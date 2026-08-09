"""
test_agents_execution_agent.py

Purpose
-------
Unit tests for `agents.execution_agent.ExecutionAgentWrapper`:
delegation to a fresh `ExecutionController` per call, and
`failures_from_record()`'s translation into the shared
`agents.failures.FailureCategory` vocabulary.
"""

from __future__ import annotations

import threading
import time

from _execution_test_helpers import FakeSimulator

from agents.execution_agent import ExecutionAgentWrapper
from agents.failures import FailureCategory
from execution.models import ExecutionStatus
from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from schemas.task import SingleTask


def _mug_table_scene():
    return [
        {
            "objectId": "Mug|1",
            "objectType": "Mug",
            "distance": 1.0,
            "isOpen": None,
            "parentReceptacle": "Table|1",
        },
        {"objectId": "Table|1", "objectType": "Table", "distance": 2.0, "isOpen": None},
    ]


def test_execute_plan_succeeds_against_fake_simulator():
    planner = RuleBasedPlanner()
    result = planner.plan(SingleTask(goal="find", object="mug"), WorldState.initial())
    wrapper = ExecutionAgentWrapper(FakeSimulator(objects=_mug_table_scene()))

    record = wrapper.execute_plan(result.plan, WorldState.initial())

    assert record.status == ExecutionStatus.SUCCESS
    assert ExecutionAgentWrapper.failures_from_record(record) == []


def test_failures_from_record_translates_navigation_failure():
    planner = RuleBasedPlanner()
    result = planner.plan(
        SingleTask(goal="find", object="fridge"), WorldState.initial()
    )
    scene = [
        {
            "objectId": "Fridge|1",
            "objectType": "Fridge",
            "distance": 1.0,
            "isOpen": False,
        }
    ]
    wrapper = ExecutionAgentWrapper(
        FakeSimulator(objects=scene, fail_actions={"navigate"})
    )

    record = wrapper.execute_plan(result.plan, WorldState.initial())

    assert record.status == ExecutionStatus.FAILED
    failures = ExecutionAgentWrapper.failures_from_record(record)
    assert len(failures) == 1
    assert failures[0].category in (
        FailureCategory.NAVIGATION_FAILURE,
        FailureCategory.OBJECT_NOT_FOUND,
    )


def test_cancel_current_stops_an_in_flight_execution_from_another_thread():
    gate = threading.Event()

    def _block_until_released() -> None:
        gate.wait(timeout=5.0)

    planner = RuleBasedPlanner()
    result = planner.plan(SingleTask(goal="find", object="mug"), WorldState.initial())
    simulator = FakeSimulator(
        objects=_mug_table_scene(), hooks={"navigate": _block_until_released}
    )
    wrapper = ExecutionAgentWrapper(simulator)

    record_holder = {}

    def _run() -> None:
        record_holder["record"] = wrapper.execute_plan(
            result.plan, WorldState.initial()
        )

    thread = threading.Thread(target=_run)
    thread.start()
    time.sleep(0.05)  # let the background thread reach the blocking hook

    wrapper.cancel_current()
    gate.set()
    thread.join(timeout=5.0)

    record = record_holder["record"]
    # The blocked "navigate" step itself completes once released (a
    # cancellation checked between steps never interrupts an
    # already-dispatched call -- see `ExecutionController.execute_plan()`'s
    # own docstring); the *plan* still ends CANCELLED, which is the
    # observable contract `cancel_current()` promises.
    assert record.status == ExecutionStatus.CANCELLED


def test_cancel_current_is_a_no_op_when_nothing_is_executing():
    wrapper = ExecutionAgentWrapper(FakeSimulator(objects=_mug_table_scene()))
    wrapper.cancel_current()  # must not raise
