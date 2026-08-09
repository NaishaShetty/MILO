"""
test_agents_registry.py

Purpose
-------
Unit tests for `agents.registry.AgentRegistry`: register/get,
missing-name behavior, state snapshotting, and shutdown fan-out.
"""

from __future__ import annotations

import pytest

from agents.base import BaseAgent
from agents.contracts import AgentRequest, AgentResponse, AgentState
from agents.registry import AgentNotRegisteredError, AgentRegistry


class _StubAgent(BaseAgent):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.shutdown_called = False

    def process(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(request_id=request.request_id, success=True)

    def shutdown(self) -> None:
        self.shutdown_called = True
        super().shutdown()


def test_register_and_get_round_trips():
    registry = AgentRegistry()
    agent = _StubAgent("memory")
    registry.register(agent)
    assert registry.get("memory") is agent
    assert list(registry.names()) == ["memory"]


def test_get_missing_agent_raises():
    registry = AgentRegistry()
    with pytest.raises(AgentNotRegisteredError):
        registry.get("missing")


def test_get_optional_returns_none_for_missing():
    registry = AgentRegistry()
    assert registry.get_optional("missing") is None


def test_snapshot_states_reports_every_registered_agent():
    registry = AgentRegistry()
    registry.register(_StubAgent("memory"))
    registry.register(_StubAgent("planner"))
    states = registry.snapshot_states()
    assert states == {"memory": AgentState.IDLE, "planner": AgentState.IDLE}


def test_shutdown_all_calls_shutdown_on_every_agent():
    registry = AgentRegistry()
    a1, a2 = _StubAgent("memory"), _StubAgent("planner")
    registry.register(a1)
    registry.register(a2)
    registry.shutdown_all()
    assert a1.shutdown_called is True
    assert a2.shutdown_called is True
    assert registry.snapshot_states() == {
        "memory": AgentState.SHUTDOWN,
        "planner": AgentState.SHUTDOWN,
    }
