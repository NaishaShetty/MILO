"""
metrics.py

Purpose
-------
Phase 3.6.3 -- Evaluation Metrics. Aggregates a list of
`models.CaseEvaluation` (from `evaluator.py`) and their originating
`models.RawBenchmarkRecord` (from `benchmark_runner.py`) into a
`models.MetricsReport`: every metric named in the spec's section
3.6.3 (A-M), each as a `models.MetricValue` carrying its own
definition, numerator, denominator, and interpretation -- never a bare
float, per the spec's "every metric MUST have Name/Definition/Formula/
Numerator/Denominator/Interpretation" requirement.

Reported per dataset category and as an overall rollup
------------------------------------------------------------
`success_cases`, `failure_cases`, and `ambiguity_cases` measure
different capabilities (correctness, robustness, calibration
respectively) and have different sizes (15/12/10). Reporting only one
combined number would let one category dominate and would hide a
system that is strong on one dimension and weak on another -- both
things the spec explicitly warns against. `compute()` therefore always
returns metrics broken down `per_category` *and* an `overall` rollup
that reports both a micro-average (every case pooled) and a
macro-average (each category's own accuracy averaged unweighted) side
by side, per the spec's "Micro vs Macro Aggregation" requirement.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Dict, List, Optional

from evaluation.models import (
    CaseEvaluation,
    CategoryMetrics,
    DatasetCategory,
    EvaluationOutcome,
    LatencyStats,
    MetricsReport,
    MetricValue,
    OverallMetrics,
    RawBenchmarkRecord,
    RetryStats,
)

_INDEX_SUFFIX = re.compile(r"\[\d+\]$")


def _path_segments(path: str) -> List[str]:
    """Splits a `FieldComparison.path` into its dotted segments, stripping `[n]` list indices."""
    return [_INDEX_SUFFIX.sub("", part) for part in path.split(".") if part]


def _leaf(path: str) -> str:
    segments = _path_segments(path)
    return segments[-1] if segments else path


def _has_segment(path: str, name: str) -> bool:
    return name in _path_segments(path)


def _metric(
    name: str,
    definition: str,
    numerator: float,
    denominator: float,
    interpretation: str,
) -> MetricValue:
    return MetricValue(
        name=name,
        definition=definition,
        numerator=float(numerator),
        denominator=float(denominator),
        interpretation=interpretation,
    )


def _field_accuracy(
    evaluations: List[CaseEvaluation],
    name: str,
    definition: str,
    interpretation: str,
    predicate: Callable[[str], bool],
) -> MetricValue:
    """
    Pools every applicable `FieldComparison` across `evaluations` whose
    path satisfies `predicate`, and reports the match ratio. Denominator
    is the count of *applicable* comparisons only (spec: "only evaluate
    fields that are applicable to the benchmark case") -- a dataset with
    no cases exercising this field yields `denominator=0`, surfaced as
    `value=None`, never a misleading `0.0`.
    """
    matched = 0
    total = 0
    for evaluation in evaluations:
        for result in evaluation.field_results:
            if not result.applicable or not predicate(result.path):
                continue
            total += 1
            if result.match:
                matched += 1
    return _metric(name, definition, matched, total, interpretation)


def _retry_stats(retry_counts: List[int]) -> RetryStats:
    if not retry_counts:
        return RetryStats(
            average_retries=None,
            max_retries=0,
            distribution={},
            retry_rate=_metric(
                "retry_rate",
                "Fraction of cases that required at least one retry.",
                0,
                0,
                "No cases available.",
            ),
        )
    distribution = dict(Counter(retry_counts))
    needed_retry = sum(1 for count in retry_counts if count > 0)
    return RetryStats(
        average_retries=sum(retry_counts) / len(retry_counts),
        max_retries=max(retry_counts),
        distribution=distribution,
        retry_rate=_metric(
            "retry_rate",
            "Fraction of cases that required at least one retry beyond the first attempt.",
            needed_retry,
            len(retry_counts),
            "Higher values indicate the first LLM attempt more often needed a second try.",
        ),
    )


def _percentile(sorted_values: List[float], pct: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = round(pct / 100.0 * (len(sorted_values) - 1))
    return sorted_values[min(index, len(sorted_values) - 1)]


def _latency_stats(latencies: List[float]) -> LatencyStats:
    if not latencies:
        return LatencyStats(
            average_ms=None,
            median_ms=None,
            min_ms=None,
            max_ms=None,
            p95_ms=None,
            sample_count=0,
        )
    ordered = sorted(latencies)
    count = len(ordered)
    median = (
        ordered[count // 2]
        if count % 2 == 1
        else (ordered[count // 2 - 1] + ordered[count // 2]) / 2.0
    )
    return LatencyStats(
        average_ms=sum(ordered) / count,
        median_ms=median,
        min_ms=ordered[0],
        max_ms=ordered[-1],
        p95_ms=_percentile(ordered, 95.0),
        sample_count=count,
    )


def _failure_distribution(records: List[RawBenchmarkRecord]) -> Dict[str, int]:
    """
    Counts every `FailureCategory` observed across `records` (spec
    section 3.6.3.M). For a failed record, every attempt's category
    (`failure_records`) is counted; for a successful-but-recovered
    record, only `last_failure_category` is available (that is all
    `RuntimeMetadata` retains -- see `language/failures.py`), so exactly
    that one data point is counted.
    """
    counts: Counter = Counter()
    for record in records:
        if record.failure_records:
            for entry in record.failure_records:
                counts[str(entry["category"])] += 1
        elif record.succeeded and record.last_failure_category:
            counts[record.last_failure_category] += 1
    return dict(counts)


def pooled_metric_value(report: MetricsReport, metric_name: str) -> Optional[float]:
    """
    Pools one named metric's numerator/denominator across every
    category that reports it under `metric_name` -- e.g.
    `goal_accuracy` is only reported by `success_cases` today, so this
    naturally reduces to that category's own value while staying
    correct if a future dataset also reports the same metric name.
    Shared by `provider_comparison.py` and `prompt_comparison.py` so
    both comparison tables read a metric out of a `MetricsReport` the
    same way, rather than each re-implementing the same pooling.
    """
    numerator = 0.0
    denominator = 0.0
    for category_metrics in report.per_category.values():
        metric = category_metrics.accuracy.get(metric_name)
        if metric is None:
            continue
        numerator += metric.numerator
        denominator += metric.denominator
    return numerator / denominator if denominator else None


class MetricsCalculator:
    """Phase 3.6.3's sole public entry point -- see module docstring."""

    def compute(
        self, evaluations: List[CaseEvaluation], records: List[RawBenchmarkRecord]
    ) -> MetricsReport:
        records_by_id = {record.case_id: record for record in records}
        per_category: Dict[str, CategoryMetrics] = {}
        for dataset in DatasetCategory:
            category_evaluations = [e for e in evaluations if e.dataset == dataset]
            category_records = [
                records_by_id[e.case_id]
                for e in category_evaluations
                if e.case_id in records_by_id
            ]
            per_category[dataset.value] = self._category_metrics(
                dataset, category_evaluations, category_records
            )
        overall = self._overall_metrics(evaluations, records, per_category)
        return MetricsReport(per_category=per_category, overall=overall)

    def _category_metrics(
        self,
        dataset: DatasetCategory,
        evaluations: List[CaseEvaluation],
        records: List[RawBenchmarkRecord],
    ) -> CategoryMetrics:
        total = len(evaluations)
        correct = sum(1 for e in evaluations if e.correct)

        accuracy: Dict[str, MetricValue] = {
            "task_accuracy": _metric(
                "task_accuracy",
                "Fraction of cases whose final result matches this dataset's expected behavior.",
                correct,
                total,
                "The primary correctness score for this category.",
            ),
            "goal_accuracy": _field_accuracy(
                evaluations,
                "goal_accuracy",
                "Fraction of applicable `goal` fields (top-level and per-subtask) that match exactly.",
                "Measures whether the parser selects the correct action verb.",
                lambda path: _leaf(path) == "goal",
            ),
            "object_accuracy": _field_accuracy(
                evaluations,
                "object_accuracy",
                "Fraction of applicable `object` fields (top-level and per-subtask) that match exactly.",
                "Measures whether the parser identifies the correct primary object.",
                lambda path: _leaf(path) == "object",
            ),
            "attribute_accuracy": _field_accuracy(
                evaluations,
                "attribute_accuracy",
                "Fraction of applicable `attributes.*` comparisons (color/size/material/state/"
                "quantity/descriptors) that match.",
                "Measures whether descriptive qualifiers are captured correctly.",
                lambda path: _has_segment(path, "attributes"),
            ),
            "location_accuracy": _field_accuracy(
                evaluations,
                "location_accuracy",
                "Fraction of applicable `source_location`/`target_location` fields that match.",
                "Measures whether the parser identifies correct source/destination locations.",
                lambda path: _leaf(path) in ("source_location", "target_location"),
            ),
            "constraint_accuracy": _field_accuracy(
                evaluations,
                "constraint_accuracy",
                "Fraction of applicable `constraints` comparisons (count and per-constraint "
                "fields) that match.",
                "Measures whether stated constraints (spatial/temporal/safety/...) are preserved.",
                lambda path: _has_segment(path, "constraints"),
            ),
            **self._multi_task_accuracy(evaluations),
            **self._clarification_accuracy(evaluations),
            **self._structural_validity(records),
            **self._recovery_rate(evaluations, records),
        }

        retry_stats = _retry_stats(
            [e.recovery.retry_count for e in evaluations if e.recovery is not None]
        )
        latency_stats = _latency_stats([record.total_latency_ms for record in records])
        failure_distribution = _failure_distribution(records)

        return CategoryMetrics(
            dataset=dataset,
            case_count=total,
            accuracy=accuracy,
            retry_stats=retry_stats,
            latency_stats=latency_stats,
            failure_distribution=failure_distribution,
        )

    @staticmethod
    def _multi_task_accuracy(
        evaluations: List[CaseEvaluation],
    ) -> Dict[str, MetricValue]:
        multi_case_ids = {
            e.case_id
            for e in evaluations
            if any(_has_segment(result.path, "subtasks") for result in e.field_results)
        }
        numerator = sum(
            1 for e in evaluations if e.case_id in multi_case_ids and e.correct
        )
        return {
            "multi_task_accuracy": _metric(
                "multi_task_accuracy",
                "Fraction of multi-subtask cases where subtask count, order, and every "
                "subtask's fields all matched.",
                numerator,
                len(multi_case_ids),
                "Measures instruction decomposition quality for multi-step commands.",
            )
        }

    @staticmethod
    def _clarification_accuracy(
        evaluations: List[CaseEvaluation],
    ) -> Dict[str, MetricValue]:
        applicable = [e for e in evaluations if e.clarification_correct is not None]
        correct = sum(1 for e in applicable if e.clarification_correct)
        missed = sum(
            1
            for e in evaluations
            if e.outcome == EvaluationOutcome.MISSED_CLARIFICATION
        )
        unnecessary = sum(
            1
            for e in evaluations
            if e.outcome == EvaluationOutcome.UNEXPECTED_CLARIFICATION
        )
        denom = len(applicable)
        return {
            "clarification_accuracy": _metric(
                "clarification_accuracy",
                "Fraction of applicable cases where `needs_clarification` matched the expected label.",
                correct,
                denom,
                "Overall calibration on when to ask for clarification, both directions.",
            ),
            "missed_clarification_rate": _metric(
                "missed_clarification_rate",
                "Fraction of applicable cases where clarification was expected but not requested.",
                missed,
                denom,
                "Higher values indicate under-triggering (missed genuine ambiguity).",
            ),
            "unnecessary_clarification_rate": _metric(
                "unnecessary_clarification_rate",
                "Fraction of applicable cases where clarification was requested but not expected.",
                unnecessary,
                denom,
                "Higher values indicate over-triggering (flagging resolvable instructions).",
            ),
        }

    @staticmethod
    def _structural_validity(
        records: List[RawBenchmarkRecord],
    ) -> Dict[str, MetricValue]:
        total = len(records)
        valid_first = sum(1 for r in records if r.succeeded and not r.recovered)
        valid_after_recovery = sum(1 for r in records if r.succeeded and r.recovered)
        never_valid = sum(1 for r in records if not r.succeeded)
        return {
            "valid_first_attempt_rate": _metric(
                "valid_first_attempt_rate",
                "Fraction of cases that produced a schema-valid result on the first attempt.",
                valid_first,
                total,
                "Measures raw first-try structural reliability, before any recovery.",
            ),
            "valid_after_recovery_rate": _metric(
                "valid_after_recovery_rate",
                "Fraction of cases that only became schema-valid after at least one retry/repair.",
                valid_after_recovery,
                total,
                "Measures how often Phase 3.5 recovery was necessary to reach a valid result.",
            ),
            "never_valid_rate": _metric(
                "never_valid_rate",
                "Fraction of cases that never produced a valid result, even after recovery.",
                never_valid,
                total,
                "Measures irrecoverable structural failure.",
            ),
        }

    @staticmethod
    def _recovery_rate(
        evaluations: List[CaseEvaluation], records: List[RawBenchmarkRecord]
    ) -> Dict[str, MetricValue]:
        total = len(records)
        attempted = sum(
            1
            for e in evaluations
            if e.recovery is not None and e.recovery.recovery_attempted
        )
        recovered = sum(
            1 for e in evaluations if e.recovery is not None and e.recovery.recovered
        )
        initial_failed = sum(1 for r in records if not r.succeeded or r.recovered)
        final_failed = sum(1 for r in records if not r.succeeded)
        return {
            "recovery_rate": _metric(
                "recovery_rate",
                "Recovered cases divided by cases where a retry was actually attempted "
                "(recoverable failures).",
                recovered,
                attempted,
                "Fraction of recovery attempts that actually salvaged a correct result.",
            ),
            "initial_failure_rate": _metric(
                "initial_failure_rate",
                "Fraction of cases whose very first attempt failed, regardless of whether a "
                "later attempt eventually succeeded.",
                initial_failed,
                total,
                "Measures how often the first LLM call alone was insufficient.",
            ),
            "final_failure_rate": _metric(
                "final_failure_rate",
                "Fraction of cases that never produced a result at all, after all attempts.",
                final_failed,
                total,
                "Measures irrecoverable pipeline failure, independent of correctness.",
            ),
        }

    def _overall_metrics(
        self,
        evaluations: List[CaseEvaluation],
        records: List[RawBenchmarkRecord],
        per_category: Dict[str, CategoryMetrics],
    ) -> OverallMetrics:
        total = len(evaluations)
        correct = sum(1 for e in evaluations if e.correct)
        micro = _metric(
            "task_accuracy_micro",
            "Task accuracy pooling every case from every category into one ratio.",
            correct,
            total,
            "Weights each individual case equally; larger categories dominate this number.",
        )

        category_values: List[float] = [
            metrics.accuracy["task_accuracy"].value
            for metrics in per_category.values()
            if metrics.accuracy["task_accuracy"].value is not None
        ]
        macro_value: Optional[float] = (
            sum(category_values) / len(category_values) if category_values else None
        )
        macro = MetricValue(
            name="task_accuracy_macro",
            definition="Unweighted average of each category's own task accuracy.",
            numerator=macro_value if macro_value is not None else 0.0,
            denominator=1.0 if macro_value is not None else 0.0,
            interpretation="Weights each category equally, so success_cases (15 cases) cannot "
            "dominate ambiguity_cases (10 cases) or vice versa.",
        )

        retry_stats = _retry_stats(
            [e.recovery.retry_count for e in evaluations if e.recovery is not None]
        )
        latency_stats = _latency_stats([record.total_latency_ms for record in records])
        failure_distribution = _failure_distribution(records)

        return OverallMetrics(
            case_count=total,
            task_accuracy_micro=micro,
            task_accuracy_macro=macro,
            retry_stats=retry_stats,
            latency_stats=latency_stats,
            failure_distribution=failure_distribution,
        )
