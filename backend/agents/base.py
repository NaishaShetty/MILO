"""
base.py (backend/agents)

Purpose
-------
`BaseAgent` -- the one lifecycle contract every Phase 7 agent
implements: `initialize()`, `process()`, `get_state()`, `shutdown()`
(the phase brief's exact list). Concrete agents (`MemoryAgentWrapper`,
`PlannerAgentWrapper`, ...) additionally expose their own strongly
typed methods for real callers to use directly -- `process()` is the
one uniform entry point a generic caller (an `AgentRegistry` walk, a
future `/agents/{name}/status` route) can use without knowing which
concrete agent it has, not a replacement for those typed methods.

Why `initialize`/`shutdown` default to no-ops
--------------------------------------------------
Most wrappers here hold no per-agent resource beyond the already-
constructed Phase 1-6 collaborator handed to `__init__` (e.g.
`PlannerAgentWrapper` just holds a `Planner`) -- there is nothing for
`initialize()`/`shutdown()` to actually do, and forcing every subclass
to write an empty override would be exactly the kind of ceremony this
project's "do not overengineer" principle rules out. A wrapper that
*does* own a resource (none currently do) overrides one or both.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agents.contracts import AgentRequest, AgentResponse, AgentState


class BaseAgent(ABC):
    """Common lifecycle every Phase 7 agent implements. See module docstring."""

    #: Stable identifier used as this agent's key in `AgentRegistry`
    #: and as `AgentError.agent`/`Event.agent` -- overridden per subclass.
    name: str = "base"

    def __init__(self) -> None:
        self._state = AgentState.IDLE

    def initialize(self) -> None:
        """Prepares the agent to receive `process()` calls. No-op by default."""
        self._state = AgentState.IDLE

    @abstractmethod
    def process(self, request: AgentRequest) -> AgentResponse:
        """
        Generic dispatch entry point. Concrete agents are expected to
        switch on `request.operation` and delegate to their own typed
        methods -- see each subclass for its supported operations.
        """
        raise NotImplementedError

    def get_state(self) -> AgentState:
        """Returns this agent's current lifecycle state."""
        return self._state

    def shutdown(self) -> None:
        """Releases any resources this agent holds. No-op by default."""
        self._state = AgentState.SHUTDOWN
