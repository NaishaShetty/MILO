"""
test_evaluation_metrics.py

Purpose
-------
Verifies `evaluation.metrics.MetricsCalculator` against hand-built
`CaseEvaluation`/`RawBenchmarkRecord` lists -- no `LanguageAgent`, no
LLM. Covers: accuracy calculation, per-category breakdown, micro/macro
averaging, latency aggregation, retry statistics, and failure
distribution.
"""

from __future__ import annotations

from evaluation.metrics import MetricsCalculator, pooled_metric_value
from evaluation.models import (
    CaseEvaluation,
    DatasetCategory,
    EvaluationOutcome,
    RawBenchmarkRecord,
    RecoveryInfo,
    RunMode,
)


def _evaluation(
    case_id, dataset, correct, outcome, recovery=None, field_results=None
) -> CaseEvaluation:
    return CaseEvaluation(
        case_id=case_id,
        dataset=dataset,
        category="test",
        outcome=outcome,
        correct=correct,
        field_results=field_results or [],
        recovery=recovery
        or RecoveryInfo(recovery_attempted=False, recovered=False, retry_count=0),
    )


def _record(
    case_id, dataset, succeeded, total_latency_ms=100.0, **kwargs
) -> RawBenchmarkRecord:
    return RawBenchmarkRecord(
        case_id=case_id,
        dataset=dataset,
        category="test",
        succeeded=succeeded,
        total_latency_ms=total_latency_ms,
        run_mode=RunMode.MOCKED,
        **kwargs,
    )


class TestAccuracyCalculation:
    def test_task_accuracy_ratio(self) -> None:
        evaluations = [
            _evaluation("s1", DatasetCategory.SUCCESS, True, EvaluationOutcome.SUCCESS),
            _evaluation(
                "s2", DatasetCategory.SUCCESS, False, EvaluationOutcome.INCORRECT_OUTPUT
            ),
        ]
        records = [
            _record(
                "s1", DatasetCategory.SUCCESS, True, attempt_number=1, recovered=False
            ),
            _record(
                "s2", DatasetCategory.SUCCESS, True, attempt_number=1, recovered=False
            ),
        ]
        report = MetricsCalculator().compute(evaluations, records)
        success_metrics = report.per_category[DatasetCategory.SUCCESS.value]
        assert success_metrics.accuracy["task_accuracy"].numerator == 1
        assert success_metrics.accuracy["task_accuracy"].denominator == 2
        assert success_metrics.accuracy["task_accuracy"].value == 0.5

    def test_empty_category_yields_none_value_not_zero(self) -> None:
        report = MetricsCalculator().compute([], [])
        for category_metrics in report.per_category.values():
            assert category_metrics.accuracy["task_accuracy"].value is None
        assert report.overall.task_accuracy_micro.value is None


class TestCategoryBreakdownAndMicroMacro:
    def test_categories_reported_independently_and_micro_macro_differ(self) -> None:
        evaluations = [
            *[
                _evaluation(
                    f"s{i}", DatasetCategory.SUCCESS, True, EvaluationOutcome.SUCCESS
                )
                for i in range(10)
            ],
            _evaluation(
                "a1",
                DatasetCategory.AMBIGUITY,
                False,
                EvaluationOutcome.MISSED_CLARIFICATION,
            ),
        ]
        records = [
            *[
                _record(
                    f"s{i}",
                    DatasetCategory.SUCCESS,
                    True,
                    attempt_number=1,
                    recovered=False,
                )
                for i in range(10)
            ],
            _record(
                "a1", DatasetCategory.AMBIGUITY, True, attempt_number=1, recovered=False
            ),
        ]
        report = MetricsCalculator().compute(evaluations, records)
        assert (
            report.per_category[DatasetCategory.SUCCESS.value]
            .accuracy["task_accuracy"]
            .value
            == 1.0
        )
        assert (
            report.per_category[DatasetCategory.AMBIGUITY.value]
            .accuracy["task_accuracy"]
            .value
            == 0.0
        )
        # Micro pools 10 correct / 11 total; macro averages 1.0 and 0.0
        # (and the empty failure_cases category, whose value is None
        # and therefore excluded from the macro average) -- the two
        # must disagree here, proving neither collapses into the other.
        assert report.overall.task_accuracy_micro.value == 10 / 11
        assert report.overall.task_accuracy_macro.value == 0.5


