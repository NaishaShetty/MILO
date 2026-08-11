"""
test_api_language.py

Purpose
-------
Verifies Phase 3.7's `POST /api/v1/language/parse` endpoint behaves as
a *thin* HTTP wrapper around `LanguageAgent`: it validates the request
body, delegates entirely to a `LanguageAgent` (injected via
`app.dependency_overrides`, never a real one), serializes a successful
`ParseOutcome` using the real `schemas.task` models, and maps every
`LanguageRuntimeError` subclass to a safe, credential-free HTTP
response. No real LLM call, network access, or `LanguageAgent.from_config()`
construction happens anywhere in this suite -- see
`test_language_agent.py`'s own docstring for why this repository
requires LLM calls to stay mocked in the unit test suite; the same
requirement applies here, one layer up.
"""

from __future__ import annotations

from typing import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routes.language import get_language_agent
from language.agent import ParseOutcome
from language.exceptions import (
    ConfigurationError,
    LLMProviderError,
    LLMTimeoutError,
    PromptLoadError,
    ResponseParsingError,
    RetryExhaustedError,
    SemanticValidationError,
    TaskValidationError,
)
from language.failures import FailureCategory, FailureRecord, RuntimeMetadata
from schemas.task import MultiTask, SingleTask

_METADATA = RuntimeMetadata(
    provider="gemini",
    model="gemini-flash-latest",
    prompt_version="1.1.0",
    schema_version="1.0.0",
    attempt_number=1,
    latency_ms=742.0,
    recovered=False,
)


def _override_agent(fake_agent: MagicMock) -> None:
    app.dependency_overrides[get_language_agent] = lambda: fake_agent


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    # `raise_server_exceptions=False` matches how this app actually
    # behaves in production: unhandled exceptions are caught by
    # `api/app.py`'s catch-all handler and turned into a JSON 500, not
    # re-raised -- see that module's `_handle_unexpected_error`.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Successful parses
# ---------------------------------------------------------------------------


