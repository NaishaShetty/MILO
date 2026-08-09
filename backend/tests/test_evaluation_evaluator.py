"""
test_evaluation_evaluator.py

Purpose
-------
Verifies `evaluation.evaluator.ResultEvaluator` and `compare_task`
against hand-built `BenchmarkCase`/`RawBenchmarkRecord` pairs -- no
`LanguageAgent`, no LLM, purely the comparison/classification logic.
Covers: exact match, partial mismatch, multi-task comparison
(count/order/fields), null handling, expected/unexpected clarification,
missed clarification, and every `failure_cases` verdict combination.
"""

from __future__ import annotations

from typing import Any, Dict

from evaluation.evaluator import ResultEvaluator, compare_task
from evaluation.models import (
    BenchmarkCase,
    DatasetCategory,
    EvaluationOutcome,
    RawBenchmarkRecord,
    RunMode,
)

_EXPECTED_SINGLE: Dict[str, Any] = {
    "task_type": "single",
    "task_id": None,
    "goal": "fetch",
    "object": "red mug",
    "target": None,
    "source_location": "counter",
    "target_location": None,
    "attributes": {
        "color": "red",
        "size": None,
        "material": None,
        "state": None,
        "quantity": None,
        "descriptors": None,
    },
    "constraints": None,
    "priority": None,
    "preconditions": None,
    "postconditions": None,
    "estimated_goal": "the red mug is delivered",
    "needs_clarification": False,
    "clarification_reason": None,
}


def _success_case(expected=None) -> BenchmarkCase:
    return BenchmarkCase(
        case_id="success-001",
        dataset=DatasetCategory.SUCCESS,
        category="attributes",
        instruction="bring the red mug from the counter",
        expected_output=expected or _EXPECTED_SINGLE,
    )


def _record(succeeded: bool, parsed=None, **kwargs) -> RawBenchmarkRecord:
    return RawBenchmarkRecord(
        case_id="success-001",
        dataset=DatasetCategory.SUCCESS,
        category="attributes",
        succeeded=succeeded,
        parsed_instruction=parsed,
        run_mode=RunMode.MOCKED,
        **kwargs,
    )


class TestFieldComparison:
    def test_exact_match_has_no_mismatches(self) -> None:
        results = compare_task(_EXPECTED_SINGLE, _EXPECTED_SINGLE)
        assert all(result.match for result in results if result.applicable)

    def test_wrong_attribute_is_flagged_at_its_own_path(self) -> None:
        actual = {
            **_EXPECTED_SINGLE,
            "attributes": {**_EXPECTED_SINGLE["attributes"], "color": "blue"},
        }
        results = compare_task(_EXPECTED_SINGLE, actual)
        color_result = next(r for r in results if r.path == "attributes.color")
        assert color_result.match is False
        assert color_result.expected == "red"
        assert color_result.actual == "blue"
        # goal/object still match -- not everything is reduced to one boolean.
        assert next(r for r in results if r.path == "goal").match is True
        assert next(r for r in results if r.path == "object").match is True

    def test_task_id_is_excluded_from_comparison(self) -> None:
        actual = {**_EXPECTED_SINGLE, "task_id": "some-generated-uuid"}
        results = compare_task(_EXPECTED_SINGLE, actual)
        assert not any(r.path == "task_id" for r in results)

    def test_null_attributes_on_both_sides_is_a_match_not_a_skip(self) -> None:
        expected = {**_EXPECTED_SINGLE, "attributes": None}
        actual = {**_EXPECTED_SINGLE, "attributes": None}
        results = compare_task(expected, actual)
        attributes_result = next(r for r in results if r.path == "attributes")
        assert attributes_result.applicable is True
        assert attributes_result.match is True

    def test_multi_task_subtask_count_order_and_fields(self) -> None:
        expected: Dict[str, Any] = {
            "task_type": "multi",
            "task_id": None,
            "goal": None,
            "priority": None,
            "needs_clarification": False,
            "clarification_reason": None,
            "subtasks": [
                {**_EXPECTED_SINGLE, "goal": "open", "object": "curtains"},
                {**_EXPECTED_SINGLE, "goal": "close", "object": "curtains"},
            ],
        }
        actual_correct_order = {
            **expected,
            "subtasks": [
                {**_EXPECTED_SINGLE, "goal": "open", "object": "curtains"},
                {**_EXPECTED_SINGLE, "goal": "close", "object": "curtains"},
            ],
        }
        results = compare_task(expected, actual_correct_order)
        assert all(r.match for r in results if r.applicable)

        actual_wrong_order = {
            **expected,
            "subtasks": [
                {**_EXPECTED_SINGLE, "goal": "close", "object": "curtains"},
                {**_EXPECTED_SINGLE, "goal": "open", "object": "curtains"},
            ],
        }
        results = compare_task(expected, actual_wrong_order)
        assert next(r for r in results if r.path == "subtasks[0].goal").match is False

        actual_wrong_count = {**expected, "subtasks": [expected["subtasks"][0]]}
        results = compare_task(expected, actual_wrong_count)
        assert next(r for r in results if r.path == "subtasks.count").match is False


