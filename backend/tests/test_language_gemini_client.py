"""
test_language_gemini_client.py

Purpose
-------
Verifies `GeminiLLMClient` against the same failure-mode matrix
`test_language_llm_client.py` verifies for `OpenAICompatibleLLMClient`
-- success, non-2xx/malformed-envelope failure, timeout (with retry),
missing credentials, and credential redaction -- plus two
Gemini-specific shapes: an empty `candidates` list and a candidate
whose `finishReason` indicates a refusal rather than content. All of
`requests.post` is monkeypatched; this suite makes zero real network
calls, per this repository's requirement that LLM calls be mocked in
the unit test suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest
import requests

from language.config import LLMRuntimeConfig
from language.exceptions import ConfigurationError, LLMProviderError, LLMTimeoutError
from language.gemini_client import GeminiLLMClient
from language.llm_client import LLMRequest

_CONFIG = LLMRuntimeConfig(
    provider="gemini",
    model="gemini-flash-latest",
    base_url="https://generativelanguage.example.invalid/v1beta",
    api_key_env_var="TEST_GEMINI_API_KEY",
    timeout_seconds=1.0,
    max_retries=2,
)

_REQUEST = LLMRequest(
    system_prompt="system",
    user_message="Bring me the red mug.",
    temperature=0.1,
    top_p=0.9,
    max_tokens=128,
    frequency_penalty=0.0,
    presence_penalty=0.0,
    strict_json_mode=True,
    prompt_version="1.1.0",
    schema_version="1.0.0",
)


@dataclass
class _FakeHTTPResponse:
    status_code: int
    _json: Optional[Dict[str, Any]] = None
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Dict[str, Any]:
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


def _candidate_response(text: str = '{"task_type": "single"}') -> _FakeHTTPResponse:
    return _FakeHTTPResponse(
        status_code=200,
        _json={
            "modelVersion": "gemini-2.0-flash-001",
            "candidates": [
                {
                    "content": {"parts": [{"text": text}]},
                    "finishReason": "STOP",
                }
            ],
        },
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_GEMINI_API_KEY", "gk-super-secret-value")


class TestSuccessfulResponse:
    def test_returns_unwrapped_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            requests,
            "post",
            lambda *a, **k: _candidate_response('{"task_type": "single"}'),
        )

        response = GeminiLLMClient(_CONFIG).complete(_REQUEST)

        assert response.content == '{"task_type": "single"}'
        assert response.provider == "gemini"
        assert response.model == "gemini-2.0-flash-001"
        assert response.latency_ms >= 0.0

    def test_concatenates_multiple_parts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_response = _FakeHTTPResponse(
            status_code=200,
            _json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": '{"task_type": '}, {"text": '"single"}'}]
                        },
                        "finishReason": "STOP",
                    }
                ]
            },
        )
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        response = GeminiLLMClient(_CONFIG).complete(_REQUEST)

        assert response.content == '{"task_type": "single"}'

    def test_sends_expected_request_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: Dict[str, Any] = {}

        def fake_post(
            url: str, json: Dict[str, Any], headers: Dict[str, str], timeout: float
        ) -> _FakeHTTPResponse:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _candidate_response()

        monkeypatch.setattr(requests, "post", fake_post)
        GeminiLLMClient(_CONFIG).complete(_REQUEST)

        assert captured["url"] == (
            "https://generativelanguage.example.invalid/v1beta/models/"
            "gemini-flash-latest:generateContent"
        )
        assert captured["json"]["generationConfig"]["temperature"] == 0.1
        assert (
            captured["json"]["generationConfig"]["responseMimeType"]
            == "application/json"
        )
        assert captured["json"]["system_instruction"]["parts"][0]["text"] == "system"
        assert captured["headers"]["x-goog-api-key"] == "gk-super-secret-value"
        # The API key must never appear in the URL itself.
        assert "gk-super-secret-value" not in captured["url"]


class TestGeminiSpecificFailureShapes:
    def test_empty_candidates_raises_llm_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_response = _FakeHTTPResponse(status_code=200, _json={"candidates": []})
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        with pytest.raises(LLMProviderError):
            GeminiLLMClient(_CONFIG).complete(_REQUEST)

    def test_safety_finish_reason_raises_llm_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_response = _FakeHTTPResponse(
            status_code=200,
            _json={
                "candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]
            },
        )
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        with pytest.raises(LLMProviderError):
            GeminiLLMClient(_CONFIG).complete(_REQUEST)

    def test_malformed_envelope_raises_llm_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_response = _FakeHTTPResponse(
            status_code=200, _json={"unexpected": "shape"}
        )
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        with pytest.raises(LLMProviderError):
            GeminiLLMClient(_CONFIG).complete(_REQUEST)


class TestProviderFailure:
    def test_non_2xx_status_raises_llm_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_response = _FakeHTTPResponse(status_code=500, text="internal error")
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        with pytest.raises(LLMProviderError):
            GeminiLLMClient(_CONFIG).complete(_REQUEST)


class TestTimeoutHandling:
    def test_timeout_is_retried_up_to_max_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = {"n": 0}

        def fake_post(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            raise requests.exceptions.Timeout("timed out")

        monkeypatch.setattr(requests, "post", fake_post)

        with pytest.raises(LLMTimeoutError):
            GeminiLLMClient(_CONFIG).complete(_REQUEST)

        assert call_count["n"] == _CONFIG.max_retries + 1

    def test_succeeds_after_transient_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = {"n": 0}

        def fake_post(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise requests.exceptions.Timeout("timed out")
            return _candidate_response()

        monkeypatch.setattr(requests, "post", fake_post)
        response = GeminiLLMClient(_CONFIG).complete(_REQUEST)

        assert response.content == '{"task_type": "single"}'
        assert call_count["n"] == 2


class TestConfigurationFailure:
    def test_missing_api_key_raises_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TEST_GEMINI_API_KEY", raising=False)

        with pytest.raises(ConfigurationError):
            GeminiLLMClient(_CONFIG).complete(_REQUEST)

    def test_missing_api_key_never_calls_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TEST_GEMINI_API_KEY", raising=False)
        called = {"post": False}

        def fake_post(*args: Any, **kwargs: Any) -> Any:
            called["post"] = True
            raise AssertionError("requests.post should not be called")

        monkeypatch.setattr(requests, "post", fake_post)

        with pytest.raises(ConfigurationError):
            GeminiLLMClient(_CONFIG).complete(_REQUEST)
        assert called["post"] is False


class TestNoCredentialLeakage:
    def test_api_key_not_present_in_provider_error_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_response = _FakeHTTPResponse(
            status_code=401,
            text="Unauthorized: key gk-super-secret-value is invalid",
        )
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        with pytest.raises(LLMProviderError) as excinfo:
            GeminiLLMClient(_CONFIG).complete(_REQUEST)

        assert "gk-super-secret-value" not in str(excinfo.value)
        assert "[REDACTED]" in str(excinfo.value)

    def test_api_key_not_present_in_connection_error_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_post(*args: Any, **kwargs: Any) -> Any:
            raise requests.exceptions.ConnectionError(
                "failed with x-goog-api-key: gk-super-secret-value"
            )

        monkeypatch.setattr(requests, "post", fake_post)

        with pytest.raises(LLMProviderError) as excinfo:
            GeminiLLMClient(_CONFIG).complete(_REQUEST)

        assert "gk-super-secret-value" not in str(excinfo.value)
