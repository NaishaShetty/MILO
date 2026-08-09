"""
sqlite_store.py (backend/memory)

Purpose
-------
The Phase 6.1 authoritative structured persistence layer: a
`MemoryStore` (`store.py`) implementation backed by SQLite (Python's
stdlib `sqlite3` -- no new project dependency). This is the only module
in `backend/memory/` that imports `sqlite3` or knows SQL exists --
every other module (`manager.py`, and every future Phase 6 milestone)
depends on `store.MemoryStore`, never this module directly, so this
class could be swapped for a different backend without any caller
change.

Why one connection per operation, not a long-lived connection
------------------------------------------------------------------
Matching `evaluation/result_store.py`'s "no state cached across calls"
simplicity and this project's general preference for boring,
predictable I/O over connection-pooling machinery this research
platform does not need: each method opens a short-lived `sqlite3`
connection, does its work inside an explicit transaction, and closes
it. This also happens to be exactly what makes "persistence across
process/database reopen" trivially true and testable -- there is no
process-lifetime cache to accidentally mask a persistence bug.

Schema
------
A single `memories` table holds every field needed to reconstruct a
`Memory` exactly (per the phase spec's "avoid storing critical
structured information only inside opaque serialized blobs"):
`memory_id`, `memory_type`, `content`, `provenance`, `status`,
`confidence`, `created_at`, `observed_at`, `updated_at`, `episode_id`,
`task_id` are all first-class, typed, indexable columns; only
`metadata` (genuinely open-ended, type-specific auxiliary data -- see
`models.py`'s docstring) is stored as a serialized JSON blob. Indexes
are declared on every column `MemoryStore.list()` can filter by.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.exceptions import (
    DuplicateMemoryError,
    MemoryNotFoundError,
    MemoryStoreError,
)
from memory.models import Memory, MemoryProvenance, MemoryStatus, MemoryType
from memory.store import MemoryStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id   TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    content     TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    status      TEXT NOT NULL,
    confidence  REAL NOT NULL,
    created_at  REAL NOT NULL,
    observed_at REAL,
    updated_at  REAL NOT NULL,
    episode_id  TEXT,
    task_id     TEXT,
    metadata    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_provenance ON memories(provenance);
CREATE INDEX IF NOT EXISTS idx_memories_episode_id ON memories(episode_id);
CREATE INDEX IF NOT EXISTS idx_memories_task_id ON memories(task_id);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);
"""


def _memory_to_row(memory: Memory) -> Dict[str, Any]:
    return {
        "memory_id": memory.memory_id,
        "memory_type": memory.memory_type.value,
        "content": memory.content,
        "provenance": memory.provenance.value,
        "status": memory.status.value,
        "confidence": memory.confidence,
        "created_at": memory.created_at,
        "observed_at": memory.observed_at,
        "updated_at": memory.updated_at,
        "episode_id": memory.episode_id,
        "task_id": memory.task_id,
        "metadata": json.dumps(memory.metadata, sort_keys=True),
    }


def _row_to_memory(row: sqlite3.Row) -> Memory:
    try:
        metadata = json.loads(row["metadata"])
    except (TypeError, ValueError) as exc:
        raise MemoryStoreError(
            f"Corrupted metadata JSON for memory_id={row['memory_id']!r}: {exc}"
        ) from exc
    try:
        return Memory(
            memory_id=row["memory_id"],
            memory_type=MemoryType(row["memory_type"]),
            content=row["content"],
            provenance=MemoryProvenance(row["provenance"]),
            status=MemoryStatus(row["status"]),
            confidence=row["confidence"],
            created_at=row["created_at"],
            observed_at=row["observed_at"],
            updated_at=row["updated_at"],
            episode_id=row["episode_id"],
            task_id=row["task_id"],
            metadata=metadata,
        )
    except ValueError as exc:
        # Covers both an invalid MemoryType/MemoryProvenance/MemoryStatus
        # value and a Memory pydantic ValidationError (e.g. confidence
        # out of range) -- either way, this is an on-disk record that
        # cannot be reconstructed, i.e. a corrupted/incompatible row.
        raise MemoryStoreError(
            f"Corrupted record for memory_id={row['memory_id']!r}: {exc}"
        ) from exc