class TestSuccessCaseOutcomes:
    def test_exact_match_is_success(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            _success_case(),
            _record(True, _EXPECTED_SINGLE, attempt_number=1, recovered=False),
        )
        assert evaluation.outcome == EvaluationOutcome.SUCCESS
        assert evaluation.correct is True

    def test_wrong_field_is_incorrect_output_not_a_pipeline_failure(self) -> None:
        actual = {**_EXPECTED_SINGLE, "goal": "store"}
        evaluation = ResultEvaluator().evaluate(
            _success_case(), _record(True, actual, attempt_number=1, recovered=False)
        )
        assert evaluation.outcome == EvaluationOutcome.INCORRECT_OUTPUT
        assert evaluation.correct is False

    def test_exception_on_a_success_case_is_unexpected_failure(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            _success_case(),
            _record(
                False,
                error_type="RetryExhaustedError",
                failure_records=[{"category": "invalid_json"}],
            ),
        )
        assert evaluation.outcome == EvaluationOutcome.UNEXPECTED_FAILURE
        assert evaluation.correct is False

    def test_recovered_success_is_labeled_recovered_failure(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            _success_case(),
            _record(
                True,
                _EXPECTED_SINGLE,
                attempt_number=2,
                recovered=True,
                last_failure_category="invalid_json",
            ),
        )
        assert evaluation.outcome == EvaluationOutcome.RECOVERED_FAILURE
        assert evaluation.correct is True
        assert evaluation.recovery is not None
        assert evaluation.recovery.recovered is True
        assert evaluation.recovery.retry_count == 1


class TestFailureCaseOutcomes:
    def _case(self, expected_validation_result: str) -> BenchmarkCase:
        return BenchmarkCase(
            case_id="failure-001",
            dataset=DatasetCategory.FAILURE,
            category="invalid_json_syntax",
            instruction="turn on the porch light",
            candidate_output="not json",
            expected_validation_result=expected_validation_result,
        )

    def _failure_record(self, succeeded: bool, **kwargs) -> RawBenchmarkRecord:
        return RawBenchmarkRecord(
            case_id="failure-001",
            dataset=DatasetCategory.FAILURE,
            category="invalid_json_syntax",
            succeeded=succeeded,
            **kwargs,
        )

    def test_reject_case_that_correctly_fails_is_expected_failure(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            self._case("reject_syntactic"),
            self._failure_record(
                False,
                error_type="RetryExhaustedError",
                failure_records=[{"category": "invalid_json"}] * 2,
            ),
        )
        assert evaluation.outcome == EvaluationOutcome.EXPECTED_FAILURE
        assert evaluation.correct is True

    def test_reject_case_that_wrongly_succeeds_is_invalid_acceptance(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            self._case("reject_syntactic"),
            self._failure_record(
                True,
                parsed_instruction=_EXPECTED_SINGLE,
                attempt_number=1,
                recovered=False,
            ),
        )
        assert evaluation.outcome == EvaluationOutcome.INVALID_ACCEPTANCE
        assert evaluation.correct is False

    def test_accept_case_that_succeeds_is_success(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            self._case("accept"),
            self._failure_record(
                True,
                parsed_instruction=_EXPECTED_SINGLE,
                attempt_number=1,
                recovered=False,
            ),
        )
        assert evaluation.outcome == EvaluationOutcome.SUCCESS
        assert evaluation.correct is True

    def test_accept_case_that_wrongly_fails_is_unrecovered_failure_when_retried(
        self,
    ) -> None:
        # Two failure records means `RetryExhaustedError` actually
        # retried once -- so the `UNEXPECTED_FAILURE` verdict is
        # promoted to `UNRECOVERED_FAILURE` (see `evaluator.py`'s
        # `_apply_recovery_overrides`).
        evaluation = ResultEvaluator().evaluate(
            self._case("accept"),
            self._failure_record(
                False,
                error_type="RetryExhaustedError",
                failure_records=[{"category": "invalid_json"}] * 2,
            ),
        )
        assert evaluation.outcome == EvaluationOutcome.UNRECOVERED_FAILURE
        assert evaluation.correct is False

    def test_accept_case_that_wrongly_fails_without_retry_is_unexpected_failure(
        self,
    ) -> None:
        evaluation = ResultEvaluator().evaluate(
            self._case("accept"),
            self._failure_record(
                False,
                error_type="ResponseParsingError",
                failure_records=[{"category": "invalid_json"}],
            ),
        )
        assert evaluation.outcome == EvaluationOutcome.UNEXPECTED_FAILURE
        assert evaluation.correct is False


class TestAmbiguityCaseOutcomes:
    def _case(self, expected: bool) -> BenchmarkCase:
        return BenchmarkCase(
            case_id="ambig-001",
            dataset=DatasetCategory.AMBIGUITY,
            category="unresolved_pronoun_no_referent",
            instruction="hand me that",
            expected_needs_clarification=expected,
        )

    def _ambiguity_record(self, needs_clarification: bool) -> RawBenchmarkRecord:
        return RawBenchmarkRecord(
            case_id="ambig-001",
            dataset=DatasetCategory.AMBIGUITY,
            category="unresolved_pronoun_no_referent",
            succeeded=True,
            parsed_instruction={
                **_EXPECTED_SINGLE,
                "needs_clarification": needs_clarification,
            },
            attempt_number=1,
            recovered=False,
        )

    def test_correctly_flagged_ambiguity_is_expected_clarification(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            self._case(True), self._ambiguity_record(True)
        )
        assert evaluation.outcome == EvaluationOutcome.EXPECTED_CLARIFICATION
        assert evaluation.correct is True
        assert evaluation.clarification_correct is True

    def test_correctly_not_flagged_is_success(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            self._case(False), self._ambiguity_record(False)
        )
        assert evaluation.outcome == EvaluationOutcome.SUCCESS
        assert evaluation.correct is True

    def test_over_triggering_is_unexpected_clarification(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            self._case(False), self._ambiguity_record(True)
        )
        assert evaluation.outcome == EvaluationOutcome.UNEXPECTED_CLARIFICATION
        assert evaluation.correct is False

    def test_missed_ambiguity_is_missed_clarification(self) -> None:
        evaluation = ResultEvaluator().evaluate(
            self._case(True), self._ambiguity_record(False)
        )
        assert evaluation.outcome == EvaluationOutcome.MISSED_CLARIFICATION
        assert evaluation.correct is False
