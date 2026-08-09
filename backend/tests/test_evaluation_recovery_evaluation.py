"""
test_evaluation_recovery_evaluation.py

Purpose
-------
Verifies `evaluation.recovery_evaluation.RecoveryEvaluator` end to end
against real `BenchmarkRunner` + `ResultEvaluator` output (real prompt
assets, fake `LLMClient`s scripted to fail then succeed, or fail
permanently) -- no network access. Covers: initial failure + successful
recovery, initial failure + failed recovery, retry counting, recovery
rate, and per-category breakdown.
"""

from __future__ import annotations

import json
from typing import List

from evaluation.benchmark_runner import BenchmarkRunner, LanguageAgentFactory
from evaluation.evaluator import ResultEvaluator
from evaluation.models import BenchmarkCase, DatasetCategory
from evaluation.recovery_evaluation import RecoveryEvaluator
from language.config import PromptAssetPaths
from language.exceptions import LLMProviderError
from language.llm_client import LLMRequest, LLMResponse
from language.prompt_builder import PromptBuilder
from language.recovery import RetryPolicy
from language.response_parser import ResponseParser
from language.schema_validator import SchemaValidator

_EXPECTED = {
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


def _case(case_id: str) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=case_id,
        dataset=DatasetCategory.SUCCESS,
        category="simple",
        instruction="turn off the hallway light",
        expected_output=_EXPECTED,
    )


class _QueueLLMClient:
    def __init__(self, responses: List[str]) -> None:
        self._responses = list(responses)

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self._responses:
            raise LLMProviderError("queue exhausted")
        content = self._responses.pop(0)
        return LLMResponse(
            content=content, provider="fake", model="fake-model", latency_ms=1.0
        )


def _factory(llm_client) -> LanguageAgentFactory:
    paths = PromptAssetPaths.from_env()
    return LanguageAgentFactory(
        prompt_builder=PromptBuilder(paths),
        default_llm_client=llm_client,
        response_parser=ResponseParser(),
        schema_validator=SchemaValidator(),
        retry_policy=RetryPolicy(max_retries=2),
    )


def _run(cases, llm_client):
    runner = BenchmarkRunner(_factory(llm_client))
    records = runner.run(cases)
    records_by_id = {r.case_id: r for r in records}
    evaluations = [
        ResultEvaluator().evaluate(case, records_by_id[case.case_id]) for case in cases
    ]
    return evaluations, records


class TestRecoverySuccess:
    def test_initial_failure_then_successful_recovery(self) -> None:
        evaluations, records = _run(
            [_case("r1")], _QueueLLMClient(["not json", json.dumps(_EXPECTED)])
        )
        report = RecoveryEvaluator().evaluate(evaluations, records)
        assert report.initial_success_rate.value == 0.0
        assert report.recovery_attempt_rate.value == 1.0
        assert report.recovery_success_rate.value == 1.0
        assert report.final_success_rate.value == 1.0
        assert report.average_retries_for_recovered == 1.0


class TestRecoveryFailure:
    def test_initial_failure_and_failed_recovery(self) -> None:
        evaluations, records = _run([_case("r2")], _QueueLLMClient(["not json"] * 5))
        report = RecoveryEvaluator().evaluate(evaluations, records)
        assert report.final_success_rate.value == 0.0
        assert report.unrecovered_failure_rate.value == 1.0
        assert report.recovery_success_rate.value == 0.0
        assert report.average_retries_for_recovered is None
        assert any(
            entry.category == "invalid_json" and entry.unrecovered == 1
            for entry in report.breakdown_by_category
        )


class TestMixedRecoveryPopulation:
    def test_retry_counting_and_breakdown_across_multiple_cases(self) -> None:
        first_client = _QueueLLMClient([json.dumps(_EXPECTED)])
        second_client = _QueueLLMClient(["not json", json.dumps(_EXPECTED)])
        third_client = _QueueLLMClient(["not json"] * 5)

        clean_evaluations, clean_records = _run([_case("clean")], first_client)
        recovered_evaluations, recovered_records = _run(
            [_case("recovered")], second_client
        )
        failed_evaluations, failed_records = _run([_case("failed")], third_client)

        evaluations = clean_evaluations + recovered_evaluations + failed_evaluations
        records = clean_records + recovered_records + failed_records

        report = RecoveryEvaluator().evaluate(evaluations, records)
        assert report.total_cases == 3
        assert report.initial_success_rate.numerator == 1
        assert report.recovery_attempt_rate.numerator == 2
        assert report.recovery_success_rate.numerator == 1
        assert report.recovery_success_rate.denominator == 2
        assert report.unrecovered_failure_rate.numerator == 1
