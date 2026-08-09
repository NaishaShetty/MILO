"""
test_memory_sqlite_store.py

Purpose
-------
Unit + integration tests for `memory.sqlite_store.SQLiteMemoryStore` --
Phase 6.1 spec section 12's "SQLite" test list: create, read, update,
delete, persistence across process/database reopen, multiple memory
types, metadata persistence, filtering, and failure cases (duplicate
ids, missing memory, corrupted records, transaction rollback,
initialization failure).
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from memory.exceptions import (
    DuplicateMemoryError,
    MemoryNotFoundError,
    MemoryStoreError,
)
from memory.models import Memory, MemoryProvenance, MemoryStatus, MemoryType
from memory.sqlite_store import SQLiteMemoryStore


def _make_memory(**overrides: Any) -> Memory:
    defaults: dict[str, Any] = dict(
        memory_type=MemoryType.EPISODIC,
        content="Picked up the apple.",
        provenance=MemoryProvenance.EXECUTION,
    )
    defaults.update(overrides)
    return Memory(**defaults)


class TestCreateReadUpdateDelete:
    def test_store_then_get_round_trips_exactly(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        memory = _make_memory(metadata={"object_id": "Apple|1"})
        store.store(memory)

        fetched = store.get(memory.memory_id)
        assert fetched == memory

    def test_get_missing_memory_returns_none(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        assert store.get("does-not-exist") is None

    def test_update_persists_new_field_values(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        memory = _make_memory()
        store.store(memory)

        memory.status = MemoryStatus.ARCHIVED
        memory.confidence = 0.2
        store.update(memory)

        fetched = store.get(memory.memory_id)
        assert fetched.status == MemoryStatus.ARCHIVED
        assert fetched.confidence == 0.2

    def test_delete_removes_the_record(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        memory = _make_memory()
        store.store(memory)

        store.delete(memory.memory_id)

        assert store.get(memory.memory_id) is None


class TestPersistenceAcrossReopen:
    def test_memory_survives_reopening_the_store(self, tmp_path):
        db_path = tmp_path / "memory.db"
        memory = _make_memory(content="Survives a reopen.")

        first = SQLiteMemoryStore(db_path)
        first.store(memory)
        del first

        second = SQLiteMemoryStore(db_path)
        fetched = second.get(memory.memory_id)
        assert fetched == memory

    def test_update_survives_reopening_the_store(self, tmp_path):
        db_path = tmp_path / "memory.db"
        memory = _make_memory()

        first = SQLiteMemoryStore(db_path)
        first.store(memory)
        memory.status = MemoryStatus.ARCHIVED
        first.update(memory)
        del first

        second = SQLiteMemoryStore(db_path)
        assert second.get(memory.memory_id).status == MemoryStatus.ARCHIVED

    def test_delete_survives_reopening_the_store(self, tmp_path):
        db_path = tmp_path / "memory.db"
        memory = _make_memory()

        first = SQLiteMemoryStore(db_path)
        first.store(memory)
        first.delete(memory.memory_id)
        del first

        second = SQLiteMemoryStore(db_path)
        assert second.get(memory.memory_id) is None


class TestMultipleMemoryTypesAndMetadata:
    def test_all_memory_types_persist_and_round_trip(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        memories = [
            _make_memory(memory_type=memory_type, content=f"content-{memory_type}")
            for memory_type in MemoryType
        ]
        for memory in memories:
            store.store(memory)

        for memory in memories:
            assert store.get(memory.memory_id) == memory

    def test_nested_metadata_persists_exactly(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        metadata = {
            "detections": [{"label": "apple", "confidence": 0.87}],
            "nested": {"a": {"b": [1, 2, 3]}},
        }
        memory = _make_memory(metadata=metadata)
        store.store(memory)

        assert store.get(memory.memory_id).metadata == metadata


class TestFiltering:
    def _seed(self, store):
        m1 = _make_memory(
            memory_type=MemoryType.EPISODIC,
            provenance=MemoryProvenance.EXECUTION,
            episode_id="ep-1",
            task_id="task-1",
            status=MemoryStatus.ACTIVE,
        )
        m2 = _make_memory(
            memory_type=MemoryType.FAILURE,
            provenance=MemoryProvenance.EXECUTION,
            episode_id="ep-1",
            task_id="task-2",
            status=MemoryStatus.ACTIVE,
        )
        m3 = _make_memory(
            memory_type=MemoryType.SEMANTIC,
            provenance=MemoryProvenance.INFERENCE,
            episode_id="ep-2",
            task_id="task-2",
            status=MemoryStatus.ARCHIVED,
        )
        for m in (m1, m2, m3):
            store.store(m)
        return m1, m2, m3

    def test_filter_by_memory_type(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        m1, m2, m3 = self._seed(store)
        results = store.list(memory_type=MemoryType.FAILURE)
        assert [m.memory_id for m in results] == [m2.memory_id]

    def test_filter_by_status(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        m1, m2, m3 = self._seed(store)
        results = store.list(status=MemoryStatus.ARCHIVED)
        assert [m.memory_id for m in results] == [m3.memory_id]

    def test_filter_by_provenance(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        m1, m2, m3 = self._seed(store)
        results = store.list(provenance=MemoryProvenance.INFERENCE)
        assert [m.memory_id for m in results] == [m3.memory_id]

    def test_filter_by_episode_id(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        m1, m2, m3 = self._seed(store)
        results = store.list(episode_id="ep-1")
        assert {m.memory_id for m in results} == {m1.memory_id, m2.memory_id}

    def test_filter_by_task_id(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        m1, m2, m3 = self._seed(store)
        results = store.list(task_id="task-2")
        assert {m.memory_id for m in results} == {m2.memory_id, m3.memory_id}

    def test_combined_filters_are_conjunctive(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        m1, m2, m3 = self._seed(store)
        results = store.list(episode_id="ep-1", task_id="task-2")
        assert [m.memory_id for m in results] == [m2.memory_id]

    def test_no_filters_returns_everything_newest_first(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        m1 = _make_memory(content="first", created_at=1000.0)
        m2 = _make_memory(content="second", created_at=2000.0)
        store.store(m1)
        store.store(m2)

        results = store.list()
        assert [m.memory_id for m in results] == [m2.memory_id, m1.memory_id]

    def test_limit_caps_result_count(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        self._seed(store)
        results = store.list(limit=1)
        assert len(results) == 1


class TestFailureCases:
    def test_storing_duplicate_memory_id_raises(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        memory = _make_memory()
        store.store(memory)
        with pytest.raises(DuplicateMemoryError):
            store.store(memory)

    def test_updating_missing_memory_raises(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        memory = _make_memory()
        with pytest.raises(MemoryNotFoundError):
            store.update(memory)

    def test_deleting_missing_memory_raises(self, tmp_path):
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        with pytest.raises(MemoryNotFoundError):
            store.delete("does-not-exist")

    def test_corrupted_metadata_json_raises_on_read(self, tmp_path):
        db_path = tmp_path / "memory.db"
        store = SQLiteMemoryStore(db_path)
        memory = _make_memory()
        store.store(memory)

        # Simulate a corrupted on-disk record (e.g. hand-edited/
        # partially-written row) by writing invalid JSON directly.
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE memories SET metadata = ? WHERE memory_id = ?",
            ("{not valid json", memory.memory_id),
        )
        conn.commit()
        conn.close()

        with pytest.raises(MemoryStoreError):
            store.get(memory.memory_id)

    def test_incompatible_enum_value_raises_on_read(self, tmp_path):
        db_path = tmp_path / "memory.db"
        store = SQLiteMemoryStore(db_path)
        memory = _make_memory()
        store.store(memory)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE memories SET memory_type = ? WHERE memory_id = ?",
            ("not_a_real_type", memory.memory_id),
        )
        conn.commit()
        conn.close()

        with pytest.raises(MemoryStoreError):
            store.get(memory.memory_id)

    def test_failed_store_does_not_leave_a_partial_row(self, tmp_path):
        db_path = tmp_path / "memory.db"
        store = SQLiteMemoryStore(db_path)
        memory = _make_memory()
        store.store(memory)

        # A second store() with the same id fails with IntegrityError;
        # verify the transaction rolled back cleanly rather than
        # leaving a duplicate or partially-written row behind.
        with pytest.raises(DuplicateMemoryError):
            store.store(memory)

        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE memory_id = ?",
            (memory.memory_id,),
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_database_initialization_failure_raises_memory_store_error(self, tmp_path):
        # Point the "database file" at a path whose parent is actually
        # a file, not a directory -- sqlite3 cannot create the database
        # there, so schema initialization must fail loudly rather than
        # constructing a half-usable store.
        blocking_file = tmp_path / "blocking_file"
        blocking_file.write_text("not a directory")
        bad_path = blocking_file / "memory.db"

        with pytest.raises(MemoryStoreError):
            SQLiteMemoryStore(bad_path)
