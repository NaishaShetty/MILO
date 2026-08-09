"""
test_evaluation_prompt_comparison.py

Purpose
-------
Verifies `evaluation.prompt_comparison.PromptVersionComparisonRunner`
against real prompt assets and a fake `LLMClient` -- no network
access. Covers: multiple prompt-version specs scored on the same
dataset/provider/model, with the version label tracked correctly per
row.
"""

from __future__ import annotations

import json

from evaluation.benchmark_runner import LanguageAgentFactory
from evaluation.models import BenchmarkCase, DatasetCategory
from evaluation.prompt_comparison import PromptRunSpec, PromptVersionComparisonRunner
from language.config import PromptAssetPaths
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
            provider="fake",
            model="fake-model",
            latency_ms=1.0,
        )


def _factory() -> LanguageAgentFactory:
    # Both specs point at the *same* real `PromptAssetPaths.from_env()`
    # here (this repository only has one prompt version checked in) --
    # what this test actually verifies is that each spec's own
    # `prompt_version` label is tracked independently on its row, which
    # is what `run_benchmark.py`/a real ablation would rely on once a
    # second prompt asset directory exists.
    paths = PromptAssetPaths.from_env()
    return LanguageAgentFactory(
        prompt_builder=PromptBuilder(paths),
        default_llm_client=_AlwaysCorrectClient(),
        response_parser=ResponseParser(),
        schema_validator=SchemaValidator(),
        retry_policy=RetryPolicy(max_retries=0),
    )


class TestPromptVersionComparison:
    def test_two_prompt_versions_are_tracked_independently(self) -> None:
        specs = [
            PromptRunSpec(
                prompt_version="1.0.0",
                provider="openai",
                model="gpt-4o-mini",
                agent_factory=_factory(),
            ),
            PromptRunSpec(
                prompt_version="1.1.0",
                provider="openai",
                model="gpt-4o-mini",
                agent_factory=_factory(),
            ),
        ]
        report = PromptVersionComparisonRunner().run([_CASE], specs)
        assert [row.prompt_version for row in report.rows] == ["1.0.0", "1.1.0"]
        assert all(row.task_accuracy == 1.0 for row in report.rows)
        assert report.rows[0].run_id != report.rows[1].run_id
