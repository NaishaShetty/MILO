"""
benchmark.py (backend/api/routes)

    GET /api/v1/benchmark    the latest benchmark report (per planner, fault recovery,
                             ablations) and the history of past runs, for the Leaderboard.

Reads `benchmarks/latest.json` and `benchmarks/history.jsonl` written by
`python -m benchmark.run`; never runs the benchmark itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter

router = APIRouter()
DIR = Path(__file__).resolve().parents[3] / "benchmarks"


@router.get("", summary="Latest benchmark results and their history")
def get_benchmark() -> Dict[str, Any]:
    latest = None
    path = DIR / "latest.json"
    if path.exists():
        data = json.loads(path.read_text())
        latest = {k: v for k, v in data.items() if k != "by_case"}
    history: List[Dict[str, Any]] = []
    hist = DIR / "history.jsonl"
    if hist.exists():
        for line in hist.read_text().splitlines()[-100:]:
            try:
                history.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"latest": latest, "history": history}
