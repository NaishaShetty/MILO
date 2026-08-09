"""
test_agents_navigation_agent.py

Purpose
-------
Unit tests for `agents.navigation_agent.NavigationAgent.diagnose()`:
refines `OBJECT_NOT_REACHABLE` to `PATH_BLOCKED`, `NAVIGATION_FAILED`
to `NAVIGATION_FAILURE`, ignores non-navigation failures, and ignores
successful records.
"""

from __future__ import annotations

from agents.failures import FailureCategory
from agents.navigation_agent import NavigationAgent
from execution.errors import ExecutionError, ExecutionErrorCode
from execution.models import (
    ExecutionRecord,
    ExecutionStatus,
    StepExecutionRecord,
    StepStatus,
)
from planner.state import WorldState


def _record(action: str, code: ExecutionErrorCode, *, recoverable: bool = True):
    return ExecutionRecord(
        plan_id="p1",
        task_id="t1",
        status=ExecutionStatus.FAILED,
        step_results=[
            StepExecutionRecord(
                step_id=1,
                action=action,
                target="fridge",
                status=StepStatus.FAILED,
                error=ExecutionError(
                    code=code, message="cannot reach it", recoverable=recoverable
                ),
            )
        ],
    )


def test_object_not_reachable_becomes_path_blocked():
    agent = NavigationAgent()
    record = _record("navigate", ExecutionErrorCode.OBJECT_NOT_REACHABLE)
    failure = agent.diagnose(record, WorldState.initial())
    assert failure is not None
    assert failure.category == FailureCategory.PATH_BLOCKED
    assert failure.agent == "navigation"


def test_navigation_failed_stays_navigation_failure():
    agent = NavigationAgent()
    record = _record("navigate", ExecutionErrorCode.NAVIGATION_FAILED)
    failure = agent.diagnose(record, WorldState.initial())
    assert failure is not None
    assert failure.category == FailureCategory.NAVIGATION_FAILURE


def test_non_navigation_action_is_ignored():
    agent = NavigationAgent()
    record = _record("pickup", ExecutionErrorCode.OBJECT_NOT_REACHABLE)
    assert agent.diagnose(record, WorldState.initial()) is None


def test_successful_record_has_no_diagnosis():
    agent = NavigationAgent()
    record = ExecutionRecord(plan_id="p1", task_id="t1", status=ExecutionStatus.SUCCESS)
    assert agent.diagnose(record, WorldState.initial()) is None


def test_current_location_reads_world_state():
    agent = NavigationAgent()
    state = WorldState.initial()
    state.robot_location = "kitchen"
    assert agent.current_location(state) == "kitchen"
