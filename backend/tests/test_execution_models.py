"""
test_execution_models.py

Purpose
-------
Unit tests for `execution.models`: `Action`/`ActionResult` validity,
serialization round-tripping, and that malformed construction fails
loudly (`extra="forbid"`) -- section 18's "Action model" test list.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from execution.errors import ExecutionError, ExecutionErrorCode
from execution.models import (
    Action,
    ActionResult,
    ActionType,
    ExecutionRecord,
    ExecutionStatus,
)


def test_action_type_covers_every_dispatchable_action():
    values = {t.value for t in ActionType}
    assert values == {
        "move_ahead",
        "move_back",
        "rotate_left",
        "rotate_right",
        "look_up",
        "look_down",
        "navigate",
        "pickup",
        "put",
        "open",
        "close",
        "locate",
    }


def test_valid_action_constructs_and_serializes_round_trip():
    action = Action(
        action_type=ActionType.PICKUP,
        parameters={"object_id": "Apple|1"},
        step_id=3,
    )
    payload = action.model_dump()
    rebuilt = Action.model_validate(payload)
    assert rebuilt == action
    assert rebuilt.action_type == ActionType.PICKUP


def test_action_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Action(action_type=ActionType.OPEN, parameters={}, not_a_field=True)


def test_action_rejects_invalid_action_type():
    with pytest.raises(ValidationError):
        Action(action_type="teleport_to_mars", parameters={})


def test_action_result_success_shape():
    result = ActionResult(
        success=True,
        action="pickup",
        action_id="a1",
        step_id=1,
        object_id="Apple|1",
        metadata={"lastActionSuccess": True},
    )
    assert result.error is None
    assert result.error_code is None
    assert result.model_dump()["success"] is True


def test_action_result_failure_shape():
    result = ActionResult(
        success=False,
        action="open",
        action_id="a2",
        step_id=2,
        object_id="Fridge|1",
        error="Object not reachable",
        error_code=ExecutionErrorCode.OBJECT_NOT_REACHABLE,
        metadata={},
    )
    assert result.success is False
    assert result.error_code == ExecutionErrorCode.OBJECT_NOT_REACHABLE


def test_execution_error_defaults_not_recoverable():
    error = ExecutionError(
        code=ExecutionErrorCode.INVALID_ACTION, message="unknown action"
    )
    assert error.recoverable is False
    assert error.details == {}


def test_execution_record_duration_none_until_finished():
    record = ExecutionRecord(plan_id="p1", task_id="t1")
    assert record.duration_ms is None
    assert record.status == ExecutionStatus.PENDING
    assert record.success_count == 0
    assert record.failure_count == 0


def test_execution_record_deserializes_from_dict():
    payload = {
        "execution_id": "e1",
        "plan_id": "p1",
        "task_id": "t1",
        "status": "success",
        "step_results": [],
        "events": [],
        "error": None,
        "started_at": 1.0,
        "finished_at": 2.0,
    }
    record = ExecutionRecord.model_validate(payload)
    assert record.duration_ms == pytest.approx(1000.0)