class TestLatencyAndRetryAggregation:
    def test_latency_stats_over_records(self) -> None:
        records = [
            _record(
                "s1",
                DatasetCategory.SUCCESS,
                True,
                total_latency_ms=100.0,
                attempt_number=1,
                recovered=False,
            ),
            _record(
                "s2",
                DatasetCategory.SUCCESS,
                True,
                total_latency_ms=200.0,
                attempt_number=1,
                recovered=False,
            ),
            _record(
                "s3",
                DatasetCategory.SUCCESS,
                True,
                total_latency_ms=300.0,
                attempt_number=1,
                recovered=False,
            ),
        ]
        evaluations = [
            _evaluation(
                r.case_id, DatasetCategory.SUCCESS, True, EvaluationOutcome.SUCCESS
            )
            for r in records
        ]
        report = MetricsCalculator().compute(evaluations, records)
        stats = report.per_category[DatasetCategory.SUCCESS.value].latency_stats
        assert stats.average_ms == 200.0
        assert stats.median_ms == 200.0
        assert stats.min_ms == 100.0
        assert stats.max_ms == 300.0
        assert stats.sample_count == 3

    def test_retry_statistics(self) -> None:
        evaluations = [
            _evaluation(
                "s1",
                DatasetCategory.SUCCESS,
                True,
                EvaluationOutcome.SUCCESS,
                recovery=RecoveryInfo(
                    recovery_attempted=False, recovered=False, retry_count=0
                ),
            ),
            _evaluation(
                "s2",
                DatasetCategory.SUCCESS,
                True,
                EvaluationOutcome.RECOVERED_FAILURE,
                recovery=RecoveryInfo(
                    recovery_attempted=True, recovered=True, retry_count=2
                ),
            ),
        ]
        records = [
            _record(
                "s1", DatasetCategory.SUCCESS, True, attempt_number=1, recovered=False
            ),
            _record(
                "s2", DatasetCategory.SUCCESS, True, attempt_number=3, recovered=True
            ),
        ]
        report = MetricsCalculator().compute(evaluations, records)
        retry_stats = report.per_category[DatasetCategory.SUCCESS.value].retry_stats
        assert retry_stats.average_retries == 1.0
        assert retry_stats.max_retries == 2
        assert retry_stats.distribution == {0: 1, 2: 1}
        assert retry_stats.retry_rate.value == 0.5


class TestFailureDistribution:
    def test_failure_categories_are_counted_from_failure_records(self) -> None:
        records = [
            _record(
                "f1",
                DatasetCategory.FAILURE,
                False,
                error_type="RetryExhaustedError",
                failure_records=[
                    {"category": "invalid_json"},
                    {"category": "invalid_json"},
                ],
            ),
            _record(
                "f2",
                DatasetCategory.FAILURE,
                False,
                error_type="ResponseParsingError",
                failure_records=[{"category": "unsupported_response"}],
            ),
        ]
        evaluations = [
            _evaluation(
                "f1", DatasetCategory.FAILURE, True, EvaluationOutcome.EXPECTED_FAILURE
            ),
            _evaluation(
                "f2", DatasetCategory.FAILURE, True, EvaluationOutcome.EXPECTED_FAILURE
            ),
        ]
        report = MetricsCalculator().compute(evaluations, records)
        distribution = report.per_category[
            DatasetCategory.FAILURE.value
        ].failure_distribution
        assert distribution == {"invalid_json": 2, "unsupported_response": 1}


class TestPooledMetricValue:
    def test_pools_numerator_and_denominator_across_categories(self) -> None:
        evaluations = [
            _evaluation(
                "s1",
                DatasetCategory.SUCCESS,
                True,
                EvaluationOutcome.SUCCESS,
                field_results=[],
            ),
        ]
        records = [
            _record(
                "s1", DatasetCategory.SUCCESS, True, attempt_number=1, recovered=False
            )
        ]
        report = MetricsCalculator().compute(evaluations, records)
        # goal_accuracy has 0/0 (no field_results supplied) everywhere -> None.
        assert pooled_metric_value(report, "goal_accuracy") is None
        assert pooled_metric_value(report, "not_a_real_metric") is None
