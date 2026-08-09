"""
test_execution_preconditions.py

Purpose
-------
Unit tests for `execution.preconditions.PreconditionChecker` -- section
18's "Preconditions" test list: valid pickup, invalid pickup (target
not near), already-holding-incompatible-object (hand not empty),
invalid/unresolved target, and an unrecognized action name. Exercises
both layers this checker runs (grounded existence checks against a
resolved objectId, and the symbolic `planner.actions.ACTION_REGISTRY`
checks it reuses directly from Phase 4) with zero AI2-THOR/simulator
dependency -- everything here is a plain `WorldState`.
"""

from __future__ import annotations

from execution.errors import ExecutionErrorCode
from execution.preconditions import PreconditionChecker
from planner.models import PlanStep
from planner.state import WorldState


def _step(action: str, target=None, parameters=None) -> PlanStep:
    return PlanStep(
        step_id=1,
        action=action,
        target=target,
        parameters=parameters or {},
        description=f"{action} {target or ''}".strip(),
    )


def test_unknown_action_is_invalid_action():
    checker = PreconditionChecker()
    result = checker.check(
        _step("teleport"), WorldState.initial(), resolved_object_id=None
    )
    assert result.satisfied is False
    assert result.error_code == ExecutionErrorCode.INVALID_ACTION


def test_place_without_container_parameter_is_invalid_parameter():
    checker = PreconditionChecker()
    result = checker.check(
        _step("place", target="apple"),
        WorldState.initial(),
        resolved_object_id="Apple|1",
    )
    assert result.satisfied is False
    assert result.error_code == ExecutionErrorCode.INVALID_PARAMETER


def test_pickup_with_unresolved_target_is_object_not_found():
    checker = PreconditionChecker()
    result = checker.check(
        _step("pickup", target="apple"), WorldState.initial(), resolved_object_id=None
    )
    assert result.satisfied is False
    assert result.error_code == ExecutionErrorCode.OBJECT_NOT_FOUND


def test_place_with_unresolved_container_is_target_not_found():
    checker = PreconditionChecker()
    state = WorldState.initial()
    state.object("apple").is_held = True
    state.robot_holding = "apple"
    result = checker.check(
        _step("place", target="apple", parameters={"container": "refrigerator"}),
        state,
        resolved_object_id="Apple|1",
        resolved_container_id=None,
    )
    assert result.satisfied is False
    assert result.error_code == ExecutionErrorCode.TARGET_NOT_FOUND


def test_pickup_before_navigate_is_precondition_failed():
    # Fresh state: the apple has never been navigated to
    # (is_near_robot=False), so pickup's "target_near" precondition
    # must fail -- this is what catches "pickup" issued out of order.
    checker = PreconditionChecker()
    result = checker.check(
        _step("pickup", target="apple"),
        WorldState.initial(),
        resolved_object_id="Apple|1",
    )
    assert result.satisfied is False
    assert result.error_code == ExecutionErrorCode.PRECONDITION_FAILED
    assert any("near" in msg for msg in result.unmet)


def test_pickup_while_already_holding_something_else_is_precondition_failed():
    checker = PreconditionChecker()
    state = WorldState.initial()
    state.object("apple").is_near_robot = True
    state.robot_holding = "mug"
    result = checker.check(
        _step("pickup", target="apple"), state, resolved_object_id="Apple|1"
    )
    assert result.satisfied is False
    assert result.error_code == ExecutionErrorCode.PRECONDITION_FAILED


def test_valid_pickup_is_satisfied():
    checker = PreconditionChecker()
    state = WorldState.initial()
    state.object("apple").is_near_robot = True
    result = checker.check(
        _step("pickup", target="apple"), state, resolved_object_id="Apple|1"
    )
    assert result.satisfied is True
    assert result.error_code is None


def test_valid_navigate_is_satisfied_once_located():
    checker = PreconditionChecker()
    state = WorldState.initial()
    state.object("apple").is_located = True
    result = checker.check(
        _step("navigate", target="apple"), state, resolved_object_id="Apple|1"
    )
    assert result.satisfied is True


def test_locate_has_no_resolved_target_requirement():
    # `locate` is not in _REQUIRES_RESOLVED_TARGET -- it has no
    # simulator-side effect (see dispatcher.py), so it must never be
    # rejected purely for lacking a resolved objectId.
    checker = PreconditionChecker()
    result = checker.check(
        _step("locate", target="apple"), WorldState.initial(), resolved_object_id=None
    )
    assert result.satisfied is True
