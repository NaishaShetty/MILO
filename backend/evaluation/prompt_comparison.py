"""
prompt_comparison.py

Purpose
-------
Phase 3.6.5 -- Prompt Version Comparison. Structurally mirrors
`provider_comparison.py`, but each `PromptRunSpec` varies only its
`PromptBuilder` (built from a distinct `PromptAssetPaths` -- a
different `parser_prompt.txt`/`prompt_config.yaml` pair, and therefore
a different `prompt_version`), holding provider, model, schema
version, and recovery policy fixed. This is the seam the spec's
"Prompt Ablation Readiness" section asks for: a future zero-shot vs.
few-shot comparison, or a different example set, is just another
`PromptRunSpec` pointing at a different `PromptAssetPaths` -- no change
to this module or `benchmark_runner.py` is required to add one.

Every `LanguageAgentFactory` passed in via a `PromptRunSpec` must share
the same `default_llm_client`/`response_parser`/`schema_validator`/
`semantic_validator`/`retry_policy` across specs -- this module does
not enforce that itself (it has no way to, since it only receives
already-built factories), so callers (`run_benchmark.py`, tests) are
responsible for constructing specs that hold everything but the prompt
builder constant, exactly as `provider_comparison.py`'s callers are
responsible for holding everything but the LLM client constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from evaluation.benchmark_runner import BenchmarkRunner, LanguageAgentFactory
from evaluation.evaluator import ResultEvaluator
from evaluation.metrics import MetricsCalculator, pooled_metric_value
from evaluation.models import (
    BenchmarkCase,
    PromptComparisonReport,
    PromptComparisonRow,
    RunMode,
    generate_run_id,
)


@dataclass
class PromptRunSpec:
    """One prompt-version configuration to benchmark, sharing every other variable."""

    prompt_version: str
    provider: str
    model: str
    agent_factory: LanguageAgentFactory
    case_limit: Optional[int] = None
    run_mode: RunMode = RunMode.MOCKED


class PromptVersionComparisonRunner:
    """Phase 3.6.5's sole public entry point -- see module docstring."""

    def __init__(
        self,
        benchmark_runner_factory: Callable[..., BenchmarkRunner] = BenchmarkRunner,
        evaluator: Optional[ResultEvaluator] = None,
        metrics_calculator: Optional[MetricsCalculator] = None,
    ) -> None:
        self._benchmark_runner_factory = benchmark_runner_factory
        self._evaluator = evaluator or ResultEvaluator()
        self._metrics_calculator = metrics_calculator or MetricsCalculator()

    def run(
        self, cases: Sequence[BenchmarkCase], specs: Sequence[PromptRunSpec]
    ) -> PromptComparisonReport:
        rows: List[PromptComparisonRow] = []
        for spec in specs:
            runner = self._benchmark_runner_factory(
                spec.agent_factory, case_limit=spec.case_limit, run_mode=spec.run_mode
            )
            records = runner.run(cases)
            records_by_id = {record.case_id: record for record in records}
            evaluations = [
                self._evaluator.evaluate(case, records_by_id[case.case_id])
                for case in cases
                if case.case_id in records_by_id
            ]
            report = self._metrics_calculator.compute(evaluations, records)

            # Reuses `metrics.pooled_metric_value` rather than
            # duplicating the same numerator/denominator-pooling logic
            # `provider_comparison.py` already uses -- see that
            # function's docstring for why it is correct here too (it
            # only pools by metric name, agnostic to what's actually
            # being varied).
            rows.append(
                PromptComparisonRow(
                    prompt_version=spec.prompt_version,
                    provider=spec.provider,
                    model=spec.model,
                    run_id=generate_run_id(f"prompt-{spec.prompt_version}"),
                    task_accuracy=report.overall.task_accuracy_micro.value,
                    goal_accuracy=pooled_metric_value(report, "goal_accuracy"),
                    object_accuracy=pooled_metric_value(report, "object_accuracy"),
                    clarification_accuracy=pooled_metric_value(
                        report, "clarification_accuracy"
                    ),
                    recovery_rate=pooled_metric_value(report, "recovery_rate"),
                    average_latency_ms=report.overall.latency_stats.average_ms,
                )
            )
        return PromptComparisonReport(rows=rows)
