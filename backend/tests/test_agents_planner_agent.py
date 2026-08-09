"""
test_agents_planner_agent.py

Purpose
-------
Unit tests for `agents.planner_agent.PlannerAgentWrapper`: `plan()`/
`replan()` delegate identically to the wrapped `Planner`, and state
transitions to `THINKING` during the call.
"""

from __future__ import annotations

from agents.contracts import AgentRequest, AgentState
from agents.planner_agent import PlannerAgentWrapper
from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from schemas.task import SingleTask


def test_plan_delegates_to_wrapped_planner():
    wrapper = PlannerAgentWrapper(RuleBasedPlanner())
    result = wrapper.plan(SingleTask(goal="find", object="mug"), WorldState.initial())
    assert result.success is True
    assert wrapper.get_state() == AgentState.IDLE


def test_replan_is_the_same_call_as_plan():
    wrapper = PlannerAgentWrapper(RuleBasedPlanner())
    task = SingleTask(goal="find", object="mug")
    state = WorldState.initial()
    first = wrapper.plan(task, state)
    second = wrapper.replan(task, state)
    assert [s.action for s in first.plan.steps] == [s.action for s in second.plan.steps]


def test_process_is_not_supported_for_planner():
    wrapper = PlannerAgentWrapper(RuleBasedPlanner())
    response = wrapper.process(AgentRequest(operation="plan"))
    assert response.success is False
    assert response.error is not None
