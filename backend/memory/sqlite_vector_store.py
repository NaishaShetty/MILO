"""
sqlite_vector_store.py (backend/memory)

Purpose
-------
The Phase 6.2 concrete `VectorStore` (`memory.store.VectorStore`,
defined but deliberately left unimplemented in Phase 6.1). Persists
embeddings as BLOBs in a SQLite table and answers `search()` with
brute-force cosine similarity via `numpy` -- both already project
dependencies (`numpy` for Vision, `sqlite3` stdlib, reused from
`sqlite_store.py`), so this adds no new third-party dependency, exactly
like every other Phase 6.1/6.2 module.

Why brute-force, not an approximate-nearest-neighbor index
------------------------------------------------------------------
This is a research prototype's memory store, not a production-scale
vector database -- the phase spec's own evaluation dataset (section
20) is a handful of memories. Brute-force cosine similarity over
`numpy` arrays is exact (no recall loss from an ANN index),
trivially deterministic (a hard requirement -- see `retrieval.py`),
and fast enough at this scale (a few hundred to a few thousand
vectors) that adding FAISS/HNSW/a real vector database now would be
optimizing a problem this project does not have yet. If dataset size
ever makes brute-force too slow, swapping the implementation behind
`VectorStore` is the intended escape hatch -- no caller changes.

Why a separate table from `sqlite_store.py`'s `memories` table, not a
BLOB column added there
---------------------------------------------------------------------
Per the phase spec's "maintain separation between domain model,
embedding model, and vector database" -- `SQLiteMemoryStore` and
`SQLiteVectorStore` both happen to use SQLite as their file format, but
they are two independent stores behind two independent interfaces
(`MemoryStore`/`VectorStore`). Nothing prevents a deployment from
pointing them at two different database files (as `MemoryConfig.
vector_store_path` already anticipated in Phase 6.1); this
implementation just also supports pointing them at the same file
without the tables colliding, since they are namespaced separately.

Why cosine similarity, not raw dot product or Euclidean distance
------------------------------------------------------------------------
`Embedder.embed()` implementations are documented to return unit-norm
vectors (`embeddings.py`), so cosine similarity and dot product
coincide for any two vectors both stores/queries produce -- this class
still explicitly normalizes both the stored and query vectors before
computing a dot product, rather than assuming every caller obeys that
contract, so `search()` is correct even against a future `Embedder`
implementation that does not normalize.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np

from memory.exceptions import MemoryStoreError
from memory.store import VectorSearchResult, VectorStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
    memory_id TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    dimension INTEGER NOT NULL
);
"""


class SQLiteVectorStore(VectorStore):
    """`VectorStore` implementation backed by SQLite + brute-force numpy cosine search."""

    def __init__(self, database_path: Path, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError(f"dimension must be positive, got {dimension}")
        self._database_path = Path(database_path)
        self._dimension = dimension
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
        except (OSError, sqlite3.Error) as exc:
            raise MemoryStoreError(
                f"Failed to initialize vector database at {self._database_path}: {exc}"
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._database_path))
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(
        self,
        memory_id: str,
        embedding: Sequence[float],
        metadata: Optional[dict] = None,
    ) -> None:
        vector = np.asarray(embedding, dtype=np.float32)
        if vector.shape != (self._dimension,):
            raise ValueError(
                f"embedding for memory_id={memory_id!r} has shape {vector.shape}, "
                f"expected ({self._dimension},)"
            )
        with closing(self._connect()) as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO vectors (memory_id, embedding, dimension)
                    VALUES (:memory_id, :embedding, :dimension)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        embedding = excluded.embedding,
                        dimension = excluded.dimension
                    """,
                    {
                        "memory_id": memory_id,
                        "embedding": vector.tobytes(),
                        "dimension": self._dimension,
                    },
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise MemoryStoreError(
                    f"Failed to upsert embedding for memory_id={memory_id!r}: {exc}"
                ) from exc

    def delete(self, memory_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM vectors WHERE memory_id = ?", (memory_id,))
            conn.commit()

    def search(
        self, query_embedding: Sequence[float], top_k: int = 5
    ) -> List[VectorSearchResult]:
        query = np.asarray(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0.0:
            return []
        query = query / query_norm

        with closing(self._connect()) as conn:
            # Ordered by memory_id so tie-breaking in the argsort below
            # (equal similarity scores) is deterministic regardless of
            # SQLite's unspecified default row order.
            rows = conn.execute(
                "SELECT memory_id, embedding FROM vectors ORDER BY memory_id"
            ).fetchall()

        if not rows:
            return []

        memory_ids = [row["memory_id"] for row in rows]
        matrix = np.stack(
            [np.frombuffer(row["embedding"], dtype=np.float32) for row in rows]
        )
        norms = np.linalg.norm(matrix, axis=1)
        # Avoid dividing by zero for a (degenerate) all-zero stored
        # vector -- treat it as similarity 0 with everything rather
        # than producing NaN.
        safe_norms = np.where(norms == 0.0, 1.0, norms)
        normalized = matrix / safe_norms[:, np.newaxis]
        similarities = normalized @ query
        similarities = np.where(norms == 0.0, 0.0, similarities)

        order = np.argsort(-similarities, kind="stable")[:top_k]
        return [
            VectorSearchResult(memory_id=memory_ids[i], score=float(similarities[i]))
            for i in order
        ]
