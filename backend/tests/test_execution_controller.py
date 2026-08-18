"""
test_execution_controller.py

Purpose
-------
Integration tests for `execution.controller.ExecutionController` --
section 18/19's "Execution state," "Failure handling," and
"Integration: Planner -> Plan -> ExecutionController -> Simulator
Abstraction" test lists, all against a `FakeSimulator`
(`tests._execution_test_helpers`) so nothing here launches real
AI2-THOR/Unity. Builds real Phase 4 `Plan`s via
`planner.factory.create_planner("rule_based")` -- the same plan
`test_api_planner.py::test_plan_endpoint_returns_valid_plan_for_store_goal`
already asserts the shape of -- so these tests exercise the actual
Planner -> Execution handoff, not a hand-crafted plan shape.
"""

from __future__ import annotations

import time

import pytest

from execution.controller import ExecutionController
from execution.errors import ExecutionErrorCode
from execution.exceptions import PlanNotExecutableError
from execution.models import ExecutionStatus
from planner.factory import create_planner
from planner.models import Plan, PlanStatus, PlanStep, StepStatus
from planner.state import WorldState
from schemas.task import SingleTask
from tests._execution_test_helpers import FakeSimulator, apple_and_fridge_scene

_STORE_TASK = SingleTask(goal="store", object="apple", target="refrigerator")


def _store_plan() -> Plan:
    planning_result = create_planner("rule_based").plan(
        _STORE_TASK, WorldState.initial()
    )
    assert planning_result.success
    assert planning_result.plan is not None
    return planning_result.plan


def test_load_plan_rejects_invalid_plan():
    plan = _store_plan()
    plan.status = PlanStatus.INVALID
    controller = ExecutionController(FakeSimulator())
    with pytest.raises(PlanNotExecutableError):
        controller.load_plan(plan)


def test_load_plan_rejects_empty_plan():
    plan = _store_plan()
    plan.steps = []
    controller = ExecutionController(FakeSimulator())
    with pytest.raises(PlanNotExecutableError):
        controller.load_plan(plan)


def test_full_store_plan_executes_successfully():
    plan = _store_plan()
    simulator = FakeSimulator(apple_and_fridge_scene())
    controller = ExecutionController(simulator)

    record = controller.execute_plan(plan)

    assert record.status == ExecutionStatus.SUCCESS
    assert plan.status == PlanStatus.COMPLETED
    assert all(step.status == StepStatus.COMPLETED for step in plan.steps)
    assert record.success_count == len(plan.steps)
    assert record.failure_count == 0
    assert record.started_at is not None and record.finished_at is not None
    assert record.duration_ms is not None and record.duration_ms >= 0
    # One "started" + one terminal event per step.
    assert len(record.events) == 2 * len(plan.steps)
    # Object actually ends up in the fridge, not held.
    assert simulator.inventory_objects == []


def test_plan_halts_and_skips_remaining_steps_on_unresolvable_target():
    plan = _store_plan()
    # No fridge in the scene -- the "navigate to refrigerator" step can
    # never resolve an objectId.
    simulator = FakeSimulator(
        [o for o in apple_and_fridge_scene() if o["objectType"] != "Refrigerator"]
    )
    controller = ExecutionController(simulator)

    record = controller.execute_plan(plan)

    assert record.status == ExecutionStatus.FAILED
    assert plan.status == PlanStatus.FAILED
    statuses = [step.status for step in plan.steps]
    assert StepStatus.BLOCKED in statuses
    assert StepStatus.SKIPPED in statuses
    blocked_index = statuses.index(StepStatus.BLOCKED)
    assert all(s == StepStatus.SKIPPED for s in statuses[blocked_index + 1 :])
    assert record.error is not None
    assert record.error.code == ExecutionErrorCode.OBJECT_NOT_FOUND


def test_simulator_reported_failure_marks_step_failed_and_halts():
    plan = _store_plan()
    simulator = FakeSimulator(apple_and_fridge_scene(), fail_actions={"pickup"})
    controller = ExecutionController(simulator)

    record = controller.execute_plan(plan)

    assert record.status == ExecutionStatus.FAILED
    pickup_step = next(s for s in plan.steps if s.action == "pickup")
    assert pickup_step.status == StepStatus.FAILED
    pickup_result = next(s for s in record.step_results if s.action == "pickup")
    assert pickup_result.error is not None
    # The simulator itself reported lastActionSuccess=False here (not a
    # ground-truth-vs-report mismatch) -- SIMULATOR_ERROR, not
    # VALIDATION_FAILED (reserved for "simulator claims success but the
    # expected state change is missing," see test_execution_validator.py).
    assert pickup_result.error.code == ExecutionErrorCode.SIMULATOR_ERROR


