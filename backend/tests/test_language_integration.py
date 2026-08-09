"""
test_language_integration.py

Purpose
-------
The one deterministic end-to-end test of the full Language Parsing
Runtime pipeline against this repository's *real* Phase 3.3 prompt
assets (`backend/prompts/parser_prompt.txt`,
`backend/prompts/prompt_config.yaml`) and *real* Phase 3.2 schema
(`schemas/task.py`) -- only `LLMClient` is a fake, returning a
hand-written mock LLM response. No API key, no network access, and no
mocking framework patching internals are required to run this test.

Why this test exists alongside the per-component unit tests
------------------------------------------------------------------
`test_language_agent.py` verifies `LanguageAgent` orchestrates its
(mocked) collaborators correctly. `test_language_prompt_builder.py`,
`test_language_response_parser.py`, and `test_language_schema_validator.py`
verify each collaborator in isolation. None of those, individually,
proves the *real* `PromptBuilder` + `ResponseParser` + `SchemaValidator`
combination actually works end to end against this repository's actual
asset files -- e.g. that `PromptAssetPaths.from_env()`'s default paths
really resolve to the real `backend/prompts/` files from wherever
pytest is invoked. This test is that proof.
"""

from __future__ import annotations

import json

import pytest

from language.agent import LanguageAgent
from language.config import PromptAssetPaths
from language.exceptions import ResponseParsingError, TaskValidationError
from language.llm_client import LLMRequest, LLMResponse
from language.prompt_builder import PromptBuilder
from language.response_parser import ResponseParser
from language.schema_validator import SchemaValidator
from schemas.task import MultiTask, SingleTask


class _MockLLMClient:
    """
    A hand-written fake satisfying the `LLMClient` protocol
    structurally (see `llm_client.py`) -- no inheritance, no mocking
    framework. Returns whatever `content` it was constructed with,
    letting each test control exactly what the "model" says without
    ever making a network call.
    """

    def __init__(self, content: str) -> None:
        self._content = content
        self.received_request: LLMRequest | None = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.received_request = request
        return LLMResponse(
            content=self._content, provider="mock", model="mock-model", latency_ms=0.5
        )


def _build_agent(mock_llm_content: str) -> tuple[LanguageAgent, _MockLLMClient]:
    paths = PromptAssetPaths.from_env()
    mock_client = _MockLLMClient(mock_llm_content)
    agent = LanguageAgent(
        prompt_builder=PromptBuilder(paths),
        llm_client=mock_client,
        response_parser=ResponseParser(),
        schema_validator=SchemaValidator(),
    )
    return agent, mock_client


class TestEndToEndMockedParsing:
    def test_bring_me_the_red_mug_produces_a_valid_single_task(self) -> None:
        mock_output = {
            "task_type": "single",
            "task_id": None,
            "goal": "fetch",
            "object": "red mug",
            "target": None,
            "source_location": None,
            "target_location": None,
            "attributes": {"color": "red"},
            "constraints": None,
            "priority": None,
            "preconditions": None,
            "postconditions": None,
            "estimated_goal": "the red mug is delivered to the user",
            "needs_clarification": False,
            "clarification_reason": None,
        }
        agent, mock_client = _build_agent(json.dumps(mock_output))

        result = agent.parse("Bring me the red mug.")

        assert isinstance(result, SingleTask)
        assert result.goal == "fetch"
        assert result.object == "red mug"
        assert result.attributes is not None
        assert result.attributes.color == "red"
        assert result.needs_clarification is False

        # The real PromptBuilder must have loaded the real
        # parser_prompt.txt as the system message and passed the raw
        # instruction through unmodified.
        assert mock_client.received_request is not None
        assert len(mock_client.received_request.system_prompt) > 0
        assert mock_client.received_request.user_message == "Bring me the red mug."

    def test_ambiguous_instruction_produces_needs_clarification_task(self) -> None:
        mock_output = {
            "task_type": "single",
            "task_id": None,
            "goal": None,
            "needs_clarification": True,
            "clarification_reason": "The instruction does not specify which object to move.",
        }
        agent, _ = _build_agent(json.dumps(mock_output))

        result = agent.parse("Move it over there.")

        assert isinstance(result, SingleTask)
        assert result.needs_clarification is True
        assert result.clarification_reason is not None

    def test_malformed_llm_output_raises_response_parsing_error(self) -> None:
        agent, _ = _build_agent("this is not JSON at all")

        with pytest.raises(ResponseParsingError):
            agent.parse("Bring me the red mug.")

    def test_schema_invalid_llm_output_raises_task_validation_error(self) -> None:
        # Syntactically valid JSON, but violates a Phase 3.2 invariant
        # (needs_clarification=True requires a non-null reason).
        mock_output = {
            "task_type": "single",
            "needs_clarification": True,
            "clarification_reason": None,
        }
        agent, _ = _build_agent(json.dumps(mock_output))

        with pytest.raises(TaskValidationError):
            agent.parse("put it there")

    def test_multi_task_instruction_produces_valid_multi_task(self) -> None:
        mock_output = {
            "task_type": "multi",
            "task_id": None,
            "needs_clarification": False,
            "subtasks": [
                {
                    "task_type": "single",
                    "goal": "pick_up",
                    "object": "cup",
                    "needs_clarification": False,
                },
                {
                    "task_type": "single",
                    "goal": "navigate_to",
                    "target_location": "office",
                    "needs_clarification": False,
                },
            ],
        }
        agent, _ = _build_agent(json.dumps(mock_output))

        result = agent.parse("Pick up the cup, then take it to the office.")

        assert isinstance(result, MultiTask)
        assert len(result.subtasks) == 2
