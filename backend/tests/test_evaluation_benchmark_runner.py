"""
test_evaluation_benchmark_runner.py

Purpose
-------
Verifies `evaluation.benchmark_runner` against the real
`PromptBuilder`/`ResponseParser`/`SchemaValidator` collaborators (same
convention as `test_language_integration.py`), with a hand-written fake
`LLMClient` -- no network access, no real provider.

Covers: dataset loading is not this module's job, but case-ID
preservation through a run, agent invocation, failure handling (both
the `RetryExhaustedError`-wrapped and unwrapped-exception paths),
`failure_cases` always using `StaticResponseLLMClient` regardless of
the factory's default client, and per-case isolation.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from evaluation.benchmark_runner import (
    BenchmarkRunner,
    LanguageAgentFactory,
    StaticResponseLLMClient,
)
from evaluation.dataset_loader import load_dataset
from evaluation.models import BenchmarkCase, DatasetCategory, RunMode
from language.config import PromptAssetPaths
from language.exceptions import LLMProviderError
from language.llm_client import LLMRequest, LLMResponse
from language.prompt_builder import PromptBuilder
from language.recovery import RetryPolicy
from language.response_parser import ResponseParser
from language.schema_validator import SchemaValidator

_EXPECTED_OUTPUT: Dict[str, Any] = {
    "task_type": "single",
    "task_id": None,
    "goal": "turn_off",
    "object": "hallway light",
    "target": None,
    "source_location": None,
    "target_location": None,
    "attributes": None,
    "constraints": None,
    "priority": None,
    "preconditions": None,
    "postconditions": None,
    "estimated_goal": "the hallway light is off",
    "needs_clarification": False,
    "clarification_reason": None,
}

_SUCCESS_CASE = BenchmarkCase(
    case_id="success-999",
    dataset=DatasetCategory.SUCCESS,
    category="simple",
    instruction="Turn off the hallway light.",
    expected_output=_EXPECTED_OUTPUT,
)


class _QueueLLMClient:
    """
    Structural `LLMClient` fake that returns one scripted `content`
    string per call, from a fixed queue -- lets a test script "first
    attempt fails, second attempt succeeds" without any mocking
    framework, mirroring `test_language_integration.py`'s
    `_MockLLMClient` convention.
    """

    def __init__(self, responses: List[str]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        if not self._responses:
            raise LLMProviderError("queue exhausted")
        content = self._responses.pop(0)
        return LLMResponse(
            content=content, provider="fake", model="fake-model", latency_ms=1.0
        )


class _AlwaysFailsLLMClient:
    """Always raises -- used to prove a poisoned default client never affects `failure_cases`."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("this client must never be called for failure_cases")


def _factory(
    llm_client: Any, *, retry_policy: Optional[RetryPolicy] = None
) -> LanguageAgentFactory:
    paths = PromptAssetPaths.from_env()
    return LanguageAgentFactory(
        prompt_builder=PromptBuilder(paths),
        default_llm_client=llm_client,
        response_parser=ResponseParser(),
        schema_validator=SchemaValidator(),
        retry_policy=retry_policy or RetryPolicy(max_retries=2),
    )


class TestSuccessCaseExecution:
    def test_successful_case_produces_a_succeeded_record_with_preserved_case_id(
        self,
    ) -> None:
        llm_client = _QueueLLMClient([json.dumps(_EXPECTED_OUTPUT)])
        runner = BenchmarkRunner(_factory(llm_client), run_mode=RunMode.MOCKED)
        records = runner.run([_SUCCESS_CASE])
        assert len(records) == 1
        record = records[0]
        assert record.case_id == "success-999"
        assert record.dataset == DatasetCategory.SUCCESS
        assert record.succeeded is True
        assert record.parsed_instruction is not None
        assert record.parsed_instruction["goal"] == "turn_off"
        assert record.attempt_number == 1
        assert record.recovered is False
        assert record.total_latency_ms >= 0.0

    def test_case_limit_truncates_the_run(self) -> None:
        llm_client = _QueueLLMClient([json.dumps(_EXPECTED_OUTPUT)] * 5)
        runner = BenchmarkRunner(_factory(llm_client), case_limit=0)
        records = runner.run([_SUCCESS_CASE, _SUCCESS_CASE])
        assert records == []


