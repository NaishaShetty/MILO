"""
manager.py (backend/memory)

Purpose
-------
`MemoryManager` -- the single application-facing entry point for
Phase 6.1's memory foundation. It coordinates a `MemoryStore`
(required -- structured persistence, `sqlite_store.py`) and an
optional `VectorStore` (`store.py`; no concrete implementation exists
yet, see that module's docstring), and exposes the plain
store/get/update/delete/list API the phase spec calls for. This is
deliberately the *only* moving part a future Phase 6 milestone (Memory
Agent, Planner integration, retrieval) needs to import from this
package -- `MemoryStore`/`SQLiteMemoryStore`/`VectorStore` are
implementation details `MemoryManager` owns, not a second API surface
callers are expected to reach around it for.

What this class deliberately does NOT do
--------------------------------------------
Per the phase spec section 10, this class contains no planner logic,
no navigation/simulator logic, no LLM reasoning, no reflection, no
memory summarization, and no retrieval ranking/scoring -- `list()`
is a thin passthrough to `MemoryStore.list()`'s filter-only query
surface. Every one of those behaviors belongs to a dedicated future
milestone built *on top of* this manager, not inside it.
"""

from __future__ import annotations

import time
from typing import List, Optional

from memory.config import MemoryConfig
from memory.models import Memory, MemoryProvenance, MemoryStatus, MemoryType
from memory.sqlite_store import SQLiteMemoryStore
from memory.store import MemoryStore, VectorStore


class MemoryManager:
    """
    Coordinates structured (and, in the future, vector) persistence for
    `Memory` records. See this module's docstring for scope.
    """

    def __init__(
        self, store: MemoryStore, vector_store: Optional[VectorStore] = None
    ) -> None:
        self._store = store
        self._vector_store = vector_store

    @classmethod
    def from_config(cls, config: MemoryConfig) -> "MemoryManager":
        """
        Production entry point: `MemoryManager.from_config(MemoryConfig.
        from_env())`. Constructs a `SQLiteMemoryStore` at `config.
        database_path`; `vector_store` stays unset (`None`) since no
        concrete `VectorStore` implementation exists as of Phase 6.1
        (see `store.py`'s docstring) -- a Phase 6.2 caller is expected
        to pass one into `MemoryManager.__init__` directly once one
        exists, rather than this factory guessing at its construction.
        """
        return cls(store=SQLiteMemoryStore(config.database_path))

    def store(self, memory: Memory) -> Memory:
        """Persists `memory` (via the structured store) and returns it."""
        self._store.store(memory)
        return memory

    def get(self, memory_id: str) -> Optional[Memory]:
        """Returns the `Memory` for `memory_id`, or `None` if absent."""
        return self._store.get(memory_id)

    def update(self, memory: Memory) -> Memory:
        """
        Persists `memory`'s current field values over the existing
        record for `memory.memory_id`, refreshing `updated_at` to now
        first -- the one piece of bookkeeping this manager applies on
        every update, since a plain field assignment on a `Memory`
        instance has no way to know an update is happening (see
        `models.Memory.updated_at`'s docstring). Raises `memory.
        exceptions.MemoryNotFoundError` if no such record exists.
        """
        memory.updated_at = time.time()
        self._store.update(memory)
        return memory

    def delete(self, memory_id: str) -> None:
        """
        Permanently removes the record for `memory_id` from the
        structured store, and from the vector store too if one is
        configured. Raises `memory.exceptions.MemoryNotFoundError` if
        no such record exists in the structured store.
        """
        self._store.delete(memory_id)
        if self._vector_store is not None:
            self._vector_store.delete(memory_id)

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
        """Thin passthrough to `MemoryStore.list()` -- see its docstring."""
        return self._store.list(
            memory_type=memory_type,
            status=status,
            provenance=provenance,
            episode_id=episode_id,
            task_id=task_id,
            limit=limit,
        )
