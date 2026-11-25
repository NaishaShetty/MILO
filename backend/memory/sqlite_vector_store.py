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

In-memory index (loaded once, kept in sync)
-----------------------------------------------
`search()` used to `SELECT` every vector out of SQLite and rebuild the
whole numpy matrix on *every* retrieval -- O(N) disk reads, row
decoding and normalisation per query. The vectors are now loaded once,
lazily, into a pre-normalised `(N, D)` float32 matrix; `upsert()`/
`upsert_many()`/`delete()` write through to SQLite (still the durable
source of truth) *and* update that matrix in place, so a search is a
single matrix-vector product with no database access at all. Deletes
swap the last row into the hole, appends double capacity as needed, and
ties are broken by `memory_id` (explicitly, since row order is no
longer sorted), so results stay deterministic. A lock guards the index
because the API serves requests from worker threads.

Why brute-force, not an approximate-nearest-neighbor index
------------------------------------------------------------------
This is a research prototype's memory store, not a production-scale
vector database. Brute-force cosine similarity over a resident `numpy`
matrix is exact (no recall loss from an ANN index), trivially
deterministic (a hard requirement -- see `retrieval.py`), and fast at
this scale (5,000 vectors x 512 dims is one ~10 MB matrix-vector
product, well under a millisecond or two). If dataset size ever makes
brute-force too slow, swapping the implementation behind `VectorStore`
is the intended escape hatch -- no caller changes.

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
still explicitly normalizes both the stored and query vectors, rather
than assuming every caller obeys that contract, so `search()` is
correct even against a future `Embedder` implementation that does not
normalize.

One process, one index
-------------------------
The in-memory index assumes this instance is the only writer to the
database file while it is alive (the API process owns it). A second
`SQLiteVectorStore` opened on the same file after this one has loaded
will not be reflected until this instance is recreated.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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

_INITIAL_CAPACITY = 256


class SQLiteVectorStore(VectorStore):
    """`VectorStore` backed by SQLite (durable) + an in-memory numpy index (search)."""

    def __init__(self, database_path: Path, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError(f"dimension must be positive, got {dimension}")
        self._database_path = Path(database_path)
        self._dimension = dimension
        self._lock = threading.RLock()
        # In-memory index -- see this module's docstring. `_matrix[:count]`
        # holds unit-norm rows (all-zero stays zero); `_ids[i]` names row i.
        self._loaded = False
        self._ids: List[str] = []
        self._row_of: Dict[str, int] = {}
        self._matrix = np.zeros((_INITIAL_CAPACITY, dimension), dtype=np.float32)
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

    # -- in-memory index ---------------------------------------------

    @property
    def size(self) -> int:
        """Number of vectors currently indexed (loads the index if needed)."""
        with self._lock:
            self._ensure_loaded()
            return len(self._ids)

    def _ensure_loaded(self) -> None:
        """Loads every vector from SQLite into the index, once."""
        if self._loaded:
            return
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT memory_id, embedding FROM vectors").fetchall()
        self._ids = []
        self._row_of = {}
        capacity = max(_INITIAL_CAPACITY, len(rows))
        self._matrix = np.zeros((capacity, self._dimension), dtype=np.float32)
        for row in rows:
            vector = np.frombuffer(row["embedding"], dtype=np.float32)
            if vector.shape != (self._dimension,):
                continue  # stale row from a different embedding dimension
            self._set_row(row["memory_id"], vector)
        self._loaded = True

    @staticmethod
    def _unit(vector: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(vector))
        # A degenerate all-zero vector stays zero: similarity 0 with
        # everything rather than NaN.
        return vector / norm if norm > 0.0 else vector.astype(np.float32)

    def _set_row(self, memory_id: str, vector: np.ndarray) -> None:
        unit = self._unit(np.asarray(vector, dtype=np.float32))
        row = self._row_of.get(memory_id)
        if row is None:
            row = len(self._ids)
            if row >= self._matrix.shape[0]:
                grown = np.zeros(
                    (self._matrix.shape[0] * 2, self._dimension), dtype=np.float32
                )
                grown[:row] = self._matrix[:row]
                self._matrix = grown
            self._ids.append(memory_id)
            self._row_of[memory_id] = row
        self._matrix[row] = unit

    def _remove_row(self, memory_id: str) -> None:
        row = self._row_of.pop(memory_id, None)
        if row is None:
            return
        last = len(self._ids) - 1
        if row != last:
            last_id = self._ids[last]
            self._matrix[row] = self._matrix[last]
            self._ids[row] = last_id
            self._row_of[last_id] = row
        self._ids.pop()
        self._matrix[last] = 0.0

    # -- VectorStore API -----------------------------------------------

    def _checked(self, memory_id: str, embedding: Sequence[float]) -> np.ndarray:
        vector = np.asarray(embedding, dtype=np.float32)
        if vector.shape != (self._dimension,):
            raise ValueError(
                f"embedding for memory_id={memory_id!r} has shape {vector.shape}, "
                f"expected ({self._dimension},)"
            )
        return vector

    def upsert(
        self,
        memory_id: str,
        embedding: Sequence[float],
        metadata: Optional[dict] = None,
    ) -> None:
        self.upsert_many([(memory_id, embedding, metadata)])

    def upsert_many(
        self,
        items: Iterable[Tuple[str, Sequence[float], Optional[dict]]],
    ) -> None:
        """Batched `upsert()`: one SQLite transaction for the whole batch."""
        prepared = [(mid, self._checked(mid, emb)) for mid, emb, _meta in items]
        if not prepared:
            return
        with self._lock:
            with closing(self._connect()) as conn:
                try:
                    conn.executemany(
                        """
                        INSERT INTO vectors (memory_id, embedding, dimension)
                        VALUES (?, ?, ?)
                        ON CONFLICT(memory_id) DO UPDATE SET
                            embedding = excluded.embedding,
                            dimension = excluded.dimension
                        """,
                        [
                            (mid, vec.tobytes(), self._dimension)
                            for mid, vec in prepared
                        ],
                    )
                    conn.commit()
                except sqlite3.Error as exc:
                    conn.rollback()
                    raise MemoryStoreError(
                        f"Failed to upsert {len(prepared)} embedding(s): {exc}"
                    ) from exc
            # Only touch the index once SQLite has accepted the write, so
            # the two never disagree after a failure.
            if self._loaded:
                for memory_id, vector in prepared:
                    self._set_row(memory_id, vector)

    def delete(self, memory_id: str) -> None:
        with self._lock:
            with closing(self._connect()) as conn:
                conn.execute("DELETE FROM vectors WHERE memory_id = ?", (memory_id,))
                conn.commit()
            if self._loaded:
                self._remove_row(memory_id)

    def search(
        self, query_embedding: Sequence[float], top_k: int = 5
    ) -> List[VectorSearchResult]:
        query = np.asarray(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0.0 or top_k <= 0:
            return []
        query = query / query_norm

        with self._lock:
            self._ensure_loaded()
            count = len(self._ids)
            if count == 0:
                return []
            similarities = self._matrix[:count] @ query
            k = min(top_k, count)
            if k < count:
                # Partial selection, then include everything tied with the
                # k-th score so the memory_id tie-break below is exact.
                boundary = np.partition(similarities, count - k)[count - k]
                candidates = np.nonzero(similarities >= boundary)[0]
            else:
                candidates = np.arange(count)
            ranked = sorted(
                candidates.tolist(),
                key=lambda i: (-float(similarities[i]), self._ids[i]),
            )[:k]
            return [
                VectorSearchResult(memory_id=self._ids[i], score=float(similarities[i]))
                for i in ranked
            ]
