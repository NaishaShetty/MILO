"""
test_memory_store.py

Purpose
-------
Tests for `memory.store`'s abstract interfaces themselves: that
`MemoryStore`/`VectorStore` cannot be instantiated without implementing
every abstract method (the mechanism that guarantees a concrete
backend can't silently omit part of the contract), and that
`SQLiteMemoryStore` satisfies the `MemoryStore` interface.
"""

from __future__ import annotations

import pytest

from memory.sqlite_store import SQLiteMemoryStore
from memory.store import MemoryStore, VectorSearchResult, VectorStore


def test_memory_store_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        MemoryStore()  # type: ignore[abstract]


def test_vector_store_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        VectorStore()  # type: ignore[abstract]


def test_sqlite_memory_store_is_a_memory_store(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    assert isinstance(store, MemoryStore)


def test_incomplete_memory_store_subclass_cannot_be_instantiated():
    class IncompleteStore(MemoryStore):
        def store(self, memory):
            pass

        # get/update/delete/list intentionally left unimplemented.

    with pytest.raises(TypeError):
        IncompleteStore()  # type: ignore[abstract]


def test_vector_search_result_equality():
    a = VectorSearchResult(memory_id="m1", score=0.9)
    b = VectorSearchResult(memory_id="m1", score=0.9)
    c = VectorSearchResult(memory_id="m2", score=0.9)
    assert a == b
    assert a != c
