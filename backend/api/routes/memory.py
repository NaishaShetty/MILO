"""
memory.py (backend/api/routes)

Purpose
-------
Implements `GET /api/v1/memory/search` and `GET /api/v1/memory` --
Phase 8.2's first HTTP exposure of the Phase 6 memory subsystem.
`MemoryAgent` (`memory/agent.py`) already exists and is already
constructed unconditionally at startup (`app.state.memory_agent`, see
`api/app.py`) -- this module adds no new singleton, only a thin HTTP
wrapper around methods that already existed (`retrieve_relevant_
memories`) or a one-method addition to `MemoryAgent` itself
(`list_memories`, added alongside this route since it's a passthrough
in the same spirit as `MemoryManager.list()`).

Why this never 503s the way `routes/vision.py`/`routes/speech.py` do
------------------------------------------------------------------------
Unlike the simulator or Whisper, `MemoryAgent` is always constructed
(`MemoryAgent.from_config()` never raises) -- an unavailable underlying
store just makes `is_available()` False, which every `MemoryAgent`
method already degrades to an empty result for (see that module's
docstring). So this route never needs its own unavailable-handling: a
degraded memory subsystem simply returns an empty list, same as it
would for the planner's memory-retrieval call.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request

from api.models.memory import (
    MemoryListResponse,
    MemorySearchResponse,
    MemorySearchResult,
)
from memory.agent import MemoryAgent, MemoryQueryContext
from memory.models import MemoryType

router = APIRouter()


def get_memory_agent(request: Request) -> MemoryAgent:
    """FastAPI dependency returning the `MemoryAgent` built at startup.
    Never 503s -- see this module's docstring."""
    return request.app.state.memory_agent


def _parse_memory_types(types: Optional[str]) -> Optional[List[MemoryType]]:
    """Parses a comma-separated `?types=episodic,failure` query param
    into `MemoryType` members. Unknown values are dropped silently
    (never raise on a stray query param) rather than 400ing a search
    request over a typo -- an empty/absent result still just means
    "no type filter applied," not an error."""
    if not types:
        return None
    parsed = []
    for raw in types.split(","):
        raw = raw.strip()
        try:
            parsed.append(MemoryType(raw))
        except ValueError:
            continue
    return parsed or None


@router.get(
    "/search",
    summary="Search MILO's memory",
    description=(
        "Real semantic/structured memory retrieval via MemoryAgent."
        " Returns ranked MemoryResults, never a fabricated or "
        "canned response."
    ),
)
def search_memory(
    q: str = Query(..., min_length=1, description="Free-text query."),
    types: Optional[str] = Query(
        None, description="Comma-separated MemoryType filter, e.g. episodic,failure."
    ),
    top_k: int = Query(10, ge=1, le=50),
    memory_agent: MemoryAgent = Depends(get_memory_agent),
) -> MemorySearchResponse:
    context = MemoryQueryContext(goal=q)
    planner_context = memory_agent.retrieve_relevant_memories(
        context,
        memory_types=_parse_memory_types(types),
        top_k=top_k,
    )
    return MemorySearchResponse(
        query=planner_context.query,
        results=[
            MemorySearchResult(
                memory=result.memory,
                similarity=result.similarity,
                final_score=result.final_score,
                ranking_components=result.ranking_components,
            )
            for result in planner_context.results
        ],
    )


@router.get(
    "",
    summary="List MILO's stored memories",
    description=(
        "Unranked listing (newest first), optionally filtered by "
        "memory_type -- backs 'My Knowledge', 'Recent Memories', "
        "'Memory Timeline', and 'Memory At a Glance' counts."
    ),
)
def list_memory(
    memory_type: Optional[MemoryType] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    memory_agent: MemoryAgent = Depends(get_memory_agent),
) -> MemoryListResponse:
    all_memories = memory_agent.list_memories(limit=None)
    counts_by_type = {member.value: 0 for member in MemoryType}
    for memory in all_memories:
        counts_by_type[memory.memory_type.value] += 1
    filtered = (
        [m for m in all_memories if m.memory_type == memory_type]
        if memory_type is not None
        else all_memories
    )
    return MemoryListResponse(memories=filtered[:limit], counts_by_type=counts_by_type)