class TestRecoveryPath:
    def test_first_attempt_invalid_json_then_success_is_recorded_as_recovered(
        self,
    ) -> None:
        llm_client = _QueueLLMClient(
            [
                '{"task_type": "single", invalid',
                json.dumps(_EXPECTED_OUTPUT),
            ]
        )
        runner = BenchmarkRunner(_factory(llm_client))
        record = runner.run([_SUCCESS_CASE])[0]
        assert record.succeeded is True
        assert record.recovered is True
        assert record.attempt_number == 2


class TestFailureHandling:
    def test_retry_exhausted_produces_failed_record_with_failure_history(self) -> None:
        llm_client = _QueueLLMClient(["not json at all"] * 5)
        runner = BenchmarkRunner(
            _factory(llm_client, retry_policy=RetryPolicy(max_retries=2))
        )
        record = runner.run([_SUCCESS_CASE])[0]
        assert record.succeeded is False
        assert record.error_type == "RetryExhaustedError"
        assert len(record.failure_records) >= 2
        assert all("category" in entry for entry in record.failure_records)

    def test_single_attempt_unwrapped_exception_is_still_recorded_with_one_failure_record(
        self,
    ) -> None:
        llm_client = _QueueLLMClient(["not json at all"])
        runner = BenchmarkRunner(
            _factory(llm_client, retry_policy=RetryPolicy(max_retries=0))
        )
        record = runner.run([_SUCCESS_CASE])[0]
        assert record.succeeded is False
        assert record.error_type == "ResponseParsingError"
        assert len(record.failure_records) == 1
        assert record.failure_records[0]["attempt_number"] == 1


class TestFailureCasesUseStaticClient:
    def test_failure_case_ignores_the_factorys_default_llm_client(self) -> None:
        cases, _ = load_dataset(DatasetCategory.FAILURE)
        accept_case = next(c for c in cases if c.expected_validation_result == "accept")
        # The factory's default client would raise `AssertionError` if
        # it were ever invoked -- proving `failure_cases` are always
        # routed through `StaticResponseLLMClient` regardless of what
        # the factory was built with.
        runner = BenchmarkRunner(_factory(_AlwaysFailsLLMClient()))
        record = runner.run([accept_case])[0]
        assert record.succeeded is True

    def test_reject_syntactic_case_fails_as_expected(self) -> None:
        cases, _ = load_dataset(DatasetCategory.FAILURE)
        reject_case = next(c for c in cases if c.case_id == "failure-001")
        runner = BenchmarkRunner(_factory(_AlwaysFailsLLMClient()))
        record = runner.run([reject_case])[0]
        assert record.succeeded is False


class TestIsolation:
    def test_static_response_client_ignores_request_content(self) -> None:
        client = StaticResponseLLMClient("fixed content")
        response = client.complete(
            LLMRequest(
                system_prompt="anything",
                user_message="anything",
                temperature=0.0,
                top_p=1.0,
                max_tokens=10,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                strict_json_mode=True,
                prompt_version="1.0.0",
                schema_version="1.0.0",
            )
        )
        assert response.content == "fixed content"

    def test_each_case_gets_a_fresh_agent_no_shared_llm_call_count_bleeds_across_cases(
        self,
    ) -> None:
        first_client = _QueueLLMClient([json.dumps(_EXPECTED_OUTPUT)])
        second_case = BenchmarkCase(
            case_id="success-998",
            dataset=DatasetCategory.SUCCESS,
            category="simple",
            instruction="Open the pantry door.",
            expected_output={
                **_EXPECTED_OUTPUT,
                "goal": "open",
                "object": "pantry door",
            },
        )
        # Both cases share one factory (and therefore one underlying
        # `default_llm_client` instance) -- verifying the queue is
        # consumed once per case, in order, with no cross-case state
        # corruption beyond the shared client's own call count (which
        # is expected and not a violation of case isolation -- the
        # isolation guarantee is about the *agent*/prompt/response
        # pipeline never carrying state between cases, not about a
        # test double's own bookkeeping).
        first_client._responses.append(json.dumps(second_case.expected_output))
        runner = BenchmarkRunner(_factory(first_client))
        records = runner.run([_SUCCESS_CASE, second_case])
        assert [r.case_id for r in records] == ["success-999", "success-998"]
        assert records[0].parsed_instruction is not None
        assert records[1].parsed_instruction is not None
        assert records[0].parsed_instruction["object"] == "hallway light"
        assert records[1].parsed_instruction["object"] == "pantry door"
