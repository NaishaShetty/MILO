"""
memory.py (backend/api/models)

Purpose
-------
Request/response envelope for `GET /api/v1/memory/search` and
`GET /api/v1/memory` (Phase 8.2) -- mirrors `api/models/vision.py`'s
pattern: `memory.models.Memory` is already a Pydantic `BaseModel`, so it
is embedded directly (no hand-projection needed, unlike `vision.py`'s
`Detection` dataclass); `memory.retrieval.MemoryResult` is a plain
dataclass, so `MemorySearchResult` below is a hand-declared projection
of it, kept in sync by hand if that dataclass ever grows a field worth
exposing over HTTP -- same drift caveat `vision.py` documents for
`SpatialObject`.
"""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, ConfigDict

from memory.models import Memory


class MemorySearchResult(BaseModel):
    """One ranked result from `MemoryAgent.retrieve_relevant_memories()`."""

    model_config = ConfigDict(extra="forbid")

    memory: Memory
    similarity: float
    final_score: float
    ranking_components: Dict[str, float]


class MemorySearchResponse(BaseModel):
    """Response envelope for `GET /api/v1/memory/search`."""

    model_config = ConfigDict(extra="forbid")

    query: str
    results: List[MemorySearchResult]


class MemoryListResponse(BaseModel):
    """Response envelope for `GET /api/v1/memory`."""

    model_config = ConfigDict(extra="forbid")

    memories: List[Memory]
    counts_by_type: Dict[str, int]
