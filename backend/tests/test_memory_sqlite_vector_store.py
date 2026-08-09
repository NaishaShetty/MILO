"""
test_memory_sqlite_vector_store.py

Purpose
-------
Tests for `memory.sqlite_vector_store.SQLiteVectorStore` -- Phase 6.2
spec section 19's "Vector retrieval tests": relevant memory retrieval,
irrelevant memory rejection, top-k behavior, empty database, duplicate
vectors, and persistence across restart.
"""

from __future__ import annotations

import math

import pytest

from memory.sqlite_vector_store import SQLiteVectorStore


def _unit(vector):
    norm = math.sqrt(sum(c * c for c in vector))
    return [c / norm for c in vector]


class TestEmptyDatabase:
    def test_search_on_empty_store_returns_empty_list(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=8)
        results = store.search([1.0] + [0.0] * 7, top_k=5)
        assert results == []


class TestUpsertAndSearch:
    def test_exact_match_scores_highest(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=4)
        target = _unit([1.0, 0.0, 0.0, 0.0])
        orthogonal = _unit([0.0, 1.0, 0.0, 0.0])
        store.upsert("target", target)
        store.upsert("orthogonal", orthogonal)

        results = store.search(target, top_k=2)
        assert results[0].memory_id == "target"
        assert results[0].score == pytest.approx(1.0, abs=1e-6)

    def test_irrelevant_vector_scores_low(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=4)
        store.upsert("relevant", _unit([1.0, 0.0, 0.0, 0.0]))
        store.upsert("orthogonal", _unit([0.0, 1.0, 0.0, 0.0]))

        results = store.search(_unit([1.0, 0.0, 0.0, 0.0]), top_k=2)
        orthogonal_result = next(r for r in results if r.memory_id == "orthogonal")
        assert orthogonal_result.score == pytest.approx(0.0, abs=1e-6)

    def test_top_k_limits_result_count(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=4)
        for i in range(10):
            vec = [0.0, 0.0, 0.0, 0.0]
            vec[i % 4] = 1.0
            store.upsert(f"m{i}", vec)
        results = store.search([1.0, 0.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3

    def test_top_k_larger_than_store_returns_everything(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=4)
        store.upsert("a", _unit([1.0, 0.0, 0.0, 0.0]))
        store.upsert("b", _unit([0.0, 1.0, 0.0, 0.0]))
        results = store.search([1.0, 0.0, 0.0, 0.0], top_k=100)
        assert len(results) == 2

    def test_upsert_same_id_replaces_previous_vector(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=4)
        store.upsert("m1", _unit([1.0, 0.0, 0.0, 0.0]))
        store.upsert("m1", _unit([0.0, 1.0, 0.0, 0.0]))
        results = store.search(_unit([0.0, 1.0, 0.0, 0.0]), top_k=1)
        assert results[0].memory_id == "m1"
        assert results[0].score == pytest.approx(1.0, abs=1e-6)

    def test_duplicate_vectors_both_returned(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=4)
        vec = _unit([1.0, 1.0, 0.0, 0.0])
        store.upsert("m1", vec)
        store.upsert("m2", vec)
        results = store.search(vec, top_k=2)
        ids = {r.memory_id for r in results}
        assert ids == {"m1", "m2"}
        assert all(r.score == pytest.approx(1.0, abs=1e-6) for r in results)

    def test_delete_removes_vector_from_search(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=4)
        store.upsert("m1", _unit([1.0, 0.0, 0.0, 0.0]))
        store.delete("m1")
        results = store.search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert results == []

    def test_delete_nonexistent_id_is_a_no_op(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=4)
        store.delete("does-not-exist")  # must not raise


class TestPersistence:
    def test_vectors_survive_reopening_the_store(self, tmp_path):
        db_path = tmp_path / "v.db"
        vec = _unit([1.0, 0.0, 0.0, 0.0])

        first = SQLiteVectorStore(db_path, dimension=4)
        first.upsert("m1", vec)
        del first

        second = SQLiteVectorStore(db_path, dimension=4)
        results = second.search(vec, top_k=1)
        assert results[0].memory_id == "m1"
        assert results[0].score == pytest.approx(1.0, abs=1e-6)


class TestFailureCases:
    def test_wrong_dimension_embedding_rejected(self, tmp_path):
        store = SQLiteVectorStore(tmp_path / "v.db", dimension=4)
        with pytest.raises(ValueError):
            store.upsert("m1", [1.0, 0.0])

    def test_zero_or_negative_dimension_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            SQLiteVectorStore(tmp_path / "v.db", dimension=0)
