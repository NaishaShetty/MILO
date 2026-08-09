"""
provider_comparison.py

Purpose
-------
Phase 3.6.4 -- Provider Comparison. Runs the identical benchmark
dataset, through identical evaluation rules, against multiple
`LanguageAgentFactory` configurations that differ only in their
`LLMClient` (provider/model) -- and produces the comparison table the
spec describes, generated from real results rather than hardcoded.

Fair comparison, per the spec
------------------------------
"Keep constant: Dataset, evaluation rules, prompt version, schema
version, benchmark version, recovery policy, metric definitions. Only
change: provider, model, provider-specific configuration." A
`ProviderRunSpec` therefore carries a full `LanguageAgentFactory`
(built by the caller with identical `prompt_builder`/
`response_parser`/`schema_validator`/`semantic_validator`/
`retry_policy` across every spec) -- this module has no way to
accidentally vary anything except what each spec's factory actually
varies. No case is ever dropped because a provider failed it: a
provider that cannot complete a case is scored the same way any other
failure is scored (see `evaluator.py`), never silently excluded or
treated as a success.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from evaluation.benchmark_runner import BenchmarkRunner, LanguageAgentFactory
from evaluation.evaluator import ResultEvaluator
from evaluation.metrics import MetricsCalculator, pooled_metric_value
from evaluation.models import (
    BenchmarkCase,
    ProviderComparisonReport,
    ProviderComparisonRow,
    RunMode,
    generate_run_id,
)


@dataclass
class ProviderRunSpec:
    """One provider/model configuration to benchmark, sharing every other variable."""

    provider: str
    model: str
    agent_factory: LanguageAgentFactory
    case_limit: Optional[int] = None
    run_mode: RunMode = RunMode.MOCKED


class ProviderComparisonRunner:
    """Phase 3.6.4's sole public entry point -- see module docstring."""

    def __init__(
        self,
        benchmark_runner_factory: Callable[..., BenchmarkRunner] = BenchmarkRunner,
        evaluator: Optional[ResultEvaluator] = None,
        metrics_calculator: Optional[MetricsCalculator] = None,
    ) -> None:
        # Constructor-injected collaborators (not hardcoded module-level
        # instances) so a test can substitute a fake `MetricsCalculator`
        # to check that `ProviderComparisonRunner` wires results through
        # correctly, without re-testing `metrics.py`'s own arithmetic.
        self._benchmark_runner_factory = benchmark_runner_factory
        self._evaluator = evaluator or ResultEvaluator()
        self._metrics_calculator = metrics_calculator or MetricsCalculator()

    def run(
        self, cases: Sequence[BenchmarkCase], specs: Sequence[ProviderRunSpec]
    ) -> ProviderComparisonReport:
        rows: List[ProviderComparisonRow] = []
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

            rows.append(
                ProviderComparisonRow(
                    provider=spec.provider,
                    model=spec.model,
                    run_id=generate_run_id(f"provider-{spec.provider}-{spec.model}"),
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
        return ProviderComparisonReport(rows=rows)
