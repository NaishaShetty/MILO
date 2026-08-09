"""
test_language_agent.py

Purpose
-------
Verifies `LanguageAgent` behaves as a pure orchestrator: it invokes
`PromptBuilder`, `LLMClient`, `ResponseParser`, and `SchemaValidator`
in the correct order with the correct data flowing between them, and
propagates any collaborator's failure unmodified rather than catching
and swallowing it. Every collaborator is a mock or a hand-written fake
here -- this suite never touches the network, a real prompt file, or a
real LLM, per this repository's requirement that LLM calls be mocked
in the unit test suite.

See `test_language_integration.py` for the companion end-to-end test
that wires up the *real* `PromptBuilder`, `ResponseParser`, and
`SchemaValidator` (only `LLMClient` mocked) against this repository's
actual Phase 3.3 prompt assets.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from language.agent import LanguageAgent, ParseOutcome
from language.exceptions import (
    LLMProviderError,
    LLMTimeoutError,
    PromptLoadError,
    ResponseParsingError,
    RetryExhaustedError,
    SemanticValidationError,
    TaskValidationError,
)
from language.llm_client import LLMRequest, LLMResponse
from language.prompt_builder import PromptBuilder
from language.recovery import RetryPolicy
from language.response_parser import ResponseParser
from language.schema_validator import SchemaValidator
from language.semantic_validator import SemanticValidator
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
_RESPONSE = LLMResponse(
    content='{"task_type": "single", "goal": "fetch"}',
    provider="fake",
    model="fake-model",
    latency_ms=1.0,
)
_PARSED_DICT = {"task_type": "single", "goal": "fetch"}


def _mock_collaborators() -> tuple:
    prompt_builder = MagicMock(spec=PromptBuilder)
    prompt_builder.build.return_value = _REQUEST

    llm_client = MagicMock()
    llm_client.complete.return_value = _RESPONSE

    response_parser = MagicMock(spec=ResponseParser)
    response_parser.parse.return_value = _PARSED_DICT

    schema_validator = MagicMock(spec=SchemaValidator)
    schema_validator.validate.return_value = SingleTask(goal="fetch")

    return prompt_builder, llm_client, response_parser, schema_validator


class TestSuccessfulOrchestration:
    def test_returns_validated_parsed_instruction(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        result = agent.parse("Bring me the red mug.")

        assert isinstance(result, SingleTask)
        assert result.goal == "fetch"

    def test_prompt_builder_is_invoked_with_instruction(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        agent.parse("Bring me the red mug.")

        prompt_builder.build.assert_called_once_with("Bring me the red mug.")

    def test_llm_client_is_invoked_with_prompt_builder_output(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        agent.parse("Bring me the red mug.")

        llm_client.complete.assert_called_once_with(_REQUEST)

    def test_response_parser_is_invoked_with_llm_client_output(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        agent.parse("Bring me the red mug.")

        response_parser.parse.assert_called_once_with(_RESPONSE)

    def test_schema_validator_is_invoked_with_response_parser_output(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        agent.parse("Bring me the red mug.")

        schema_validator.validate.assert_called_once_with(_PARSED_DICT)

    def test_needs_clarification_result_is_a_successful_parse(self) -> None:
        # A task with needs_clarification=True is a *valid* result, not
        # an error -- see agent.py's module docstring. This must not
        # raise.
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        schema_validator.validate.return_value = SingleTask(
            needs_clarification=True, clarification_reason="ambiguous referent"
        )
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        result = agent.parse("put it there")

        assert result.needs_clarification is True


class TestErrorPropagation:
    def test_prompt_builder_failure_propagates(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        prompt_builder.build.side_effect = PromptLoadError("prompt file missing")
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        with pytest.raises(PromptLoadError):
            agent.parse("Bring me the red mug.")

        # Downstream collaborators must never be invoked once an
        # earlier stage has failed.
        llm_client.complete.assert_not_called()
        response_parser.parse.assert_not_called()
        schema_validator.validate.assert_not_called()

    def test_llm_client_failure_propagates(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        llm_client.complete.side_effect = LLMProviderError("provider unreachable")
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        with pytest.raises(LLMProviderError):
            agent.parse("Bring me the red mug.")

        response_parser.parse.assert_not_called()
        schema_validator.validate.assert_not_called()

    def test_response_parser_failure_propagates(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        response_parser.parse.side_effect = ResponseParsingError("invalid JSON")
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        with pytest.raises(ResponseParsingError):
            agent.parse("Bring me the red mug.")

        schema_validator.validate.assert_not_called()

    def test_schema_validator_failure_propagates(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        schema_validator.validate.side_effect = TaskValidationError(
            "invalid task", original_error=None
        )
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        with pytest.raises(TaskValidationError):
            agent.parse("Bring me the red mug.")

    def test_no_exception_is_ever_swallowed_or_replaced(self) -> None:
        # A stricter check than "some exception is raised": the exact
        # exception instance raised by the failing collaborator must
        # be the one that propagates, unmodified.
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        try:
            SingleTask(needs_clarification=True)  # missing clarification_reason
            raise AssertionError("expected ValidationError")
        except ValidationError as underlying:
            original = TaskValidationError("boom", original_error=underlying)
        schema_validator.validate.side_effect = original
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        with pytest.raises(TaskValidationError) as excinfo:
            agent.parse("Bring me the red mug.")
        assert excinfo.value is original


class TestParseWithDiagnostics:
    def test_returns_outcome_with_runtime_metadata(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        outcome = agent.parse_with_diagnostics("Bring me the red mug.")

        assert isinstance(outcome, ParseOutcome)
        assert outcome.instruction.goal == "fetch"
        assert outcome.metadata.provider == "fake"
        assert outcome.metadata.model == "fake-model"
        assert outcome.metadata.attempt_number == 1
        assert outcome.metadata.recovered is False

    def test_parse_is_implemented_in_terms_of_diagnostics(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        assert (
            agent.parse("Bring me the red mug.")
            == agent.parse_with_diagnostics("Bring me the red mug.").instruction
        )


class TestPhase35RecoveryWiring:
    """
    Verifies the Phase 3.5 opt-in collaborators (`retry_policy`,
    `semantic_validator`) actually change `LanguageAgent`'s behavior
    when explicitly supplied -- complementing
    `TestErrorPropagation`/`TestSuccessfulOrchestration` above, which
    verify the *default* (Phase-3.4-identical) behavior when they are
    not supplied.
    """

    def test_retry_policy_recovers_from_a_transient_llm_failure(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        llm_client.complete.side_effect = [LLMTimeoutError("timed out"), _RESPONSE]
        agent = LanguageAgent(
            prompt_builder,
            llm_client,
            response_parser,
            schema_validator,
            retry_policy=RetryPolicy(max_retries=1),
        )

        result = agent.parse("Bring me the red mug.")

        assert result.goal == "fetch"
        assert llm_client.complete.call_count == 2

    def test_retry_exhaustion_raises_structured_error(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        llm_client.complete.side_effect = LLMProviderError("always fails")
        agent = LanguageAgent(
            prompt_builder,
            llm_client,
            response_parser,
            schema_validator,
            retry_policy=RetryPolicy(max_retries=1),
        )

        with pytest.raises(RetryExhaustedError) as excinfo:
            agent.parse("Bring me the red mug.")
        assert len(excinfo.value.failures) == 2

    def test_semantic_validator_rejects_implausible_task_by_default_off(
        self,
    ) -> None:
        # Without an explicit semantic_validator, a semantically
        # implausible task (per semantic_validator.py's curated rules)
        # is NOT rejected -- preserving Phase 3.4 behavior exactly.
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        schema_validator.validate.return_value = SingleTask(goal="bring")
        agent = LanguageAgent(
            prompt_builder, llm_client, response_parser, schema_validator
        )

        result = agent.parse("Bring me the red mug.")
        assert result.goal == "bring"

    def test_semantic_validator_rejects_implausible_task_when_enabled(self) -> None:
        prompt_builder, llm_client, response_parser, schema_validator = (
            _mock_collaborators()
        )
        schema_validator.validate.return_value = SingleTask(goal="bring")
        agent = LanguageAgent(
            prompt_builder,
            llm_client,
            response_parser,
            schema_validator,
            semantic_validator=SemanticValidator(),
        )

        with pytest.raises(SemanticValidationError):
            agent.parse("Bring me something.")
