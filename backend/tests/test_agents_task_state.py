"""
test_agents_task_state.py

Purpose
-------
Unit tests for `agents.task_state.TaskState`: default construction,
mutation, and `to_dict()` serialization (nested `Plan`/`ExecutionRecord`
/`AgentFailure` models included).
"""

from __future__ import annotations

from agents.contracts import AgentState
from agents.failures import AgentFailure, FailureCategory
from agents.task_state import InputSource, TaskState, TaskStatus
from execution.models import ExecutionRecord, ExecutionStatus
from planner.models import Plan, PlanStep


def test_default_task_state_is_created_and_empty():
    state = TaskState(task_id="t1", user_request="find the mug")
    assert state.status == TaskStatus.CREATED
    assert state.input_source == InputSource.TEXT
    assert state.objects == []
    assert state.failures == []
    assert state.agent_states == {}


def test_to_dict_serializes_nested_models():
    plan = Plan(
        task_id="t1",
        planner_type="rule_based",
        goal_summary={"goal": "find", "object": "mug"},
        steps=[
            PlanStep(
                step_id=1,
                action="navigate",
                target="mug",
                description="navigate to mug",
            )
        ],
    )
    record = ExecutionRecord(
        plan_id=plan.plan_id, task_id="t1", status=ExecutionStatus.SUCCESS
    )
    state = TaskState(
        task_id="t1",
        user_request="find the mug",
        input_source=InputSource.SPEECH,
        goal="find",
        objects=["mug"],
        current_plan=plan,
        execution_history=[record],
        failures=[
            AgentFailure(
                category=FailureCategory.NAVIGATION_FAILURE,
                message="blocked",
                agent="navigation",
            )
        ],
        agent_states={"planner": AgentState.THINKING},
        status=TaskStatus.EXECUTING,
    )

    payload = state.to_dict()
    assert payload["input_source"] == "speech"
    assert payload["current_plan"]["task_id"] == "t1"
    assert payload["execution_history"][0]["status"] == "success"
    assert payload["failures"][0]["category"] == "NAVIGATION_FAILURE"
    assert payload["agent_states"]["planner"] == "thinking"
    assert payload["status"] == "executing"
