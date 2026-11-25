"""
scene_map.py (backend/api/routes)

    GET /api/v1/scene/map   a top-down view: where MILO is and has been (this mission's
                            trace), where objects really are (simulator positions, when
                            the simulator gives them), and where MILO's memory believes
                            things are -- with last-seen time, confidence and source.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request

from api.routes.tasks import _store, get_simulator
from simulator.simulator import Simulator

router = APIRouter()
_LOCATION = (
    "located_on",
    "stored_in",
    "observed_on",
    "observed_in",
    "usually_on",
    "typically_stored_in",
)


def _beliefs(memory_agent: Any) -> List[Dict[str, Any]]:
    if memory_agent is None:
        return []
    from memory.models import MemoryStatus
    from memory.trust import effective_confidence, source_of

    out = []
    now = time.time()
    for m in memory_agent.list_memories(limit=None):
        meta = m.metadata or {}
        if m.status != MemoryStatus.ACTIVE or meta.get("predicate") not in _LOCATION:
            continue
        seen = meta.get("observed_at") or m.observed_at or m.created_at
        out.append({
            "object": str(meta.get("subject", "")).replace("_", " "),
            "place": str(meta.get("object", "")).replace("_", " "),
            "relation": meta.get("predicate"),
            "confidence": round(effective_confidence(m, now), 3),
            "last_seen": seen,
            "source": source_of(m),
        })  # fmt: skip
    out.sort(key=lambda b: -b["confidence"])
    return out


def _path() -> List[Dict[str, Any]]:
    """MILO's poses during the current (or last) mission, from the trace store."""
    from tracelog.store import TraceStore

    state = _store._orchestrator._current_state if _store._orchestrator else None
    path = Path(os.environ.get("MILO_TRACE_DB", "data/traces.db"))
    if state is None or not path.exists():
        return []
    trace = TraceStore(path).get(state.task_id) or {"records": []}
    return [
        r["data"]["pose"]
        for r in trace["records"]
        if r["kind"] == "step" and r["data"].get("pose")
    ]


@router.get("/map", summary="Top-down scene map with MILO's path and memory beliefs")
def scene_map(request: Request, simulator: Simulator = Depends(get_simulator)) -> dict:
    try:
        meta = simulator.get_metadata() or {}
    except Exception:
        meta = {}
    objects = []
    for o in meta.get("objects") or []:
        pos = o.get("position") or {}
        objects.append({
            "id": o.get("objectId"),
            "type": str(o.get("objectType", "")).lower(),
            "x": pos.get("x"),
            "z": pos.get("z"),
            "visible": bool(o.get("visible")),
            "in": [str(p).split("|")[0].lower() for p in (o.get("parentReceptacles") or [])],
        })  # fmt: skip
    agent = (meta.get("agent") or {}).get("position") or {}
    return {
        "agent": {"x": agent.get("x"), "z": agent.get("z")} if agent else None,
        "path": _path(),
        "objects": objects,
        "beliefs": _beliefs(getattr(request.app.state, "memory_agent", None)),
        "has_positions": any(o["x"] is not None for o in objects),
    }
