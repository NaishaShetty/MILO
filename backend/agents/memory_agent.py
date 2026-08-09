"""
memory_agent.py (backend/agents)

Purpose
-------
`MemoryAgentWrapper` -- the `BaseAgent` shape around `memory.agent.
MemoryAgent` (section 7.7). Adds no memory logic of its own: every
public method here is a direct, one-line delegation to the exact
method `orchestration.task_runner.TaskRunner` already calls
(`retrieve_relevant_memories`, `remember_episode`, `remember_failure`,
`remember_observation`, `link_recovery`). `memory.agent.MemoryAgent`
already never raises and already degrades gracefully to empty/`None`
when unavailable (see that module's own docstring) -- this wrapper
does not re-implement or duplicate that try/except, it just forwards.

Why `Orchestrator` still calls `memory.agent.MemoryAgent` methods by
name instead of only going through `process()`
------------------------------------------------------------------------
Same rationale as every other wrapper in this package (see `agents.
base.BaseAgent`'s docstring): `process()` is the generic entry point
for a caller that doesn't know which concrete agent it has. A caller
that *does* know it has a `MemoryAgentWrapper` (the `Orchestrator`)
uses its typed methods directly, exactly as `TaskRunner` uses `memory.
agent.MemoryAgent`'s typed methods directly today.
"""

from __future__ import annotations

from typing import Optional, Sequence

from agents.base import BaseAgent
from agents.contracts import AgentError, AgentRequest, AgentResponse, AgentState
from memory.agent import MemoryAgent, MemoryQueryContext, PlannerMemoryContext
from memory.models import Memory, MemoryProvenance, MemoryType
from memory.semantics import EpisodicDetails, FailureDetails


class MemoryAgentWrapper(BaseAgent):
    """Thin `BaseAgent` wrapper around `memory.agent.MemoryAgent`. See module docstring."""

    name = "memory"

    def __init__(self, memory_agent: MemoryAgent) -> None:
        super().__init__()
        self._memory_agent = memory_agent

    def is_available(self) -> bool:
        return self._memory_agent.is_available()

    def retrieve_relevant_memories(
        self,
        context: MemoryQueryContext,
        *,
        memory_types: Optional[Sequence[MemoryType]] = None,
        top_k: int = 5,
    ) -> PlannerMemoryContext:
        self._state = AgentState.ACTIVE
        try:
            return self._memory_agent.retrieve_relevant_memories(
                context, memory_types=memory_types, top_k=top_k
            )
        finally:
            self._state = AgentState.IDLE

    def remember_episode(
        self,
        details: EpisodicDetails,
        *,
        episode_id: str,
        task_id: Optional[str] = None,
        recovered_failure_ids: Optional[Sequence[str]] = None,
    ) -> Optional[Memory]:
        self._state = AgentState.ACTIVE
        try:
            return self._memory_agent.remember_episode(
                details,
                episode_id=episode_id,
                task_id=task_id,
                recovered_failure_ids=recovered_failure_ids,
            )
        finally:
            self._state = AgentState.IDLE

    def remember_failure(
        self,
        details: FailureDetails,
        *,
        episode_id: str,
        task_id: Optional[str] = None,
    ) -> Optional[Memory]:
        self._state = AgentState.ACTIVE
        try:
            return self._memory_agent.remember_failure(
                details, episode_id=episode_id, task_id=task_id
            )
        finally:
            self._state = AgentState.IDLE

    def remember_observation(
        self,
        subject: str,
        relation: str,
        obj: str,
        *,
        provenance: MemoryProvenance,
        confidence: float = 1.0,
        episode_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Optional[Memory]:
        self._state = AgentState.ACTIVE
        try:
            return self._memory_agent.remember_observation(
                subject,
                relation,
                obj,
                provenance=provenance,
                confidence=confidence,
                episode_id=episode_id,
                task_id=task_id,
            )
        finally:
            self._state = AgentState.IDLE

    def process(self, request: AgentRequest) -> AgentResponse:
        """
        Supports one generic operation: `"retrieve"`, taking
        `payload={"goal": ..., "object": ..., "target": ..., "top_k": ...}`.
        Writes (`remember_*`) are intentionally not exposed here -- they
        need typed `EpisodicDetails`/`FailureDetails` a generic
        `Dict[str, Any]` payload cannot safely carry; callers that need
        to write call `remember_episode`/`remember_failure`/
        `remember_observation` directly, exactly as `Orchestrator` does.
        """
        if request.operation != "retrieve":
            return AgentResponse(
                request_id=request.request_id,
                success=False,
                error=AgentError(
                    agent=self.name,
                    message=f"unsupported operation: {request.operation!r}",
                ),
            )
        context = MemoryQueryContext(
            goal=request.payload.get("goal"),
            object=request.payload.get("object"),
            target=request.payload.get("target"),
        )
        result = self.retrieve_relevant_memories(
            context, top_k=request.payload.get("top_k", 5)
        )
        return AgentResponse(
            request_id=request.request_id, success=True, data=result.summary()
        )