def test_valid_request_returns_single_task(client: TestClient) -> None:
    fake_agent = MagicMock()
    fake_agent.parse_with_diagnostics.return_value = ParseOutcome(
        instruction=SingleTask(goal="bring", object="mug"),
        metadata=_METADATA,
    )
    _override_agent(fake_agent)

    response = client.post(
        "/api/v1/language/parse", json={"instruction": "Bring me the red mug."}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["result"]["task_type"] == "single"
    assert body["result"]["goal"] == "bring"
    assert body["result"]["object"] == "mug"
    assert body["diagnostics"] == {
        "provider": "gemini",
        "model": "gemini-flash-latest",
        "prompt_version": "1.1.0",
        "schema_version": "1.0.0",
        "attempt_count": 1,
        "latency_ms": 742.0,
        "recovered": False,
    }
    fake_agent.parse_with_diagnostics.assert_called_once_with("Bring me the red mug.")


def test_multi_task_response(client: TestClient) -> None:
    fake_agent = MagicMock()
    fake_agent.parse_with_diagnostics.return_value = ParseOutcome(
        instruction=MultiTask(
            goal="navigate_and_find",
            subtasks=[
                SingleTask(goal="navigate_to", target_location="kitchen"),
                SingleTask(goal="find", object="bottle"),
            ],
        ),
        metadata=_METADATA,
    )
    _override_agent(fake_agent)

    response = client.post(
        "/api/v1/language/parse",
        json={"instruction": "Go to the kitchen and find the bottle."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["task_type"] == "multi"
    assert len(body["result"]["subtasks"]) == 2
    assert body["result"]["subtasks"][0]["goal"] == "navigate_to"
    assert body["result"]["subtasks"][1]["object"] == "bottle"


def test_clarification_required_is_a_200(client: TestClient) -> None:
    fake_agent = MagicMock()
    fake_agent.parse_with_diagnostics.return_value = ParseOutcome(
        instruction=SingleTask(
            goal="bring",
            object="mug",
            needs_clarification=True,
            clarification_reason="Multiple mugs may exist.",
        ),
        metadata=_METADATA,
    )
    _override_agent(fake_agent)

    response = client.post(
        "/api/v1/language/parse", json={"instruction": "Bring me the mug."}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "clarification_required"
    assert body["result"]["needs_clarification"] is True
    assert body["result"]["clarification_reason"] == "Multiple mugs may exist."


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


def test_empty_instruction_is_rejected(client: TestClient) -> None:
    fake_agent = MagicMock()
    _override_agent(fake_agent)

    response = client.post("/api/v1/language/parse", json={"instruction": ""})

    assert response.status_code == 422
    body = response.json()
    assert body["category"] == "invalid_request"
    fake_agent.parse_with_diagnostics.assert_not_called()


def test_whitespace_only_instruction_is_rejected(client: TestClient) -> None:
    fake_agent = MagicMock()
    _override_agent(fake_agent)

    response = client.post("/api/v1/language/parse", json={"instruction": "   "})

    assert response.status_code == 422
    assert response.json()["category"] == "invalid_request"
    fake_agent.parse_with_diagnostics.assert_not_called()


def test_missing_instruction_field_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/language/parse", json={})

    assert response.status_code == 422
    assert response.json()["category"] == "invalid_request"


def test_non_string_instruction_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/language/parse", json={"instruction": 42})

    assert response.status_code == 422
    assert response.json()["category"] == "invalid_request"


def test_oversized_instruction_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/language/parse", json={"instruction": "x" * 5000})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Runtime failure mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exception, expected_status, expected_category",
    [
        (LLMTimeoutError("timed out"), 504, "timeout"),
        (LLMProviderError("bad status"), 503, "provider_unavailable"),
        (ConfigurationError("missing api key"), 503, "configuration_error"),
        (PromptLoadError("missing asset"), 500, "internal_error"),
        (SemanticValidationError("object required"), 502, "upstream_invalid_response"),
        (TaskValidationError("bad enum"), 502, "upstream_invalid_response"),
        (ResponseParsingError("not json"), 502, "upstream_invalid_response"),
    ],
)
def test_runtime_failures_map_to_safe_http_responses(
    client: TestClient,
    exception: Exception,
    expected_status: int,
    expected_category: str,
) -> None:
    fake_agent = MagicMock()
    fake_agent.parse_with_diagnostics.side_effect = exception
    _override_agent(fake_agent)

    response = client.post(
        "/api/v1/language/parse", json={"instruction": "Bring me the red mug."}
    )

    assert response.status_code == expected_status
    body = response.json()
    assert body["category"] == expected_category
    assert "message" in body
    # Never leak the raw exception text verbatim into the response.
    assert str(exception) not in body["message"]


def test_retry_exhausted_defaults_to_upstream_invalid_response(
    client: TestClient,
) -> None:
    fake_agent = MagicMock()
    fake_agent.parse_with_diagnostics.side_effect = RetryExhaustedError(
        "exhausted",
        failures=[
            FailureRecord(
                category=FailureCategory.SCHEMA_VALIDATION_ERROR,
                stage="schema_validation",
                message="missing field",
                retryable=True,
                attempt_number=3,
            )
        ],
    )
    _override_agent(fake_agent)

    response = client.post(
        "/api/v1/language/parse", json={"instruction": "Bring me the red mug."}
    )

    assert response.status_code == 502
    assert response.json()["category"] == "upstream_invalid_response"


def test_retry_exhausted_after_timeouts_maps_to_timeout(client: TestClient) -> None:
    fake_agent = MagicMock()
    fake_agent.parse_with_diagnostics.side_effect = RetryExhaustedError(
        "exhausted",
        failures=[
            FailureRecord(
                category=FailureCategory.LLM_TIMEOUT,
                stage="llm_call",
                message="timed out",
                retryable=True,
                attempt_number=3,
            )
        ],
    )
    _override_agent(fake_agent)

    response = client.post(
        "/api/v1/language/parse", json={"instruction": "Bring me the red mug."}
    )

    assert response.status_code == 504
    assert response.json()["category"] == "timeout"


def test_provider_error_message_never_leaks_credentials(client: TestClient) -> None:
    fake_agent = MagicMock()
    fake_agent.parse_with_diagnostics.side_effect = LLMProviderError(
        "Authorization: Bearer sk-super-secret-key rejected"
    )
    _override_agent(fake_agent)

    response = client.post(
        "/api/v1/language/parse", json={"instruction": "Bring me the red mug."}
    )

    assert response.status_code == 503
    assert "sk-super-secret-key" not in response.text
    assert "Bearer" not in response.text


def test_unexpected_exception_returns_generic_500(client: TestClient) -> None:
    fake_agent = MagicMock()
    fake_agent.parse_with_diagnostics.side_effect = RuntimeError(
        "unexpected bug, api_key=sk-should-never-appear"
    )
    _override_agent(fake_agent)

    response = client.post(
        "/api/v1/language/parse", json={"instruction": "Bring me the red mug."}
    )

    assert response.status_code == 500
    body = response.json()
    assert body["category"] == "internal_error"
    assert "sk-should-never-appear" not in response.text
    assert "Traceback" not in response.text


# ---------------------------------------------------------------------------
# GET /api/v1/language -- Phase 8.5 provider status
# ---------------------------------------------------------------------------
# Bypasses the shared `client` fixture: these tests must control the
# environment *before* the app's lifespan constructs `language_config`,
# so they build their own `TestClient` after monkeypatching, exactly
# like `test_api_voice.py`'s equivalent status tests.


def test_language_status_reports_unconfigured_openai_by_default(monkeypatch) -> None:
    for name in (
        "LANGUAGE_LLM_PROVIDER",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "QWEN_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    with TestClient(app) as fresh_client:
        response = fresh_client.get("/api/v1/language")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "configured": False,
        "available": False,
    }


def test_language_status_reports_configured_when_key_present(monkeypatch) -> None:
    monkeypatch.delenv("LANGUAGE_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear")

    with TestClient(app) as fresh_client:
        response = fresh_client.get("/api/v1/language")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["available"] is True
    assert "sk-should-never-appear" not in response.text


def test_language_status_reports_qwen_provider(monkeypatch) -> None:
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "QWEN_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "qwen")

    with TestClient(app) as fresh_client:
        response = fresh_client.get("/api/v1/language")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "qwen"
    assert body["model"] == "qwen2.5-7b-instruct"
    assert body["configured"] is False
