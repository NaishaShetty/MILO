"""
test_agents_contracts.py

Purpose
-------
Unit tests for `agents.contracts` (`AgentState`, `AgentError`,
`AgentRequest`, `AgentResponse`) and `agents.base.BaseAgent`'s default
lifecycle behavior.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.base import BaseAgent
from agents.contracts import AgentError, AgentRequest, AgentResponse, AgentState


def test_agent_request_generates_a_request_id_when_omitted():
    request = AgentRequest(operation="ping")
    assert request.request_id
    assert request.payload == {}


def test_agent_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        AgentRequest(operation="ping", bogus="nope")


def test_agent_response_carries_error_only_on_failure():
    response = AgentResponse(
        request_id="abc",
        success=False,
        error=AgentError(agent="planner", message="boom"),
    )
    assert response.success is False
    assert response.error is not None
    assert response.error.agent == "planner"


def test_agent_state_values_match_mission_control_vocabulary():
    assert {s.value for s in AgentState} == {
        "idle",
        "active",
        "thinking",
        "waiting",
        "error",
        "shutdown",
    }


class _EchoAgent(BaseAgent):
    name = "echo"

    def process(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(
            request_id=request.request_id, success=True, data=request.payload
        )


def test_base_agent_default_lifecycle():
    agent = _EchoAgent()
    assert agent.get_state() == AgentState.IDLE

    agent.initialize()
    assert agent.get_state() == AgentState.IDLE

    response = agent.process(AgentRequest(operation="echo", payload={"x": 1}))
    assert response.success is True
    assert response.data == {"x": 1}

    agent.shutdown()
    assert agent.get_state() == AgentState.SHUTDOWN
