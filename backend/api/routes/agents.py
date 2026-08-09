"""
agents.py (backend/api/routes)

Purpose
-------
`GET /api/v1/agents` and `GET /api/v1/agents/{name}/status` -- read
access to the `agents.registry.AgentRegistry` `routes/tasks.py::
build_orchestrator()` constructs at startup. Section 7.19's Mission
Control "Agent Status" panel (`Vision ACTIVE`, `Planner THINKING`,
...) is this endpoint's intended consumer.

Why this reads `routes/tasks.py`'s `_store`, not its own state
------------------------------------------------------------------------
The `AgentRegistry` is a property of the one `Orchestrator` instance
`build_orchestrator()` builds -- there is exactly one, and
`routes/tasks.py::_TaskStore` already owns the reference to it. This
module intentionally does not construct or hold a second registry
reference; duplicating that reference would risk the two drifting
(e.g. a future agent added to one but not the other).
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException

from agents.registry import AgentNotRegisteredError, AgentRegistry
from api.routes.tasks import _store

router = APIRouter()

_AGENTS_UNAVAILABLE_MESSAGE = (
    "No agent registry is available yet (no simulator is running -- "
    "see routes/tasks.py::build_orchestrator, which is only called "
    "once a Simulator exists)."
)


def _require_registry() -> AgentRegistry:
    registry = _store.registry()
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail={
                "category": "agents_unavailable",
                "message": _AGENTS_UNAVAILABLE_MESSAGE,
            },
        )
    return registry


@router.get(
    "",
    summary="List every registered agent and its current state",
)
def list_agents() -> List[dict]:
    registry = _require_registry()
    return [
        {"name": name, "state": state.value}
        for name, state in registry.snapshot_states().items()
    ]


@router.get(
    "/{name}/status",
    summary="Get one agent's current state",
    responses={404: {"description": "No agent registered under this name."}},
)
def get_agent_status(name: str) -> dict:
    registry = _require_registry()
    try:
        agent = registry.get(name)
    except AgentNotRegisteredError:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "agent_not_found",
                "message": f"No agent registered under name {name!r}.",
            },
        ) from None
    return {"name": name, "state": agent.get_state().value}
