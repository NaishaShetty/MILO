"""
store.py (backend/tracelog)

One SQLite store of everything a mission did, so replay, observability, the benchmark
and the demo all read the same thing. Versioned schema (`SCHEMA_VERSION`); a database
written with another version is refused rather than silently mixed.

    missions(mission_id, task_text, parsed_task, planner, started_at, ended_at,
             outcome, reason, latencies, verification, schema_version)
    records(mission_id, seq, ts, kind, step_id, data)

Record kinds (`KINDS`): mission_started, memory, plan, step, thought, reflection,
replan, model_decision, verification, mission_finished. `data` is JSON.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
KINDS = (
    "mission_started",
    "memory",
    "plan",
    "step",
    "thought",
    "reflection",
    "replan",
    "model_decision",
    "verification",
    "mission_finished",
)

_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS missions (
    mission_id TEXT PRIMARY KEY,
    task_text TEXT,
    parsed_task TEXT,
    planner TEXT,
    started_at REAL,
    ended_at REAL,
    outcome TEXT,
    reason TEXT,
    latencies TEXT,
    verification TEXT,
    schema_version INTEGER
);
CREATE TABLE IF NOT EXISTS records (
    mission_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    step_id INTEGER,
    data TEXT,
    PRIMARY KEY (mission_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_missions_started ON missions(started_at);
"""


class SchemaMismatch(RuntimeError):
    pass


class TraceStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seq: Dict[str, int] = {}
        with closing(self._connect()) as db, db:
            db.executescript(_SQL)
            row = db.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO meta VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(row[0]) != SCHEMA_VERSION:
                raise SchemaMismatch(
                    f"{self.path} has trace schema {row[0]}, expected {SCHEMA_VERSION}"
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0)

    # -- writing ---------------------------------------------------------------

    def begin(self, mission_id: str, **fields: Any) -> None:
        with self._lock, closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO missions (mission_id, task_text, parsed_task, "
                "planner, started_at, schema_version) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    fields.get("task_text"),
                    json.dumps(fields.get("parsed_task")),
                    fields.get("planner"),
                    fields.get("started_at", time.time()),
                    SCHEMA_VERSION,
                ),
            )
            self._seq[mission_id] = 0

    def add(
        self,
        mission_id: str,
        kind: str,
        data: Dict[str, Any],
        *,
        step_id: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown trace record kind {kind!r}")
        with self._lock, closing(self._connect()) as db, db:
            seq = self._seq.get(mission_id)
            if seq is None:
                row = db.execute(
                    "SELECT COALESCE(MAX(seq) + 1, 0) FROM records WHERE mission_id=?",
                    (mission_id,),
                ).fetchone()
                seq = int(row[0])
            db.execute(
                "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    seq,
                    ts or time.time(),
                    kind,
                    step_id,
                    json.dumps(data, default=str),
                ),
            )
            self._seq[mission_id] = seq + 1

    def finish(self, mission_id: str, outcome: str, **fields: Any) -> None:
        with self._lock, closing(self._connect()) as db, db:
            db.execute(
                "UPDATE missions SET ended_at=?, outcome=?, reason=?, latencies=?, "
                "verification=? WHERE mission_id=?",
                (
                    time.time(),
                    outcome,
                    fields.get("reason"),
                    json.dumps(fields.get("latencies") or {}),
                    json.dumps(fields.get("verification") or []),
                    mission_id,
                ),
            )
            self._seq.pop(mission_id, None)

    # -- reading ------------------------------------------------------------------

    def get(self, mission_id: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT * FROM missions WHERE mission_id=?", (mission_id,)
            ).fetchone()
            if row is None:
                return None
            records = db.execute(
                "SELECT seq, ts, kind, step_id, data FROM records "
                "WHERE mission_id=? ORDER BY seq",
                (mission_id,),
            ).fetchall()
        mission = dict(row)
        for key in ("parsed_task", "latencies", "verification"):
            mission[key] = json.loads(mission[key]) if mission[key] else None
        return {
            "mission": mission,
            "records": [
                {
                    "seq": r["seq"],
                    "ts": r["ts"],
                    "kind": r["kind"],
                    "step_id": r["step_id"],
                    "data": json.loads(r["data"] or "{}"),
                }
                for r in records
            ],
        }

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT mission_id, task_text, planner, started_at, ended_at, outcome "
                "FROM missions ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
