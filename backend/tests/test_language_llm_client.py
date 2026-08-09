"""
test_language_llm_client.py

Purpose
-------
Verifies `OpenAICompatibleLLMClient`'s behavior against every documented
failure mode -- success, provider-level failure, timeout (with retry),
missing credentials -- and, critically, that no credential value ever
appears in a raised exception's message. `requests.post` is monkeypatched
throughout: this suite makes zero real network calls, per this
repository's requirement that LLM calls be mocked in the unit test
suite so it remains deterministic and runnable in CI without an API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest
import requests

from language.config import LLMRuntimeConfig
from language.exceptions import ConfigurationError, LLMProviderError, LLMTimeoutError
from language.llm_client import LLMRequest, OpenAICompatibleLLMClient

_CONFIG = LLMRuntimeConfig(
    provider="openai",
    model="gpt-4o-mini",
    base_url="https://api.example.invalid/v1",
    api_key_env_var="TEST_LANGUAGE_API_KEY",
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
    """Minimal stand-in for `requests.Response`, only what this client reads."""

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


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_LANGUAGE_API_KEY", "sk-super-secret-value")


class TestSuccessfulResponse:
    def test_returns_unwrapped_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_response = _FakeHTTPResponse(
            status_code=200,
            _json={
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [{"message": {"content": '{"task_type": "single"}'}}],
            },
        )
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        client = OpenAICompatibleLLMClient(_CONFIG)
        response = client.complete(_REQUEST)

        assert response.content == '{"task_type": "single"}'
        assert response.provider == "openai"
        assert response.model == "gpt-4o-mini-2024-07-18"
        assert response.latency_ms >= 0.0

    def test_sends_expected_request_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: Dict[str, Any] = {}

        def fake_post(
            url: str, json: Dict[str, Any], headers: Dict[str, str], timeout: float
        ):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return _FakeHTTPResponse(
                status_code=200,
                _json={"choices": [{"message": {"content": "{}"}}]},
            )

        monkeypatch.setattr(requests, "post", fake_post)
        OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

        assert captured["url"] == "https://api.example.invalid/v1/chat/completions"
        assert captured["json"]["model"] == "gpt-4o-mini"
        assert captured["json"]["temperature"] == 0.1
        assert captured["json"]["response_format"] == {"type": "json_object"}
        assert captured["headers"]["Authorization"] == "Bearer sk-super-secret-value"
        assert captured["timeout"] == 1.0


class TestProviderFailure:
    def test_non_2xx_status_raises_llm_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_response = _FakeHTTPResponse(status_code=500, text="internal error")
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        with pytest.raises(LLMProviderError):
            OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

    def test_malformed_envelope_raises_llm_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Valid HTTP 200, but not the expected OpenAI-shaped envelope.
        fake_response = _FakeHTTPResponse(
            status_code=200, _json={"unexpected": "shape"}
        )
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        with pytest.raises(LLMProviderError):
            OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

    def test_connection_error_raises_llm_provider_error_after_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = {"n": 0}

        def fake_post(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            raise requests.exceptions.ConnectionError("connection reset")

        monkeypatch.setattr(requests, "post", fake_post)

        with pytest.raises(LLMProviderError):
            OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

        # max_retries=2 -> 3 total attempts.
        assert call_count["n"] == 3


class TestTimeoutHandling:
    def test_timeout_raises_llm_timeout_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_post(*args: Any, **kwargs: Any) -> Any:
            raise requests.exceptions.Timeout("timed out")

        monkeypatch.setattr(requests, "post", fake_post)

        with pytest.raises(LLMTimeoutError):
            OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

    def test_timeout_is_retried_up_to_max_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = {"n": 0}

        def fake_post(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            raise requests.exceptions.Timeout("timed out")

        monkeypatch.setattr(requests, "post", fake_post)

        with pytest.raises(LLMTimeoutError):
            OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

        assert call_count["n"] == _CONFIG.max_retries + 1

    def test_succeeds_after_transient_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = {"n": 0}

        def fake_post(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise requests.exceptions.Timeout("timed out")
            return _FakeHTTPResponse(
                status_code=200,
                _json={"choices": [{"message": {"content": "{}"}}]},
            )

        monkeypatch.setattr(requests, "post", fake_post)
        response = OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

        assert response.content == "{}"
        assert call_count["n"] == 2


class TestConfigurationFailure:
    def test_missing_api_key_raises_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TEST_LANGUAGE_API_KEY", raising=False)

        with pytest.raises(ConfigurationError):
            OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

    def test_missing_api_key_never_calls_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TEST_LANGUAGE_API_KEY", raising=False)
        called = {"post": False}

        def fake_post(*args: Any, **kwargs: Any) -> Any:
            called["post"] = True
            raise AssertionError("requests.post should not be called")

        monkeypatch.setattr(requests, "post", fake_post)

        with pytest.raises(ConfigurationError):
            OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)
        assert called["post"] is False


class TestNoCredentialLeakage:
    def test_api_key_not_present_in_provider_error_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_response = _FakeHTTPResponse(
            status_code=401,
            text="Unauthorized: key sk-super-secret-value is invalid",
        )
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        with pytest.raises(LLMProviderError) as excinfo:
            OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

        assert "sk-super-secret-value" not in str(excinfo.value)
        assert "[REDACTED]" in str(excinfo.value)

    def test_api_key_not_present_in_connection_error_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_post(*args: Any, **kwargs: Any) -> Any:
            # Simulate a library exception that happens to echo request
            # detail, including (hypothetically) the header value.
            raise requests.exceptions.ConnectionError(
                "failed with Authorization: Bearer sk-super-secret-value"
            )

        monkeypatch.setattr(requests, "post", fake_post)

        with pytest.raises(LLMProviderError) as excinfo:
            OpenAICompatibleLLMClient(_CONFIG).complete(_REQUEST)

        assert "sk-super-secret-value" not in str(excinfo.value)
