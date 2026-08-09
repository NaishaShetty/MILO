"""
test_execution_e2e.py

Purpose
-------
Real AI2-THOR/Unity end-to-end tests for the Phase 5 Execution
subsystem (`backend/execution/`) -- section 20's "End-to-End Simulator
Tests." Unlike `backend/tests/test_execution_*.py` (which run against
`FakeSimulator` and are always part of the fast, deterministic CI
suite), every test in this file launches a *real* `Simulator`
(AI2-THOR/Unity subprocess) and is skipped unless explicitly opted in --
mirroring this project's existing convention for anything that can hang
or requires a display (`VISION_ENABLE_SIMULATOR`,
`RUN_LLM_BENCHMARK`, `RUN_LLM_SMOKE_TESTS`). Lives here, next to
`test_navigation.py`/`test_simulator_lifecycle.py`, not in
`backend/tests/`, per `.github/workflows/ci.yml`'s own "Scope note":
`backend/tests/` is genuine, always-CI-runnable unit tests; hands-on
integration scripts that need a real simulator/GPU live alongside the
module they exercise.

Run explicitly with:

    cd backend
    RUN_SIMULATOR_TESTS=true python -m pytest simulator/test_execution_e2e.py -v

Covers, per section 20: movement (Test A), rotation (Test B), pickup
(Test C), open (Test D), put (Test E), and the full multi-step
"store the apple in the refrigerator" task (Test F) -- driven through
the real `ExecutionController`, not hand-rolled `controller.step()`
calls, so this is also the strongest available verification that
Execution actually drives AI2-THOR correctly end to end.
"""

from __future__ import annotations

import os

import pytest

from execution.controller import ExecutionController
from execution.models import ExecutionStatus
from planner.factory import create_planner
from planner.models import PlanStatus, StepStatus
from planner.state import WorldState
from schemas.task import SingleTask
from simulator.simulator import Simulator

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SIMULATOR_TESTS", "false").strip().lower()
    not in ("1", "true", "yes", "on"),
    reason="Real AI2-THOR/Unity end-to-end tests are opt-in -- set "
    "RUN_SIMULATOR_TESTS=true (and ensure a display/binary is reachable) "
    "to run them. Never run automatically in CI (no display server) or "
    "the default local unit-test suite.",
)


@pytest.fixture
def simulator():
    sim = Simulator()
    sim.start()
    try:
        yield sim
    finally:
        sim.stop()


def test_a_move_ahead(simulator):
    before = simulator.get_metadata()["agent"]["position"]
    event = simulator.move_ahead()
    assert event.metadata["lastActionSuccess"] is True
    after = simulator.get_metadata()["agent"]["position"]
    assert after != before


def test_b_rotate_left_and_right(simulator):
    left = simulator.turn_left()
    assert left.metadata["lastActionSuccess"] is True
    right = simulator.turn_right()
    assert right.metadata["lastActionSuccess"] is True


def _first_object_id(simulator, object_type: str):
    objects = simulator.get_metadata()["objects"]
    match = next((o for o in objects if o["objectType"] == object_type), None)
    assert match is not None, f"No {object_type!r} in the default scene."
    return match["objectId"]


def test_c_locate_navigate_and_pickup_apple(simulator):
    object_id = _first_object_id(simulator, "Apple")
    nav_event = simulator.navigate_to(object_id)
    assert nav_event.metadata["lastActionSuccess"] is True

    pickup_event = simulator.pickup_object(object_id)
    assert pickup_event.metadata["lastActionSuccess"] is True
    inventory_ids = {o["objectId"] for o in pickup_event.metadata["inventoryObjects"]}
    assert object_id in inventory_ids


def test_d_navigate_and_open_fridge(simulator):
    object_id = _first_object_id(simulator, "Fridge")
    simulator.navigate_to(object_id)
    open_event = simulator.open_object(object_id)
    assert open_event.metadata["lastActionSuccess"] is True


def test_e_pickup_navigate_and_put(simulator):
    apple_id = _first_object_id(simulator, "Apple")
    fridge_id = _first_object_id(simulator, "Fridge")

    simulator.navigate_to(apple_id)
    simulator.pickup_object(apple_id)
    simulator.navigate_to(fridge_id)
    simulator.open_object(fridge_id)
    put_event = simulator.put_object(fridge_id)

    assert put_event.metadata["lastActionSuccess"] is True
    assert put_event.metadata["inventoryObjects"] == []


def test_f_full_store_apple_in_refrigerator_task(simulator):
    """
    The README's headline demonstration, run for real: Planner ->
    Execution -> AI2-THOR -> validated result, exactly the pipeline
    `docs/phases/phase5_execution.md` documents.
    """
    task = SingleTask(
        task_type="single", goal="store", object="apple", target="refrigerator"
    )
    planning_result = create_planner("rule_based").plan(task, WorldState.initial())
    assert planning_result.success
    plan = planning_result.plan
    assert plan is not None

    controller = ExecutionController(simulator)
    record = controller.execute_plan(plan)

    assert record.status == ExecutionStatus.SUCCESS
    assert plan.status == PlanStatus.COMPLETED
    assert all(step.status == StepStatus.COMPLETED for step in plan.steps)
