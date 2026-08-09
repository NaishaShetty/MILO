"""
planner_agent.py (backend/agents)

Purpose
-------
`PlannerAgentWrapper` -- the `BaseAgent` shape around a `planner.
planner.Planner` (built via `planner.factory.create_planner`, section
7.8). Adds no planning logic: `plan()` and `replan()` are both the
exact same call, `Planner.plan(task, state, memory_context)` --
"replanning" is not a different code path (this package has no
separate `Planner.replan()` method, nor should it invent one), it is
this same method invoked again with a fresher `WorldState` and
optionally an updated `memory_context`. `Orchestrator` is the module
that decides *when* to call `replan()` vs. `plan()`; this wrapper just
names the intent at the call site.
"""

from __future__ import annotations

from typing import Optional

from agents.base import BaseAgent
from agents.contracts import AgentError, AgentRequest, AgentResponse, AgentState
from memory.agent import PlannerMemoryContext
from planner.models import PlanningResult
from planner.planner import Planner
from planner.state import WorldState
from schemas.task import SingleTask


class PlannerAgentWrapper(BaseAgent):
    """Thin `BaseAgent` wrapper around a `planner.planner.Planner`. See module docstring."""

    name = "planner"

    def __init__(self, planner: Planner) -> None:
        super().__init__()
        self._planner = planner

    def plan(
        self,
        task: SingleTask,
        state: WorldState,
        memory_context: Optional[PlannerMemoryContext] = None,
    ) -> PlanningResult:
        self._state = AgentState.THINKING
        try:
            return self._planner.plan(task, state, memory_context)
        finally:
            self._state = AgentState.IDLE

    def replan(
        self,
        task: SingleTask,
        state: WorldState,
        memory_context: Optional[PlannerMemoryContext] = None,
    ) -> PlanningResult:
        """Same call as `plan()` -- see module docstring for why."""
        return self.plan(task, state, memory_context)

    def process(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(
            request_id=request.request_id,
            success=False,
            error=AgentError(
                agent=self.name,
                message="PlannerAgentWrapper requires typed SingleTask/WorldState "
                "arguments -- call plan()/replan() directly, not process().",
            ),
        )
