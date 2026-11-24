"""
episode_log.py (backend/learning)

`EpisodeLogger` appends every mission to a versioned SQLite file: one
`episodes` row per mission and one `steps` row per step attempt (with the
world feature snapshots before/after, retry/replan counts so far, memory-hit
statistics, executor result, reflection verdict and duration).

The Orchestrator calls it through four small hooks (`begin`, `snapshot`,
`log_attempt`, `finish`); logging never raises into the mission -- a failed
write is logged and dropped, so the flywheel can never break a task.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

from learning.features import failure_type
from learning.schema import SCHEMA_VERSION, STEP_COLUMNS, create_sql

logger = logging.getLogger(__name__)


class SchemaMismatchError(RuntimeError):
    pass


class EpisodeLogger:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(create_sql())
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO meta VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(row[0]) != SCHEMA_VERSION:
                raise SchemaMismatchError(
                    f"{self._path} has schema v{row[0]}, this code writes v{SCHEMA_VERSION}."
                )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path), timeout=30)

    # -- hooks -----------------------------------------------------------

    def begin(
        self,
        episode_id: str,
        *,
        scene_id: str = "live",
        seed: Optional[int] = None,
        task_text: str = "",
        parsed_task: Optional[Dict[str, Any]] = None,
        task_kind: str = "",
        planner: str = "",
        injected_fault: str = "none",
    ) -> None:
        self._write(
            "INSERT OR REPLACE INTO episodes (episode_id, scene_id, seed, task_text, parsed_task,"
            " task_kind, planner, injected_fault, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                episode_id,
                scene_id,
                seed,
                task_text,
                json.dumps(parsed_task or {}, default=str),
                task_kind,
                planner,
                injected_fault,
                time.time(),
            ),
        )

    def log_attempt(
        self,
        episode_id: str,
        *,
        attempt: int,
        record: Any,
        snapshots: Dict[int, Dict[str, Any]],
        retries_so_far: int,
        replans_so_far: int,
        memory_stats: Optional[Dict[str, float]] = None,
        perception_conf: float = -1.0,
        verdict: Optional[str] = None,
        model_decisions: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Writes one row per step of an `ExecutionRecord` (one plan attempt)."""
        results: List[Any] = list(record.step_results)
        mem = memory_stats or {}
        rows = []
        for index, step in enumerate(results):
            snap = snapshots.get(step.step_id, {})
            status = (
                step.status.value if hasattr(step.status, "value") else str(step.status)
            )
            labelled = status in ("completed", "failed", "blocked")
            success = status == "completed"
            code = step.error.code.value if step.error is not None else None
            message = step.error.message if step.error is not None else None
            duration = step.result.duration_ms if step.result is not None else None
            if (
                step.result is not None
                and step.result.metadata.get("simDurationMs") is not None
            ):
                duration = float(
                    step.result.metadata["simDurationMs"]
                )  # simulated time
            rows.append(
                (
                    episode_id,
                    attempt,
                    index,
                    len(results) - index - 1,
                    step.action,
                    step.target,
                    json.dumps(snap.get("before")),
                    json.dumps(snap.get("after")),
                    retries_so_far,
                    replans_so_far,
                    int(mem.get("hits", 0)),
                    float(mem.get("sim_max", 0.0)),
                    float(mem.get("sim_mean", 0.0)),
                    float(mem.get("prior_success", -1.0)),
                    perception_conf,
                    status,
                    int(success) if labelled else None,
                    code,
                    failure_type(code, message, success) if labelled else None,
                    duration,
                    verdict,
                    json.dumps(model_decisions) if model_decisions else None,
                )
            )
        marks = ",".join("?" * len(STEP_COLUMNS))
        self._write("INSERT INTO steps VALUES (" + marks + ")", rows, many=True)

    def finish(
        self,
        episode_id: str,
        *,
        outcome: str,
        replans: int,
        retries: int,
        total_steps: int,
        duration_ms: float,
    ) -> None:
        self._write(
            "UPDATE episodes SET outcome=?, replans=?, retries=?, total_steps=?, duration_ms=?"
            " WHERE episode_id=?",
            (outcome, replans, retries, total_steps, duration_ms, episode_id),
        )

    # -- plumbing ----------------------------------------------------------

    def _write(self, sql: str, params: Any, many: bool = False) -> None:
        try:
            with self._lock, closing(self._connect()) as conn:
                if many:
                    conn.executemany(sql, params)
                else:
                    conn.execute(sql, params)
                conn.commit()
        except Exception:
            logger.warning("episode_log.write_failed", exc_info=True)
