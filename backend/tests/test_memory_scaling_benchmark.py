"""
test_memory_scaling_benchmark.py

Benchmark + regression tests for memory retrieval/write at 5,000
memories (Phase 1): vectors are loaded once into an in-memory index and
kept in sync on writes, candidate memories are fetched in one batched
read, and a semantic write no longer lists every semantic memory.

Offline and deterministic (`HashingEmbedder`, pytest's `tmp_path`);
no sentence-transformers download. Run with `-s` to see the numbers:

    cd backend
    python -m pytest tests/test_memory_scaling_benchmark.py -v -s
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing

import numpy as np
import pytest

from memory.conflicts import store_semantic_observation
from memory.embeddings import HashingEmbedder
from memory.manager import MemoryManager
from memory.models import MemoryProvenance, MemoryStatus, MemoryType
from memory.retrieval import RetrievalEngine
from memory.semantics import build_semantic_memory as _build
from memory.sqlite_store import SQLiteMemoryStore
from memory.sqlite_vector_store import SQLiteVectorStore

N = 5_000
DIMENSION = 512


def build_semantic_memory(subject, predicate, object_, confidence=0.8):
    return _build(
        subject,
        predicate,
        object_,
        provenance=MemoryProvenance.OBSERVATION,
        confidence=confidence,
    )


def _seed(tmp_path, n=N):
    manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "m.db"))
    vectors = SQLiteVectorStore(tmp_path / "v.db", dimension=DIMENSION)
    engine = RetrievalEngine(manager, vectors, HashingEmbedder(dimension=DIMENSION))
    for i in range(n):
        manager.store(
            build_semantic_memory(
                f"object_{i}", "located_on", f"surface_{i % 40}", confidence=0.8
            )
        )
    assert engine.reindex_all() == n
    return manager, vectors, engine


def _legacy_search(db_path, query, top_k):
    """The pre-change algorithm: reload + re-normalise every vector per query."""
    query = np.asarray(query, dtype=np.float32)
    query = query / np.linalg.norm(query)
    with closing(sqlite3.connect(str(db_path))) as conn:
        rows = conn.execute(
            "SELECT memory_id, embedding FROM vectors ORDER BY memory_id"
        ).fetchall()
    ids = [r[0] for r in rows]
    matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    norms = np.linalg.norm(matrix, axis=1)
    sims = (matrix / np.where(norms == 0.0, 1.0, norms)[:, None]) @ query
    order = np.argsort(-sims, kind="stable")[:top_k]
    return [(ids[i], float(sims[i])) for i in order]


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    return _seed(tmp_path_factory.mktemp("mem5000"))


def test_in_memory_index_matches_the_legacy_search(seeded):
    _, vectors, _ = seeded
    embedder = HashingEmbedder(dimension=DIMENSION)
    for query in ("object_17 located_on", "object_4242 surface_2", "surface_9"):
        q = embedder.embed(query)
        raw = [(r.memory_id, r.score) for r in vectors.search(q, top_k=10)]
        new = [(mid, round(score, 4)) for mid, score in raw]
        old = [
            (mid, round(score, 4))
            for mid, score in _legacy_search(vectors._database_path, q, 10)
        ]
        assert len(new) == 10
        assert [s for _, s in new] == [s for _, s in old]  # same scores, same order
        # Ties (identical float scores) are broken by memory_id, always.
        assert raw == sorted(raw, key=lambda t: (-t[1], t[0]))


def test_search_after_load_does_not_touch_sqlite(seeded, monkeypatch):
    _, vectors, _ = seeded
    vectors.search(HashingEmbedder(dimension=DIMENSION).embed("warm up"), top_k=5)

    def _no_database(*_a, **_k):
        raise AssertionError("search() must not read the database once loaded")

    monkeypatch.setattr(vectors, "_connect", _no_database)
    results = vectors.search(
        HashingEmbedder(dimension=DIMENSION).embed("object_17 located_on"), top_k=5
    )
    assert results and results[0].memory_id


def test_retrieval_fetches_candidates_in_one_batched_read(seeded, monkeypatch):
    manager, _, engine = seeded
    engine.retrieve("object_17 located_on surface_17", top_k=5)  # warm the index
    calls = {"get": 0, "get_many": 0}
    real_get, real_get_many = manager.get, manager.get_many

    def counting_get(*a, **k):
        calls["get"] += 1
        return real_get(*a, **k)

    def counting_get_many(*a, **k):
        calls["get_many"] += 1
        return real_get_many(*a, **k)

    monkeypatch.setattr(manager, "get", counting_get)
    monkeypatch.setattr(manager, "get_many", counting_get_many)

    results = engine.retrieve("object_17 located_on surface_17", top_k=5)

    assert results
    assert calls["get"] == 0  # no per-candidate reads
    assert calls["get_many"] == 1


def test_semantic_write_does_not_list_every_semantic_memory(seeded, monkeypatch):
    manager, _, _ = seeded

    def _no_full_listing(*_a, **_k):
        raise AssertionError("a semantic write must not list all memories")

    monkeypatch.setattr(manager, "list", _no_full_listing)
    stored = store_semantic_observation(
        manager, build_semantic_memory("object_17", "located_on", "surface_99")
    )
    # Still finds the one existing memory it conflicts with, via the index.
    related = stored.metadata["related_memories"]
    assert [r["relation"] for r in related] == ["conflicts_with"]


def test_writes_keep_the_index_in_sync(tmp_path):
    manager, vectors, engine = _seed(tmp_path, n=50)
    embedder = HashingEmbedder(dimension=DIMENSION)
    vectors.search(embedder.embed("warm"), top_k=1)  # load the index

    fresh = engine.store_and_index(
        build_semantic_memory("brand_new_widget", "located_on", "workbench")
    )
    top = engine.retrieve("brand_new_widget located_on workbench", top_k=1)
    assert top and top[0].memory.memory_id == fresh.memory_id

    engine.delete_and_deindex(fresh.memory_id)
    after = engine.retrieve("brand_new_widget located_on workbench", top_k=3)
    assert fresh.memory_id not in [r.memory.memory_id for r in after]
    assert vectors.size == 50

    # A restart (new instance, same file) sees exactly the same data.
    reopened = SQLiteVectorStore(tmp_path / "v.db", dimension=DIMENSION)
    assert reopened.size == 50


def test_find_by_triple_only_returns_matching_active_memories(tmp_path):
    manager, _, _ = _seed(tmp_path, n=30)
    match = manager.find_by_triple(MemoryType.SEMANTIC, "object_3", "located_on")
    assert len(match) == 1 and match[0].metadata["subject"] == "object_3"
    assert manager.find_by_triple(MemoryType.SEMANTIC, "nope", "located_on") == []
    match[0].status = MemoryStatus.ARCHIVED
    manager.update(match[0])
    assert (
        manager.find_by_triple(
            MemoryType.SEMANTIC, "object_3", "located_on", status=MemoryStatus.ACTIVE
        )
        == []
    )


def test_benchmark_5000_memories(seeded, capsys):
    """Prints before/after numbers; asserts the new path is clearly faster."""
    manager, vectors, engine = seeded
    embedder = HashingEmbedder(dimension=DIMENSION)
    queries = [embedder.embed(f"object_{i * 97 % N} located_on") for i in range(30)]
    vectors.search(queries[0], top_k=20)  # load once (not counted)
    db_path = vectors._database_path

    t = time.perf_counter()
    for q in queries:
        _legacy_search(db_path, q, 20)
    legacy_ms = (time.perf_counter() - t) * 1000 / len(queries)

    t = time.perf_counter()
    for q in queries:
        vectors.search(q, top_k=20)
    search_ms = (time.perf_counter() - t) * 1000 / len(queries)

    t = time.perf_counter()
    for i in range(30):
        engine.retrieve(f"object_{i * 97 % N} located_on", top_k=5)
    retrieve_ms = (time.perf_counter() - t) * 1000 / 30

    t = time.perf_counter()
    for i in range(10):
        store_semantic_observation(
            manager, build_semantic_memory(f"bench_{i}", "located_on", "shelf")
        )
    write_ms = (time.perf_counter() - t) * 1000 / 10

    with capsys.disabled():
        print(
            f"\n[memory@{N}] vector search: legacy {legacy_ms:.2f} ms -> "
            f"indexed {search_ms:.3f} ms ({legacy_ms / max(search_ms, 1e-9):.0f}x); "
            f"full retrieve {retrieve_ms:.2f} ms; semantic write {write_ms:.2f} ms"
        )

    assert search_ms * 5 < legacy_ms
    assert retrieve_ms < 100  # generous ceiling; typically a few ms


def test_an_existing_database_without_triple_columns_is_migrated(tmp_path):
    # A memory DB created before `subject`/`predicate` columns existed.
    db = tmp_path / "old.db"
    with closing(sqlite3.connect(str(db))) as conn:
        conn.executescript(
            """
            CREATE TABLE memories (
                memory_id TEXT PRIMARY KEY, memory_type TEXT NOT NULL,
                content TEXT NOT NULL, provenance TEXT NOT NULL,
                status TEXT NOT NULL, confidence REAL NOT NULL,
                created_at REAL NOT NULL, observed_at REAL,
                updated_at REAL NOT NULL, episode_id TEXT, task_id TEXT,
                metadata TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO memories VALUES ('m1','semantic','mug on table','observation',"
            "'active',0.9,1.0,NULL,1.0,NULL,NULL,"
            '\'{"subject": "mug", "predicate": "located_on", "object": "table"}\')'
        )
        conn.commit()

    store = SQLiteMemoryStore(db)  # opening it migrates + backfills

    found = store.find_by_triple(MemoryType.SEMANTIC, "mug", "located_on")
    assert [m.memory_id for m in found] == ["m1"]
    SQLiteMemoryStore(db)  # idempotent: reopening a migrated DB is fine
