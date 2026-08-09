"""
contracts.py (backend/agents)

Purpose
-------
The common shape every Phase 7 agent speaks: `AgentState` (a lifecycle
status a caller -- Mission Control, a future `/agents/{name}/status`
route -- can poll), `AgentRequest`/`AgentResponse` (the generic
envelope `BaseAgent.process()` accepts/returns), and `AgentEvent` /
`AgentError` (the two things an agent call can produce besides its
main payload).

Why a generic envelope, not per-agent request/response types
------------------------------------------------------------------
Each concrete agent (`MemoryAgent`, `PlannerAgent`, ...) already has
its own strongly-typed methods wrapping a strongly-typed Phase 1-6
collaborator (e.g. `PlannerAgentWrapper.plan(task, state,
memory_context) -> PlanningResult`) -- those signatures are how this
codebase's other modules actually call an agent, and they are not
replaced by anything here. `AgentRequest`/`AgentResponse` exist only
for the one place a *uniform* shape is genuinely useful: `BaseAgent.
process()`, the lifecycle method a caller that only knows "I have an
agent" (an `AgentRegistry` walk, a health-check route) can call without
knowing which concrete agent it has. `payload`/`data` are therefore
deliberately open `Dict[str, Any]` fields, not typed per agent --
mirrors `planner.models.Plan.metadata` and `execution.errors.
ExecutionError.details`'s existing "this needs to vary per caller"
rationale.

Why Pydantic, `extra="forbid"`
----------------------------------
Matches every other schema file in this project (`schemas/task.py`,
`execution/models.py`, `execution/errors.py`): typed, validated,
JSON-serializable by construction, and a malformed field fails loudly
at the boundary instead of drifting silently downstream.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class AgentState(str, Enum):
    """
    Every lifecycle state a `BaseAgent` can report via `get_state()`.
    Mirrors the phase brief's Mission Control example
    (`Vision ACTIVE`, `Planner THINKING`, `Whisper IDLE`, ...).
    """

    IDLE = "idle"
    ACTIVE = "active"
    THINKING = "thinking"
    WAITING = "waiting"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class AgentError(BaseModel):
    """
    One structured failure raised out of `BaseAgent.process()` itself
    (the agent could not run at all -- not "ran and reported a
    business failure," which is a normal `AgentResponse.success=False`
    instead; see `failures.py` for that distinct, much more common
    case). Kept separate from `failures.FailureCategory` on purpose:
    this is "the agent broke," not "the task failed."
    """

    model_config = ConfigDict(extra="forbid")

    agent: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class AgentRequest(BaseModel):
    """Generic envelope into `BaseAgent.process()`. See module docstring."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operation: str = Field(description="Which of the agent's methods to invoke.")
    payload: Dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    """Generic envelope out of `BaseAgent.process()`. See module docstring."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[AgentError] = None
