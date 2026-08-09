"""
test_language_schema_validator.py

Purpose
-------
Verifies `SchemaValidator.validate()` delegates correctly to Phase
3.2's `ParsedInstruction` schema -- accepting a valid `SingleTask` or
`MultiTask` dict and returning the corresponding model instance,
rejecting an invalid one as `TaskValidationError` while preserving the
original `pydantic.ValidationError`.

This suite deliberately does NOT re-test Phase 3.2's validation rules
in depth (goal snake_case formatting, attribute normalization, ...) --
that is `backend/tests/test_task.py`'s job, and duplicating it here
would be exactly the kind of duplicated validation logic this
repository's engineering requirements ask to avoid. These tests only
confirm `SchemaValidator` is a faithful, correctly-wired adapter over
that existing schema.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from language.exceptions import TaskValidationError
from language.schema_validator import SchemaValidator
from schemas.task import MultiTask, SingleTask


def _valid_single_task() -> dict:
    return {
        "task_type": "single",
        "task_id": None,
        "goal": "fetch",
        "object": "red mug",
        "target": None,
        "source_location": None,
        "target_location": None,
        "attributes": {"color": "red"},
        "constraints": None,
        "priority": None,
        "preconditions": None,
        "postconditions": None,
        "estimated_goal": "the red mug is delivered",
        "needs_clarification": False,
        "clarification_reason": None,
    }


def _valid_multi_task() -> dict:
    return {
        "task_type": "multi",
        "task_id": None,
        "goal": None,
        "attributes": None,
        "constraints": None,
        "priority": None,
        "preconditions": None,
        "postconditions": None,
        "estimated_goal": None,
        "needs_clarification": False,
        "clarification_reason": None,
        "subtasks": [
            {
                "task_type": "single",
                "task_id": None,
                "goal": "pick_up",
                "object": "cup",
                "needs_clarification": False,
            },
            {
                "task_type": "single",
                "task_id": None,
                "goal": "navigate_to",
                "target_location": "office",
                "needs_clarification": False,
            },
        ],
    }


class TestValidSingleTask:
    def test_returns_single_task_instance(self) -> None:
        result = SchemaValidator().validate(_valid_single_task())
        assert isinstance(result, SingleTask)
        assert result.goal == "fetch"
        assert result.object == "red mug"


class TestValidMultiTask:
    def test_returns_multi_task_instance(self) -> None:
        result = SchemaValidator().validate(_valid_multi_task())
        assert isinstance(result, MultiTask)
        assert len(result.subtasks) == 2


class TestInvalidTask:
    def test_needs_clarification_without_reason_raises_task_validation_error(
        self,
    ) -> None:
        data = _valid_single_task()
        data["needs_clarification"] = True
        data["clarification_reason"] = None

        with pytest.raises(TaskValidationError) as excinfo:
            SchemaValidator().validate(data)

        # The original pydantic.ValidationError must be preserved, not
        # just stringified -- see TaskValidationError's docstring for
        # why (structured per-field errors for future callers).
        assert isinstance(excinfo.value.original_error, ValidationError)

    def test_multi_task_with_one_subtask_raises_task_validation_error(self) -> None:
        data = _valid_multi_task()
        data["subtasks"] = data["subtasks"][:1]

        with pytest.raises(TaskValidationError):
            SchemaValidator().validate(data)


class TestInvalidEnum:
    def test_unrecognized_task_type_raises_task_validation_error(self) -> None:
        data = _valid_single_task()
        data["task_type"] = "not_a_real_type"

        with pytest.raises(TaskValidationError):
            SchemaValidator().validate(data)

    def test_unrecognized_priority_raises_task_validation_error(self) -> None:
        data = _valid_single_task()
        data["priority"] = "extremely_urgent"  # not a TaskPriority value

        with pytest.raises(TaskValidationError):
            SchemaValidator().validate(data)


class TestMissingRequiredInformation:
    def test_missing_task_type_raises_task_validation_error(self) -> None:
        data = _valid_single_task()
        del data["task_type"]

        with pytest.raises(TaskValidationError):
            SchemaValidator().validate(data)

    def test_multi_task_missing_subtasks_raises_task_validation_error(self) -> None:
        data = _valid_multi_task()
        del data["subtasks"]

        with pytest.raises(TaskValidationError):
            SchemaValidator().validate(data)


class TestClarificationConsistency:
    def test_needs_clarification_true_with_reason_is_valid(self) -> None:
        data = _valid_single_task()
        data["needs_clarification"] = True
        data["clarification_reason"] = "ambiguous referent"

        result = SchemaValidator().validate(data)
        assert result.needs_clarification is True
        assert result.clarification_reason == "ambiguous referent"

    def test_needs_clarification_false_with_reason_raises_task_validation_error(
        self,
    ) -> None:
        data = _valid_single_task()
        data["needs_clarification"] = False
        data["clarification_reason"] = "unexpected reason"

        with pytest.raises(TaskValidationError):
            SchemaValidator().validate(data)


class TestAdapterIsCachedNotRebuilt:
    def test_repeated_validate_calls_reuse_the_same_adapter(self) -> None:
        validator = SchemaValidator()
        adapter_id_before = id(validator._adapter)
        validator.validate(_valid_single_task())
        validator.validate(_valid_single_task())
        assert id(validator._adapter) == adapter_id_before
