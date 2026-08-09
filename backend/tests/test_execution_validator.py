"""
test_execution_validator.py

Purpose
-------
Unit tests for `execution.validator.ResultValidator` -- section 18's
"Result validation" test list: a successful action, a
simulator-reported failure, an unexpected/malformed simulator response,
and the specific ground-truth postcondition checks (pickup ->
inventory, open/close -> isOpen) that make this validator not just
trust `lastActionSuccess` blindly.
"""

from __future__ import annotations

from execution.errors import ExecutionErrorCode
from execution.models import Action, ActionType
from execution.validator import ResultValidator
from tests._execution_test_helpers import FakeEvent


def test_locate_always_succeeds_with_no_simulator_call():
    validator = ResultValidator()
    action = Action(action_type=ActionType.LOCATE, parameters={}, step_id=1)
    result = validator.validate(action, None, duration_ms=0.0)
    assert result.success is True
    assert result.metadata == {}


def test_missing_response_is_simulator_error():
    validator = ResultValidator()
    action = Action(action_type=ActionType.MOVE_AHEAD, parameters={}, step_id=1)
    result = validator.validate(action, None, duration_ms=1.0)
    assert result.success is False
    assert result.error_code == ExecutionErrorCode.SIMULATOR_ERROR


def test_simulator_reported_failure_is_reported():
    validator = ResultValidator()
    action = Action(
        action_type=ActionType.PICKUP, parameters={"object_id": "Apple|1"}, step_id=1
    )
    raw = FakeEvent({"lastActionSuccess": False, "errorMessage": "too far"})
    result = validator.validate(action, raw, duration_ms=5.0)
    assert result.success is False
    assert result.error == "too far"


def test_navigate_failure_reports_navigation_failed_code():
    validator = ResultValidator()
    action = Action(
        action_type=ActionType.NAVIGATE, parameters={"object_id": "Apple|1"}, step_id=1
    )
    raw = FakeEvent({"lastActionSuccess": False, "errorMessage": "unreachable"})
    result = validator.validate(action, raw, duration_ms=5.0)
    assert result.error_code == ExecutionErrorCode.NAVIGATION_FAILED


def test_pickup_success_requires_object_in_inventory():
    validator = ResultValidator()
    action = Action(
        action_type=ActionType.PICKUP, parameters={"object_id": "Apple|1"}, step_id=1
    )
    # AI2-THOR reports success but the inventory disagrees -- must not
    # be trusted blindly (section 8).
    raw = FakeEvent({"lastActionSuccess": True, "inventoryObjects": [], "objects": []})
    result = validator.validate(action, raw, duration_ms=5.0)
    assert result.success is False
    assert result.error_code == ExecutionErrorCode.VALIDATION_FAILED


def test_pickup_success_with_object_in_inventory_is_success():
    validator = ResultValidator()
    action = Action(
        action_type=ActionType.PICKUP, parameters={"object_id": "Apple|1"}, step_id=1
    )
    raw = FakeEvent(
        {
            "lastActionSuccess": True,
            "inventoryObjects": [{"objectId": "Apple|1"}],
            "objects": [],
        }
    )
    result = validator.validate(action, raw, duration_ms=5.0)
    assert result.success is True


def test_open_success_requires_is_open_true():
    validator = ResultValidator()
    action = Action(
        action_type=ActionType.OPEN, parameters={"object_id": "Fridge|1"}, step_id=1
    )
    raw = FakeEvent(
        {
            "lastActionSuccess": True,
            "objects": [{"objectId": "Fridge|1", "isOpen": False}],
        }
    )
    result = validator.validate(action, raw, duration_ms=5.0)
    assert result.success is False
    assert result.error_code == ExecutionErrorCode.VALIDATION_FAILED


def test_open_success_with_is_open_true_is_success():
    validator = ResultValidator()
    action = Action(
        action_type=ActionType.OPEN, parameters={"object_id": "Fridge|1"}, step_id=1
    )
    raw = FakeEvent(
        {
            "lastActionSuccess": True,
            "objects": [{"objectId": "Fridge|1", "isOpen": True}],
        }
    )
    result = validator.validate(action, raw, duration_ms=5.0)
    assert result.success is True


def test_close_success_requires_is_open_false():
    validator = ResultValidator()
    action = Action(
        action_type=ActionType.CLOSE, parameters={"object_id": "Fridge|1"}, step_id=1
    )
    raw = FakeEvent(
        {
            "lastActionSuccess": True,
            "objects": [{"objectId": "Fridge|1", "isOpen": True}],
        }
    )
    result = validator.validate(action, raw, duration_ms=5.0)
    assert result.success is False


def test_retry_count_is_carried_through():
    validator = ResultValidator()
    action = Action(action_type=ActionType.MOVE_AHEAD, parameters={}, step_id=1)
    raw = FakeEvent({"lastActionSuccess": True})
    result = validator.validate(action, raw, duration_ms=5.0, retry_count=2)
    assert result.retry_count == 2
