"""The API's executor has a step timeout by default (EXECUTION_STEP_TIMEOUT_S)."""

from __future__ import annotations

import threading
import time

import pytest

from agents.execution_agent import ExecutionAgentWrapper
from api.routes import tasks as task_routes
from execution.errors import ExecutionErrorCode
from execution.models import ExecutionStatus
from planner.models import Plan, PlanStatus, PlanStep
from planner.state import WorldState
from tests._execution_test_helpers import FakeSimulator, apple_and_fridge_scene


def test_default_step_timeout_is_120_seconds(monkeypatch):
    monkeypatch.delenv("EXECUTION_STEP_TIMEOUT_S", raising=False)
    assert task_routes._step_timeout_from_env() == 120.0


@pytest.mark.parametrize(
    "raw,expected",
    [("30", 30.0), ("0", None), ("-1", None), ("soon", 120.0), ("  ", 120.0)],
)
def test_step_timeout_env_values(monkeypatch, raw, expected):
    monkeypatch.setenv("EXECUTION_STEP_TIMEOUT_S", raw)
    assert task_routes._step_timeout_from_env() == expected


def test_hung_simulator_call_fails_on_time_with_the_default_config(monkeypatch):
    # Same wiring as the API (env -> ExecutionAgent -> controller), with
    # the default shrunk so the test doesn't wait two minutes.
    monkeypatch.delenv("EXECUTION_STEP_TIMEOUT_S", raising=False)
    monkeypatch.setattr(task_routes, "DEFAULT_STEP_TIMEOUT_S", 0.2)
    release = threading.Event()
    simulator = FakeSimulator(
        apple_and_fridge_scene(), hooks={"navigate": lambda: release.wait(30)}
    )
    agent = ExecutionAgentWrapper(
        simulator, step_timeout_s=task_routes._step_timeout_from_env()
    )
    plan = Plan(
        plan_id="p1",
        task_id="t1",
        planner_type="test",
        goal_summary={},
        steps=[
            PlanStep(step_id=1, action="navigate", target="apple", description="go")
        ],
        status=PlanStatus.VALID,
    )
    state = WorldState.initial()
    state.object("apple").is_located = True

    started = time.monotonic()
    try:
        record = agent.execute_plan(plan, state)
    finally:
        release.set()
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"step did not fail at its timeout ({elapsed:.1f}s)"
    assert record.status == ExecutionStatus.FAILED
    assert record.error is not None
    assert record.error.code == ExecutionErrorCode.ACTION_TIMEOUT
