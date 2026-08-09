"""
test_evaluation_provider_comparison.py

Purpose
-------
Verifies `evaluation.provider_comparison.ProviderComparisonRunner`
against real prompt assets and hand-written fake `LLMClient`s
simulating two providers of different quality -- no network access.
Covers: multiple providers scored on the same dataset with the same
evaluation rules, and that a provider's failure on a case is recorded
(not silently dropped or scored as a success).
"""

from __future__ import annotations

import json

from evaluation.benchmark_runner import LanguageAgentFactory
from evaluation.models import BenchmarkCase, DatasetCategory
from evaluation.provider_comparison import ProviderComparisonRunner, ProviderRunSpec
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

_CASE = BenchmarkCase(
    case_id="success-001",
    dataset=DatasetCategory.SUCCESS,
    category="simple",
    instruction="turn off the hallway light",
    expected_output=_EXPECTED,
)


class _AlwaysCorrectClient:
    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=json.dumps(_EXPECTED),
            provider="good",
            model="good-model",
            latency_ms=1.0,
        )


class _AlwaysFailsClient:
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise LLMProviderError("simulated provider outage")


def _factory(llm_client) -> LanguageAgentFactory:
    paths = PromptAssetPaths.from_env()
    return LanguageAgentFactory(
        prompt_builder=PromptBuilder(paths),
        default_llm_client=llm_client,
        response_parser=ResponseParser(),
        schema_validator=SchemaValidator(),
        retry_policy=RetryPolicy(max_retries=0),
    )


class TestProviderComparison:
    def test_two_providers_scored_on_the_same_dataset(self) -> None:
        specs = [
            ProviderRunSpec(
                provider="good-co",
                model="good-model",
                agent_factory=_factory(_AlwaysCorrectClient()),
            ),
            ProviderRunSpec(
                provider="bad-co",
                model="bad-model",
                agent_factory=_factory(_AlwaysFailsClient()),
            ),
        ]
        report = ProviderComparisonRunner().run([_CASE], specs)
        assert len(report.rows) == 2
        good_row = next(r for r in report.rows if r.provider == "good-co")
        bad_row = next(r for r in report.rows if r.provider == "bad-co")
        assert good_row.task_accuracy == 1.0
        assert bad_row.task_accuracy == 0.0
        # A failing provider's run_id is still populated -- it was not
        # skipped or silently excluded from the comparison.
        assert good_row.run_id != bad_row.run_id

    def test_provider_failure_is_recorded_not_dropped(self) -> None:
        specs = [
            ProviderRunSpec(
                provider="bad-co",
                model="bad-model",
                agent_factory=_factory(_AlwaysFailsClient()),
            )
        ]
        report = ProviderComparisonRunner().run([_CASE], specs)
        assert len(report.rows) == 1
        assert report.rows[0].task_accuracy == 0.0
