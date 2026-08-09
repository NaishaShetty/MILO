"""
store.py (backend/memory)

Purpose
-------
The storage-agnostic abstraction every structured persistence backend
for `Memory` must implement, and the only interface `MemoryManager`
(`manager.py`) depends on. Nothing outside this package's own
`sqlite_store.py` is allowed to depend on SQLite-specific behavior --
`MemoryManager`, and every future Phase 6 milestone built on top of it,
imports `MemoryStore`, never `sqlite3` or `SQLiteMemoryStore` directly.
This mirrors `simulator/simulator.py`'s role for `execution/`: a small,
backend-agnostic contract that lets the concrete implementation be
swapped (a different SQL engine, a managed database) without touching
any caller.

Why an ABC rather than a `Protocol`
--------------------------------------
An `ABC` with `@abstractmethod` gives an immediate, loud
`TypeError` at construction time if a concrete store forgets to
implement a method -- a stronger guarantee than `typing.Protocol`'s
purely structural, opt-in checking, and consistent with this
project's general preference for failing loudly at the boundary
(see `models.py`'s `extra="forbid"` rationale).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Sequence

from memory.models import Memory, MemoryProvenance, MemoryStatus, MemoryType


class MemoryStore(ABC):
    """
    CRUD + filtered listing over `Memory` records. Every method
    operates on exactly one `Memory` at a time except `list()`, which
    is the sole query surface -- Phase 6.1 deliberately does not
    implement ranking/scoring here (see the phase spec section 10):
    `list()` returns matching records in a deterministic order
    (newest first), leaving *which* memories are relevant to a future
    retrieval milestone.
    """

    @abstractmethod
    def store(self, memory: Memory) -> None:
        """
        Persists a new `Memory`. Raises `memory.exceptions.
        DuplicateMemoryError` if `memory.memory_id` already exists --
        never silently overwrites.
        """

    @abstractmethod
    def get(self, memory_id: str) -> Optional[Memory]:
        """Returns the `Memory` for `memory_id`, or `None` if absent."""

    @abstractmethod
    def update(self, memory: Memory) -> None:
        """
        Overwrites the stored record for `memory.memory_id` with
        `memory`'s current field values. Raises `memory.exceptions.
        MemoryNotFoundError` if no record with that id exists --
        `update()` is never an implicit insert.
        """

    @abstractmethod
    def delete(self, memory_id: str) -> None:
        """
        Permanently removes the record for `memory_id`. Raises
        `memory.exceptions.MemoryNotFoundError` if no record with that
        id exists. Distinct from setting `MemoryStatus.ARCHIVED`
        (a normal `update()`), which retains the record -- `delete()`
        is for genuine removal.
        """

    @abstractmethod
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
        """
        Returns every stored `Memory` matching all of the given
        filters (a filter left as `None` is not applied), newest
        (`created_at`) first, capped at `limit` records if given.
        Filtering only, no ranking/scoring -- see this class's
        docstring.
        """


class VectorSearchResult:
    """
    One result from `VectorStore.search()`: the id of the matched
    record and a similarity score. Kept as its own tiny type (rather
    than a bare tuple) so a future caller reads `.memory_id`/`.score`
    instead of guessing tuple order.
    """

    __slots__ = ("memory_id", "score")

    def __init__(self, memory_id: str, score: float) -> None:
        self.memory_id = memory_id
        self.score = score

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"VectorSearchResult(memory_id={self.memory_id!r}, score={self.score!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VectorSearchResult):
            return NotImplemented
        return self.memory_id == other.memory_id and self.score == other.score


class VectorStore(ABC):
    """
    The architectural boundary for a future semantic (embedding-based)
    retrieval backend -- e.g. ChromaDB. Phase 6.1 defines this
    interface and nothing else: no concrete implementation ships yet,
    and `MemoryManager` never requires one (it is an optional
    collaborator -- see `manager.py`). ChromaDB is not currently a
    dependency of this project (`backend/requirements.txt`), so adding
    a concrete adapter now would introduce a new, unused runtime
    dependency purely on speculation; the phase spec (section 9)
    explicitly permits deferring the concrete implementation to Phase
    6.2 in exactly this situation. Keeping this interface separate
    from `MemoryStore` (rather than merging vector fields onto it)
    means the domain/application layer never becomes coupled to any
    embedding implementation, per the phase spec's architectural
    requirements.
    """

    @abstractmethod
    def upsert(
        self,
        memory_id: str,
        embedding: Sequence[float],
        metadata: Optional[dict] = None,
    ) -> None:
        """Inserts or replaces the embedding for `memory_id`."""

    @abstractmethod
    def delete(self, memory_id: str) -> None:
        """Removes the embedding for `memory_id`, if present."""

    @abstractmethod
    def search(
        self, query_embedding: Sequence[float], top_k: int = 5
    ) -> List[VectorSearchResult]:
        """
        Returns up to `top_k` nearest-neighbor matches to
        `query_embedding`, most similar first. Ranking/scoring
        semantics are owned entirely by the concrete backend -- this
        interface only fixes the call shape a future retrieval
        milestone will depend on.
        """
