"""
traces.py (backend/api/routes)

Read-only access to the mission trace store (`tracelog`):

    GET /api/v1/traces               recent missions (newest first)
    GET /api/v1/traces/{mission_id}  one mission: summary + every record in order
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from tracelog.store import TraceStore

router = APIRouter()


def _store() -> Optional[TraceStore]:
    path = Path(os.environ.get("MILO_TRACE_DB", "data/traces.db"))
    if not path.exists():
        return None
    return TraceStore(path)


@router.get("", summary="Recent mission traces")
def list_traces(limit: int = Query(50, ge=1, le=500)) -> dict:
    store = _store()
    return {"missions": store.list(limit) if store else []}


@router.get("/{mission_id}", summary="One mission's full trace")
def get_trace(mission_id: str) -> dict:
    store = _store()
    trace = store.get(mission_id) if store else None
    if trace is None:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "not_found",
                "message": "I don't have a record of that mission.",
            },
        )
    return trace