class SQLiteMemoryStore(MemoryStore):
    """
    `MemoryStore` implementation backed by a SQLite database file. See
    this module's docstring for the schema and connection strategy.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
        except (OSError, sqlite3.Error) as exc:
            raise MemoryStoreError(
                f"Failed to initialize memory database at {self._database_path}: {exc}"
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        # A fresh connection per call (see this module's docstring) --
        # `closing()` (not `with conn:`, which commits/rolls back but
        # never closes) guarantees the connection is always released,
        # success or failure.
        conn = sqlite3.connect(str(self._database_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def store(self, memory: Memory) -> None:
        row = _memory_to_row(memory)
        with closing(self._connect()) as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO memories (
                        memory_id, memory_type, content, provenance, status,
                        confidence, created_at, observed_at, updated_at,
                        episode_id, task_id, metadata
                    ) VALUES (
                        :memory_id, :memory_type, :content, :provenance, :status,
                        :confidence, :created_at, :observed_at, :updated_at,
                        :episode_id, :task_id, :metadata
                    )
                    """,
                    row,
                )
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise DuplicateMemoryError(
                    f"A memory with memory_id={memory.memory_id!r} already exists."
                ) from exc
            except sqlite3.Error as exc:
                conn.rollback()
                raise MemoryStoreError(f"Failed to store memory: {exc}") from exc
            else:
                conn.commit()

    def get(self, memory_id: str) -> Optional[Memory]:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_memory(row)

    def update(self, memory: Memory) -> None:
        row = _memory_to_row(memory)
        with closing(self._connect()) as conn:
            try:
                cursor = conn.execute(
                    """
                    UPDATE memories SET
                        memory_type = :memory_type,
                        content = :content,
                        provenance = :provenance,
                        status = :status,
                        confidence = :confidence,
                        created_at = :created_at,
                        observed_at = :observed_at,
                        updated_at = :updated_at,
                        episode_id = :episode_id,
                        task_id = :task_id,
                        metadata = :metadata
                    WHERE memory_id = :memory_id
                    """,
                    row,
                )
            except sqlite3.Error as exc:
                conn.rollback()
                raise MemoryStoreError(f"Failed to update memory: {exc}") from exc
            if cursor.rowcount == 0:
                conn.rollback()
                raise MemoryNotFoundError(
                    f"No memory found with memory_id={memory.memory_id!r}."
                )
            conn.commit()

    def delete(self, memory_id: str) -> None:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM memories WHERE memory_id = ?", (memory_id,)
            )
            if cursor.rowcount == 0:
                conn.rollback()
                raise MemoryNotFoundError(
                    f"No memory found with memory_id={memory_id!r}."
                )
            conn.commit()

    def list(
        self,
        *,
        memory_type: Optional[MemoryType] = None,
        status: Optional[MemoryStatus] = None,
        provenance: Optional[MemoryProvenance] = None,
        episode_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Memory]:
        clauses = []
        params: Dict[str, Any] = {}
        if memory_type is not None:
            clauses.append("memory_type = :memory_type")
            params["memory_type"] = memory_type.value
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status.value
        if provenance is not None:
            clauses.append("provenance = :provenance")
            params["provenance"] = provenance.value
        if episode_id is not None:
            clauses.append("episode_id = :episode_id")
            params["episode_id"] = episode_id
        if task_id is not None:
            clauses.append("task_id = :task_id")
            params["task_id"] = task_id

        query = "SELECT * FROM memories"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = limit

        with closing(self._connect()) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
        return [_row_to_memory(row) for row in rows]
