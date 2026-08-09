"""
recovery_evaluation.py

Purpose
-------
Phase 3.6.6 -- Recovery Evaluation. Analyzes the Phase 3.5 recovery
system (retry, repair, semantic re-check) independently of the general
accuracy metrics in `metrics.py` -- initial vs. final success rate,
recovery attempt/success rate, average retries for recovered cases,
recovery's latency cost, and a breakdown of recovered vs. unrecovered
outcomes by `FailureCategory`, per the spec's "Recovery Analysis" tree.

Why this is cross-cutting, not `failure_cases`-only
---------------------------------------------------------
Recovery (a retry after a transient/sampling failure) can happen for
any case in any dataset -- a real, flaky provider might need a retry on
a `success_cases` instruction just as easily as on a
`failure_cases`/`ambiguity_cases` one. This evaluator therefore reads
`CaseEvaluation.recovery` across every dataset, never filtering by
`dataset` -- the same design choice `evaluator.py`'s `_recovery_info`
already makes.

Recovery success definition, exactly as the spec states it
------------------------------------------------------------------
A case counts as recovered only when (1) the initial attempt failed,
(2) a retry was actually made, and (3) the *final* result satisfies
that case's own expected behavior -- never merely "a second attempt
happened". `evaluator.py`'s `_recovery_info` already encodes this
(`recovered = recovery_attempted and correct`); this module only reads
that field, it never re-derives correctness itself.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence

from evaluation.models import (
    CaseEvaluation,
    MetricValue,
    RawBenchmarkRecord,
    RecoveryCategoryBreakdown,
    RecoveryReport,
)


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


class RecoveryEvaluator:
    """Phase 3.6.6's sole public entry point -- see module docstring."""

    def evaluate(
        self,
        evaluations: Sequence[CaseEvaluation],
        records: Sequence[RawBenchmarkRecord],
    ) -> RecoveryReport:
        records_by_id = {record.case_id: record for record in records}
        total = len(evaluations)

        initial_success = 0
        final_success = 0
        for evaluation in evaluations:
            record = records_by_id.get(evaluation.case_id)
            if record is None:
                continue
            if record.succeeded:
                final_success += 1
                if not record.recovered:
                    initial_success += 1

        recovery_attempted = sum(
            1
            for e in evaluations
            if e.recovery is not None and e.recovery.recovery_attempted
        )
        recovered = sum(
            1 for e in evaluations if e.recovery is not None and e.recovery.recovered
        )
        unrecovered_final_failures = sum(
            1
            for e in evaluations
            if records_by_id.get(e.case_id) and not records_by_id[e.case_id].succeeded
        )

        retry_counts_for_recovered = [
            e.recovery.retry_count
            for e in evaluations
            if e.recovery is not None and e.recovery.recovered
        ]
        average_retries: Optional[float] = (
            sum(retry_counts_for_recovered) / len(retry_counts_for_recovered)
            if retry_counts_for_recovered
            else None
        )

        latency_overhead = self._recovery_latency_overhead(evaluations, records_by_id)
        breakdown = self._breakdown_by_category(evaluations)

        return RecoveryReport(
            total_cases=total,
            initial_success_rate=_metric(
                "initial_success_rate",
                "Fraction of cases whose very first attempt already succeeded, needing no recovery.",
                initial_success,
                total,
                "Baseline reliability of a single LLM call, before Phase 3.5 recovery.",
            ),
            initial_failure_rate=_metric(
                "initial_failure_rate",
                "Fraction of cases whose very first attempt failed (whether or not it later recovered).",
                total - initial_success,
                total,
                "Complement of initial_success_rate.",
            ),
            recovery_attempt_rate=_metric(
                "recovery_attempt_rate",
                "Fraction of cases where the recovery loop actually made a second (or later) attempt.",
                recovery_attempted,
                total,
                "How often Phase 3.5's retry policy was invoked at all.",
            ),
            recovery_success_rate=_metric(
                "recovery_success_rate",
                "Fraction of recovery attempts that produced a final result matching the case's "
                "expected behavior.",
                recovered,
                recovery_attempted,
                "How effective recovery is, conditioned on it being attempted at all.",
            ),
            final_success_rate=_metric(
                "final_success_rate",
                "Fraction of cases that produced any result at all after every permitted attempt.",
                final_success,
                total,
                "Overall pipeline reliability including recovery -- not the same as correctness "
                "(see metrics.py's task_accuracy, which also requires the result to be correct).",
            ),
            unrecovered_failure_rate=_metric(
                "unrecovered_failure_rate",
                "Fraction of cases that never produced a result, even after every permitted attempt.",
                unrecovered_final_failures,
                total,
                "Cases recovery could not save.",
            ),
            average_retries_for_recovered=average_retries,
            recovery_latency_overhead_ms=latency_overhead,
            breakdown_by_category=breakdown,
        )

    @staticmethod
    def _recovery_latency_overhead(
        evaluations: Sequence[CaseEvaluation],
        records_by_id: Dict[str, RawBenchmarkRecord],
    ) -> Optional[float]:
        """
        Approximates recovery's wall-clock cost as the difference
        between the mean `total_latency_ms` of recovered cases and the
        mean `total_latency_ms` of clean-first-attempt cases. This is
        an approximation, documented as such (see `models.RecoveryReport`):
        only whole-call timing is available, not a per-attempt
        breakdown, since `RuntimeMetadata.latency_ms` only covers the
        final successful LLM call (see `language/failures.py`).
        """
        recovered_latencies: List[float] = []
        baseline_latencies: List[float] = []
        for evaluation in evaluations:
            record = records_by_id.get(evaluation.case_id)
            if record is None or evaluation.recovery is None:
                continue
            if evaluation.recovery.recovered:
                recovered_latencies.append(record.total_latency_ms)
            elif record.succeeded and not evaluation.recovery.recovery_attempted:
                baseline_latencies.append(record.total_latency_ms)
        if not recovered_latencies or not baseline_latencies:
            return None
        return (sum(recovered_latencies) / len(recovered_latencies)) - (
            sum(baseline_latencies) / len(baseline_latencies)
        )

    @staticmethod
    def _breakdown_by_category(
        evaluations: Sequence[CaseEvaluation],
    ) -> List[RecoveryCategoryBreakdown]:
        """
        Buckets every case where recovery was attempted by the *last*
        `FailureCategory` it encountered (the category that ultimately
        triggered the retry that led to the final outcome), per the
        spec's "Recovery Analysis" tree (one bucket per
        `FailureCategory`, each split into recovered/unrecovered).
        """
        counts: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"recovered": 0, "unrecovered": 0}
        )
        for evaluation in evaluations:
            recovery = evaluation.recovery
            if recovery is None or not recovery.recovery_attempted:
                continue
            category = (
                recovery.failure_categories[-1]
                if recovery.failure_categories
                else "unknown"
            )
            key = "recovered" if recovery.recovered else "unrecovered"
            counts[category][key] += 1
        return [
            RecoveryCategoryBreakdown(
                category=category,
                recovered=values["recovered"],
                unrecovered=values["unrecovered"],
            )
            for category, values in sorted(counts.items())
        ]
