"""
test_agents_memory_agent.py

Purpose
-------
Unit tests for `agents.memory_agent.MemoryAgentWrapper`: delegation to
`memory.agent.MemoryAgent`, state transitions, and the generic
`process()` "retrieve" operation.
"""

from __future__ import annotations

from agents.contracts import AgentRequest, AgentState
from agents.memory_agent import MemoryAgentWrapper
from memory.agent import MemoryAgent, MemoryQueryContext
from memory.config import MemoryConfig
from memory.models import MemoryProvenance


def _config(tmp_path):
    return MemoryConfig(
        enabled=True,
        database_path=tmp_path / "memory.db",
        vector_store_path=tmp_path / "vector_store",
    )


def test_retrieve_relevant_memories_delegates_and_resets_state(tmp_path):
    underlying = MemoryAgent.from_config(_config(tmp_path))
    underlying.remember_observation(
        "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
    )
    wrapper = MemoryAgentWrapper(underlying)
    assert wrapper.get_state() == AgentState.IDLE

    result = wrapper.retrieve_relevant_memories(
        MemoryQueryContext(goal="find", object="mug")
    )

    assert not result.is_empty
    assert wrapper.get_state() == AgentState.IDLE


def test_remember_episode_and_failure_delegate(tmp_path):
    from memory.semantics import EpisodicDetails, FailureDetails

    underlying = MemoryAgent.from_config(_config(tmp_path))
    wrapper = MemoryAgentWrapper(underlying)

    episodic = wrapper.remember_episode(
        EpisodicDetails(task_summary="find mug", outcome="success"),
        episode_id="ep-1",
    )
    assert episodic is not None

    failure = wrapper.remember_failure(
        FailureDetails(
            task="find mug",
            action="navigate",
            failure_reason="blocked",
            cause="blocked",
            recovery=None,
            outcome="failed",
        ),
        episode_id="ep-2",
    )
    assert failure is not None


def test_process_retrieve_operation_returns_summary(tmp_path):
    underlying = MemoryAgent.from_config(_config(tmp_path))
    wrapper = MemoryAgentWrapper(underlying)
    response = wrapper.process(
        AgentRequest(operation="retrieve", payload={"goal": "find", "object": "mug"})
    )
    assert response.success is True
    assert "query" in response.data
    assert "count" in response.data


def test_process_rejects_unsupported_operation(tmp_path):
    underlying = MemoryAgent.from_config(_config(tmp_path))
    wrapper = MemoryAgentWrapper(underlying)
    response = wrapper.process(AgentRequest(operation="delete_everything"))
    assert response.success is False
    assert response.error is not None
