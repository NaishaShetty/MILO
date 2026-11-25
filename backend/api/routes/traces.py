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

from fastapi import APIRouter, HTTPException, Query, Response

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


@router.get("/stats", summary="p50 / p95 per stage and per action over recent missions")
def trace_stats(limit: int = Query(200, ge=1, le=2000)) -> dict:
    from tracelog.stats import stage_stats

    store = _store()
    return (
        stage_stats(store, limit)
        if store
        else {"missions": 0, "stages": {}, "actions": {}}
    )


@router.get("/{mission_id}/waterfall", summary="One mission as time bars")
def trace_waterfall(mission_id: str) -> dict:
    from tracelog.stats import waterfall

    store = _store()
    trace = store.get(mission_id) if store else None
    if trace is None:
        raise _missing()
    return {"mission_id": mission_id, "bars": waterfall(trace)}


@router.get("/{mission_id}/report", summary="A one-page Markdown run report")
def trace_report(mission_id: str) -> Response:
    from tracelog.stats import report

    store = _store()
    trace = store.get(mission_id) if store else None
    if trace is None:
        raise _missing()
    return Response(
        report(trace),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="milo-run-{mission_id[:8]}.md"'
        },
    )


def _missing() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "category": "not_found",
            "message": "I don't have a record of that mission.",
        },
    )


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
