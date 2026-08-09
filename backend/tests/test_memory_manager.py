"""
test_memory_manager.py

Purpose
-------
Tests for `memory.manager.MemoryManager` -- Phase 6.1 spec section
12's "Memory Manager" test list: store -> retrieve -> update -> delete
and verify persistence, plus that the manager depends only on the
`MemoryStore` interface (never a concrete SQLite detail) and never
performs retrieval ranking of its own.
"""

from __future__ import annotations

from typing import Any, List, Optional

import pytest

from memory.config import MemoryConfig
from memory.exceptions import DuplicateMemoryError, MemoryNotFoundError
from memory.manager import MemoryManager
from memory.models import Memory, MemoryProvenance, MemoryStatus, MemoryType
from memory.sqlite_store import SQLiteMemoryStore
from memory.store import MemoryStore


def _make_memory(**overrides: Any) -> Memory:
    defaults: dict[str, Any] = dict(
        memory_type=MemoryType.SEMANTIC,
        content="The mug is usually in the cupboard.",
        provenance=MemoryProvenance.INFERENCE,
    )
    defaults.update(overrides)
    return Memory(**defaults)


class InMemoryStore(MemoryStore):
    """
    A minimal, dependency-free `MemoryStore` implementation used to
    prove `MemoryManager` depends only on the `MemoryStore` interface
    -- never on `SQLiteMemoryStore`/`sqlite3` directly. Mirrors
    `tests/_execution_test_helpers.py::FakeSimulator`'s role for
    `execution/`.
    """

    def __init__(self) -> None:
        self._records: dict[str, Memory] = {}

    def store(self, memory: Memory) -> None:
        if memory.memory_id in self._records:
            raise DuplicateMemoryError(memory.memory_id)
        self._records[memory.memory_id] = memory

    def get(self, memory_id: str) -> Optional[Memory]:
        return self._records.get(memory_id)

    def update(self, memory: Memory) -> None:
        if memory.memory_id not in self._records:
            raise MemoryNotFoundError(memory.memory_id)
        self._records[memory.memory_id] = memory

    def delete(self, memory_id: str) -> None:
        if memory_id not in self._records:
            raise MemoryNotFoundError(memory_id)
        del self._records[memory_id]

    def list(self, **filters) -> List[Memory]:
        return list(self._records.values())


class TestStoreRetrieveUpdateDelete:
    def test_full_lifecycle_against_sqlite_backend(self, tmp_path):
        manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "memory.db"))
        memory = _make_memory()

        stored = manager.store(memory)
        assert stored.memory_id == memory.memory_id

        fetched = manager.get(memory.memory_id)
        assert fetched == memory

        fetched.status = MemoryStatus.ARCHIVED
        updated = manager.update(fetched)
        assert updated.status == MemoryStatus.ARCHIVED
        assert manager.get(memory.memory_id).status == MemoryStatus.ARCHIVED

        manager.delete(memory.memory_id)
        assert manager.get(memory.memory_id) is None

    def test_update_bumps_updated_at(self, tmp_path):
        manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "memory.db"))
        memory = _make_memory()
        manager.store(memory)
        original_updated_at = memory.updated_at

        memory.confidence = 0.3
        manager.update(memory)

        assert manager.get(memory.memory_id).updated_at >= original_updated_at

    def test_persists_across_manager_recreation(self, tmp_path):
        db_path = tmp_path / "memory.db"
        memory = _make_memory()

        first_manager = MemoryManager(store=SQLiteMemoryStore(db_path))
        first_manager.store(memory)
        del first_manager

        second_manager = MemoryManager(store=SQLiteMemoryStore(db_path))
        assert second_manager.get(memory.memory_id) == memory

    def test_list_delegates_filters_to_the_store(self, tmp_path):
        manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "memory.db"))
        episodic = _make_memory(
            memory_type=MemoryType.EPISODIC, provenance=MemoryProvenance.EXECUTION
        )
        semantic = _make_memory(
            memory_type=MemoryType.SEMANTIC, provenance=MemoryProvenance.INFERENCE
        )
        manager.store(episodic)
        manager.store(semantic)

        results = manager.list(memory_type=MemoryType.EPISODIC)
        assert [m.memory_id for m in results] == [episodic.memory_id]


class TestDependsOnlyOnTheStoreInterface:
    def test_manager_works_against_a_non_sqlite_store(self):
        manager = MemoryManager(store=InMemoryStore())
        memory = _make_memory()

        manager.store(memory)
        assert manager.get(memory.memory_id) == memory

        memory.status = MemoryStatus.ARCHIVED
        manager.update(memory)
        assert manager.get(memory.memory_id).status == MemoryStatus.ARCHIVED

        manager.delete(memory.memory_id)
        assert manager.get(memory.memory_id) is None


class TestFailureCases:
    def test_updating_a_memory_never_stored_raises(self, tmp_path):
        manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "memory.db"))
        memory = _make_memory()
        with pytest.raises(MemoryNotFoundError):
            manager.update(memory)

    def test_deleting_a_memory_never_stored_raises(self, tmp_path):
        manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "memory.db"))
        with pytest.raises(MemoryNotFoundError):
            manager.delete("does-not-exist")

    def test_getting_a_memory_never_stored_returns_none(self, tmp_path):
        manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "memory.db"))
        assert manager.get("does-not-exist") is None


class TestFromConfig:
    def test_from_config_constructs_a_working_manager(self, tmp_path):
        config = MemoryConfig(
            enabled=True,
            database_path=tmp_path / "nested" / "memory.db",
            vector_store_path=tmp_path / "vector_store",
        )
        manager = MemoryManager.from_config(config)
        memory = _make_memory()

        manager.store(memory)
        assert manager.get(memory.memory_id) == memory
        assert (tmp_path / "nested" / "memory.db").exists()