def test_cancel_before_execution_cancels_every_step():
    plan = _store_plan()
    simulator = FakeSimulator(apple_and_fridge_scene())
    controller = ExecutionController(simulator)
    controller.cancel()

    record = controller.execute_plan(plan)

    assert record.status == ExecutionStatus.CANCELLED
    assert plan.status == PlanStatus.CANCELLED
    assert all(step.status == StepStatus.CANCELLED for step in plan.steps)
    # No simulator calls at all -- cancellation is checked before dispatch.
    assert simulator.calls == []


def test_bounded_retry_recovers_from_a_transient_failure():
    scene = apple_and_fridge_scene()
    attempts = {"open": 0}

    def flaky_open():
        attempts["open"] += 1
        if attempts["open"] >= 2:
            simulator._fail_actions.discard(
                "open"
            )  # noqa: B023 -- closure is fine here

    simulator = FakeSimulator(scene, fail_actions={"open"}, hooks={"open": flaky_open})
    controller = ExecutionController(simulator, max_step_retries=1)

    plan = _store_plan()
    record = controller.execute_plan(plan)

    assert record.status == ExecutionStatus.SUCCESS
    open_result = next(s for s in record.step_results if s.action == "open")
    assert open_result.result is not None
    assert open_result.result.retry_count == 1


def test_retries_are_bounded_and_never_infinite():
    simulator = FakeSimulator(apple_and_fridge_scene(), fail_actions={"open"})
    controller = ExecutionController(simulator, max_step_retries=2)

    plan = _store_plan()
    record = controller.execute_plan(plan)

    assert record.status == ExecutionStatus.FAILED
    open_result = next(s for s in record.step_results if s.action == "open")
    # Exactly max_step_retries retries were attempted, then it gave up.
    assert open_result.result is not None
    assert open_result.result.retry_count == 2
    open_calls = [c for c in simulator.calls if c["action"] == "open"]
    assert len(open_calls) == 3  # 1 initial attempt + 2 retries


def test_step_timeout_is_reported_as_action_timeout():
    step = PlanStep(
        step_id=1, action="navigate", target="apple", description="Navigate to apple"
    )
    plan = Plan(
        plan_id="p1",
        task_id="t1",
        planner_type="test",
        goal_summary={},
        steps=[step],
        status=PlanStatus.VALID,
    )
    state = WorldState.initial()
    state.object("apple").is_located = True

    simulator = FakeSimulator(
        apple_and_fridge_scene(), hooks={"navigate": lambda: time.sleep(0.3)}
    )
    controller = ExecutionController(simulator, step_timeout_s=0.05)

    record = controller.execute_plan(plan, state)

    assert record.status == ExecutionStatus.FAILED
    assert record.error is not None
    assert record.error.code == ExecutionErrorCode.ACTION_TIMEOUT


def test_engine_level_timeout_with_no_step_timeout_configured_is_reported_accurately():
    # Regression test (Phase E follow-up): `ai2thor.fifo_server.
    # FifoServer` has its own internal ~100s pipe-read timeout,
    # completely independent of `step_timeout_s`. Since Python 3.11,
    # `concurrent.futures.TimeoutError is TimeoutError`, so that
    # AI2-THOR-internal `TimeoutError` lands in the same `except
    # FutureTimeoutError:` clause `_dispatch_with_retries` uses for its
    # own `step_timeout_s`-configured path -- previously misattributed
    # to `self._step_timeout_s` (`None`), producing the nonsensical
    # "exceeded its Nones timeout" message. With no `step_timeout_s`
    # configured (the default -- see `TaskRunner`/`ExecutionAgentWrapper`,
    # neither pass one), a `TimeoutError` raised directly by the
    # simulator/dispatcher must be this engine-level timeout, not ours.
    step = PlanStep(
        step_id=1, action="navigate", target="apple", description="Navigate to apple"
    )
    plan = Plan(
        plan_id="p1",
        task_id="t1",
        planner_type="test",
        goal_summary={},
        steps=[step],
        status=PlanStatus.VALID,
    )
    state = WorldState.initial()
    state.object("apple").is_located = True

    def _raise_engine_timeout():
        raise TimeoutError(
            "Reading from AI2-THOR backend timed out (using 100.0s) timeout."
        )

    simulator = FakeSimulator(
        apple_and_fridge_scene(), hooks={"navigate": _raise_engine_timeout}
    )
    controller = ExecutionController(simulator)  # no step_timeout_s configured

    record = controller.execute_plan(plan, state)

    assert record.status == ExecutionStatus.FAILED
    assert record.error is not None
    assert record.error.code == ExecutionErrorCode.ACTION_TIMEOUT
    assert "Nones" not in record.error.message
    assert "AI2-THOR" in record.error.message
    assert "no step_timeout_s" in record.error.message
    assert "100.0s" in record.error.message  # the real AI2-THOR-reported number


def test_execute_plan_without_simulator_raises():
    plan = _store_plan()
    controller = ExecutionController(None)
    from execution.exceptions import SimulatorUnavailableError

    with pytest.raises(SimulatorUnavailableError):
        controller.execute_plan(plan)
