"""
test_language_recovery.py

Purpose
-------
Verifies `RecoveryEngine`'s attempt loop against every documented Phase
3.5 retry-policy behavior: a clean first-attempt success, a retryable
failure that succeeds on a later attempt (and is correctly reported as
`recovered=True`), a non-retryable configuration failure that fails
immediately regardless of `RetryPolicy`, retry exhaustion producing a
structured `RetryExhaustedError`, and -- critically -- that with the
default `RetryPolicy()` (`max_retries=0`) a single failure re-raises
the *original* exception completely unmodified, preserving Phase 3.4's
exact behavior. Every collaborator is a `MagicMock`/fake; this suite
makes zero network calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from language.exceptions import (
    ConfigurationError,
    LLMProviderError,
    LLMTimeoutError,
    ResponseParsingError,
    RetryExhaustedError,
    SemanticValidationError,
    TaskValidationError,
)
from language.failures import FailureCategory
from language.llm_client import LLMRequest, LLMResponse
from language.recovery import RecoveryEngine, RetryPolicy
from language.repair import SafeResponseRepairer
from schemas.task import SingleTask

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


def _response(content: str = '{"task_type": "single", "goal": "fetch"}') -> LLMResponse:
    return LLMResponse(
        content=content, provider="fake", model="fake-model", latency_ms=1.0
    )


class TestSingleAttemptBackwardCompatibility:
    def test_clean_success_returns_outcome(self) -> None:
        llm_client = MagicMock()
        llm_client.complete.return_value = _response()
        response_parser = MagicMock()
        response_parser.parse.return_value = {"task_type": "single", "goal": "fetch"}
        schema_validator = MagicMock()
        schema_validator.validate.return_value = SingleTask(goal="fetch")

        engine = RecoveryEngine(llm_client, response_parser, schema_validator)
        outcome = engine.run(_REQUEST)

        assert outcome.instruction.goal == "fetch"
        assert outcome.metadata.attempt_number == 1
        assert outcome.metadata.recovered is False
        assert outcome.metadata.last_failure is None

    def test_default_policy_reraises_original_exception_unmodified(self) -> None:
        llm_client = MagicMock()
        original = LLMProviderError("provider unreachable")
        llm_client.complete.side_effect = original
        response_parser = MagicMock()
        schema_validator = MagicMock()

        engine = RecoveryEngine(llm_client, response_parser, schema_validator)

        with pytest.raises(LLMProviderError) as excinfo:
            engine.run(_REQUEST)
        assert excinfo.value is original
        llm_client.complete.assert_called_once()

    def test_configuration_error_never_retried_even_with_policy(self) -> None:
        llm_client = MagicMock()
        original = ConfigurationError("missing API key")
        llm_client.complete.side_effect = original
        response_parser = MagicMock()
        schema_validator = MagicMock()

        engine = RecoveryEngine(
            llm_client,
            response_parser,
            schema_validator,
            retry_policy=RetryPolicy(max_retries=3),
        )

        with pytest.raises(ConfigurationError) as excinfo:
            engine.run(_REQUEST)
        assert excinfo.value is original
        llm_client.complete.assert_called_once()


class TestRetrySucceedsOnLaterAttempt:
    def test_llm_timeout_then_success(self) -> None:
        llm_client = MagicMock()
        llm_client.complete.side_effect = [
            LLMTimeoutError("timed out"),
            _response(),
        ]
        response_parser = MagicMock()
        response_parser.parse.return_value = {"task_type": "single", "goal": "fetch"}
        schema_validator = MagicMock()
        schema_validator.validate.return_value = SingleTask(goal="fetch")

        engine = RecoveryEngine(
            llm_client,
            response_parser,
            schema_validator,
            retry_policy=RetryPolicy(max_retries=1),
        )
        outcome = engine.run(_REQUEST)

        assert outcome.metadata.attempt_number == 2
        assert outcome.metadata.recovered is True
        assert outcome.metadata.last_failure == FailureCategory.LLM_TIMEOUT
        assert llm_client.complete.call_count == 2

    def test_schema_validation_error_then_success(self) -> None:
        llm_client = MagicMock()
        llm_client.complete.return_value = _response()
        response_parser = MagicMock()
        response_parser.parse.return_value = {"task_type": "single"}
        schema_validator = MagicMock()
        schema_validator.validate.side_effect = [
            TaskValidationError("bad task", original_error=None),
            SingleTask(goal="fetch"),
        ]

        engine = RecoveryEngine(
            llm_client,
            response_parser,
            schema_validator,
            retry_policy=RetryPolicy(max_retries=1),
        )
        outcome = engine.run(_REQUEST)

        assert outcome.metadata.recovered is True
        assert outcome.metadata.last_failure == FailureCategory.SCHEMA_VALIDATION_ERROR

    def test_semantic_validation_error_then_success(self) -> None:
        llm_client = MagicMock()
        llm_client.complete.return_value = _response()
        response_parser = MagicMock()
        response_parser.parse.return_value = {"task_type": "single"}
        schema_validator = MagicMock()
        schema_validator.validate.return_value = SingleTask(goal="fetch")
        semantic_validator = MagicMock()
        semantic_validator.validate.side_effect = [
            SemanticValidationError("implausible"),
            None,
        ]

        engine = RecoveryEngine(
            llm_client,
            response_parser,
            schema_validator,
            semantic_validator=semantic_validator,
            retry_policy=RetryPolicy(max_retries=1),
        )
        outcome = engine.run(_REQUEST)

        assert outcome.metadata.recovered is True
        assert (
            outcome.metadata.last_failure == FailureCategory.SEMANTIC_VALIDATION_ERROR
        )
        assert semantic_validator.validate.call_count == 2


class TestSafeRepair:
    def test_response_repaired_and_parsed_on_same_attempt(self) -> None:
        wrapped = 'Sure! ```json\n{"task_type": "single", "goal": "fetch"}\n``` Hope that helps.'
        llm_client = MagicMock()
        llm_client.complete.return_value = _response(wrapped)
        response_parser = MagicMock()
        # First call (raw content) fails, second call (repaired content) succeeds.
        response_parser.parse.side_effect = [
            ResponseParsingError("not valid JSON"),
            {"task_type": "single", "goal": "fetch"},
        ]
        schema_validator = MagicMock()
        schema_validator.validate.return_value = SingleTask(goal="fetch")

        engine = RecoveryEngine(llm_client, response_parser, schema_validator)
        outcome = engine.run(_REQUEST)

        assert outcome.metadata.attempt_number == 1
        assert outcome.metadata.recovered is True
        assert llm_client.complete.call_count == 1

    def test_unrepairable_response_reraises_original_on_first_failure(self) -> None:
        llm_client = MagicMock()
        llm_client.complete.return_value = _response("not json at all")
        response_parser = MagicMock()
        original = ResponseParsingError("not valid JSON")
        response_parser.parse.side_effect = original
        schema_validator = MagicMock()

        engine = RecoveryEngine(llm_client, response_parser, schema_validator)

        with pytest.raises(ResponseParsingError) as excinfo:
            engine.run(_REQUEST)
        assert excinfo.value is original


class TestRetryExhaustion:
    def test_exhausted_after_configured_retries_raises_structured_error(self) -> None:
        llm_client = MagicMock()
        llm_client.complete.side_effect = LLMProviderError("always fails")
        response_parser = MagicMock()
        schema_validator = MagicMock()

        engine = RecoveryEngine(
            llm_client,
            response_parser,
            schema_validator,
            retry_policy=RetryPolicy(max_retries=2),
        )

        with pytest.raises(RetryExhaustedError) as excinfo:
            engine.run(_REQUEST)

        assert llm_client.complete.call_count == 3
        assert len(excinfo.value.failures) == 3
        assert excinfo.value.last_failure is not None
        assert excinfo.value.last_failure.category == FailureCategory.LLM_PROVIDER_ERROR
        assert all(f.retryable for f in excinfo.value.failures)

    def test_unrepairable_garbage_is_retried_as_invalid_json(self) -> None:
        # No fence, no balanced braces at all -- SafeResponseRepairer
        # finds no candidate, so this is classified INVALID_JSON (a
        # retryable category) rather than SAFE_REPAIR_FAILED.
        llm_client = MagicMock()
        llm_client.complete.return_value = _response("garbage, not json")
        response_parser = MagicMock()
        response_parser.parse.side_effect = ResponseParsingError("not valid JSON")
        schema_validator = MagicMock()

        engine = RecoveryEngine(
            llm_client,
            response_parser,
            schema_validator,
            repairer=SafeResponseRepairer(),
            retry_policy=RetryPolicy(max_retries=1),
        )

        with pytest.raises(RetryExhaustedError) as excinfo:
            engine.run(_REQUEST)
        assert llm_client.complete.call_count == 2
        last_failure = excinfo.value.last_failure
        assert last_failure is not None
        assert last_failure.category == FailureCategory.INVALID_JSON

    def test_repair_produces_still_unparseable_text_is_terminal(self) -> None:
        # Simulates a `SafeResponseRepairer` (via a fake) that claims
        # to have found a candidate, but the candidate still fails
        # `ResponseParser.parse()` -- the SAFE_REPAIR_FAILED path.
        # Terminal even with retries configured, per this module's
        # docstring: a failed repair is not retried further.
        llm_client = MagicMock()
        llm_client.complete.return_value = _response("some wrapped content")
        response_parser = MagicMock()
        response_parser.parse.side_effect = [
            ResponseParsingError("not valid JSON"),
            ResponseParsingError("still not valid JSON"),
        ]
        schema_validator = MagicMock()
        fake_repairer = MagicMock()
        fake_repairer.repair.return_value = "still-not-json"

        engine = RecoveryEngine(
            llm_client,
            response_parser,
            schema_validator,
            repairer=fake_repairer,
            retry_policy=RetryPolicy(max_retries=2),
        )

        with pytest.raises(ResponseParsingError):
            engine.run(_REQUEST)
        llm_client.complete.assert_called_once()
