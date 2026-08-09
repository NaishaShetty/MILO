"""
registry.py (backend/agents)

Purpose
-------
`AgentRegistry` -- section 7.5's registry, so nothing that needs an
agent (`Orchestrator`, a future `/agents` route) hard-codes which
concrete agent instance backs a name. Same dict-registration pattern
as `planner/factory.py`'s `_REGISTRY` (register-by-name, `get(name)`,
no dynamic plugin discovery -- this project's "do not overengineer"
principle rules that out for a handful of agents in one process).

Why this module imports no concrete agent
------------------------------------------------
`AgentRegistry` is typed purely against `agents.base.BaseAgent` and
never imports `vision_agent.py`/`memory_agent.py`/etc. itself --
whoever wires the system together (today: `Orchestrator.__init__`;
later: the FastAPI lifespan) constructs each concrete agent and calls
`register()`, so this module cannot become a place a circular import
sneaks in (7.5's explicit warning), and adding a new agent later never
means editing this file.
"""

from __future__ import annotations

from typing import Dict, Iterator, Optional

from agents.base import BaseAgent
from agents.contracts import AgentState


class AgentNotRegisteredError(KeyError):
    """Raised by `AgentRegistry.get()` for a name nothing registered."""


class AgentRegistry:
    """Holds one `BaseAgent` instance per name. See module docstring."""

    def __init__(self) -> None:
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        try:
            return self._agents[name]
        except KeyError:
            raise AgentNotRegisteredError(name) from None

    def get_optional(self, name: str) -> Optional[BaseAgent]:
        return self._agents.get(name)

    def names(self) -> Iterator[str]:
        return iter(self._agents.keys())

    def snapshot_states(self) -> Dict[str, AgentState]:
        """Every registered agent's current `get_state()` -- Mission
        Control's "Agent status" panel, in one call."""
        return {name: agent.get_state() for name, agent in self._agents.items()}

    def shutdown_all(self) -> None:
        for agent in self._agents.values():
            agent.shutdown()
