"""Phase D: retrieval benchmark, learned embedder provider + fallback, reranker, auto re-embedding."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from learning.generate import generate
from learning.retrieval.benchmark import HELD_OUT_OBJECTS, Query, build, metrics
from learning.retrieval.reranker import (
    RetrievalReranker,
    features,
    from_mem,
    job_match,
    names_of,
    object_match,
)
from memory.config import MemoryConfig
from memory.embeddings import (
    EmbeddingConfig,
    HashingEmbedder,
    LearnedEmbedder,
    get_embedder,
)
from memory.manager import MemoryManager
from memory.models import MemoryProvenance
from memory.retrieval import RetrievalEngine, build_retrieval_engine
from memory.semantics import build_semantic_memory
from memory.sqlite_store import SQLiteMemoryStore
from memory.sqlite_vector_store import SQLiteVectorStore

BASE_MODEL = Path(__file__).resolve().parents[2] / "models" / "sentence_embedder"


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    root = tmp_path_factory.mktemp("retr")
    generate(root, episodes=900, scenes=20, seed=4, workers=1, batch=100)
    return build(root, seed=0, per_split_queries=300)


def test_benchmark_has_all_splits_and_real_memory_text(bench):
    for split in ("train", "val", "test"):
        assert bench.corpus[split] and bench.queries[split]
    kinds = {m.kind for m in bench.corpus["train"]}
    assert kinds == {"fact", "moment", "oops"}
    assert any(
        m.text.startswith("Task: ") for m in bench.corpus["train"]
    )  # production canonical text
    assert all(
        " stored_in " in m.text or " located_on " in m.text
        for m in bench.corpus["train"]
        if m.kind == "fact"
    )


def test_held_out_objects_never_appear_in_train_or_val(bench):
    for split in ("train", "val"):
        assert not [m for m in bench.corpus[split] if m.obj in HELD_OUT_OBJECTS]
        assert not [q for q in bench.queries[split] if q.obj in HELD_OUT_OBJECTS]
    assert any(q.novel_object for q in bench.queries["test"])


def test_every_query_has_at_least_one_relevant_memory_in_its_own_split(bench):
    for split in ("train", "val", "test"):
        ids = {m.mem_id for m in bench.corpus[split]}
        assert all(q.relevant and q.relevant <= ids for q in bench.queries[split])


def test_corpora_are_disjoint_between_splits_by_scene(bench):
    scenes = {s: {m.scene for m in bench.corpus[s]} for s in ("train", "val", "test")}
    assert not scenes["test"] & scenes["train"] and not scenes["test"] & scenes["val"]


def test_metrics_recall_and_mrr():
    qs = [Query("a", "x", "g", {1, 2}), Query("b", "y", "g", {9})]
    m = metrics([[1, 5, 2], [7, 8, 9]], qs, ks=(1, 3))
    assert m["recall@1"] == pytest.approx((1 / 1 + 0) / 2)
    assert m["recall@3"] == pytest.approx((2 / 2 + 1 / 1) / 2)
    assert m["mrr"] == pytest.approx((1.0 + 1 / 3) / 2)


# -- provider + fallback ----------------------------------------------------------


def test_learned_provider_falls_back_to_hashing_when_the_model_is_missing(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_LEARNED_EMBEDDER_DIR", str(tmp_path / "nope"))
    embedder = get_embedder(EmbeddingConfig("learned", 512, "", "cpu"))
    assert isinstance(embedder, HashingEmbedder)


@pytest.mark.skipif(
    not BASE_MODEL.exists(), reason="base sentence embedder weights not present"
)
def test_learned_embedder_gives_unit_vectors_and_batches_match_singles():
    emb = LearnedEmbedder(str(BASE_MODEL), device="cpu")
    texts = ["mug stored_in shelf", "bring me the apple"]
    batch = emb.embed_batch(texts)
    assert len(batch[0]) == emb.dimension == 384
    assert sum(v * v for v in batch[0]) == pytest.approx(1.0, abs=1e-4)
    assert emb.embed(texts[1]) == pytest.approx(batch[1], abs=1e-4)


# -- reranker ------------------------------------------------------------------------


def test_object_and_job_matching_understand_everyday_synonyms():
    assert (
        "tap" in names_of("faucet") and object_match("turn on the tap", "faucet") == 1.0
    )
    assert object_match("bring me the mug", "apple") == 0.0
    assert (
        job_match("grab the mug", "pick_up") == 1.0
        and job_match("open the door", "fetch") == 0.0
    )
    assert features(0.5, 2, "fact", 0.9, 3.0, True, 1.0, 0.0)[:2] == [0.5, 2.0]


def _result(content, similarity, confidence=0.8, meta=None, mtype="semantic"):
    memory = SimpleNamespace(
        content=content,
        metadata=meta or {},
        memory_type=SimpleNamespace(value=mtype),
        confidence=confidence,
        created_at=0.0,
    )
    return SimpleNamespace(memory=memory, similarity=similarity, retrieval_metadata={})


def test_reranker_promotes_the_object_that_the_query_names(bench):
    rows, labels = [], []
    for q in bench.queries["train"][:200]:
        pool = bench.corpus["train"][:30]
        for rank, m in enumerate(pool):
            rows.append(from_mem(q.text, 0.5, rank, m))
            labels.append(int(m.mem_id in q.relevant))
    rr = RetrievalReranker.fit(rows, labels)
    wrong = _result("pan stored_in shelf", 0.9, meta={"subject": "pan"})
    right = _result("mug stored_in shelf", 0.8, meta={"subject": "mug"})
    ranked = rr.rescore("bring me the mug", [wrong, right])
    assert ranked[0] is right and right.retrieval_metadata["reranked"] is True


def test_a_failing_reranker_leaves_the_order_unchanged():
    class Broken(RetrievalReranker):
        def __init__(self):
            pass

        def score(self, rows):
            raise RuntimeError("boom")

    results = [_result("a", 0.9), _result("b", 0.8)]
    assert Broken().rescore("q", results) == results
    assert RetrievalReranker.load(Path("/definitely/not/here.pkl")) is None


def test_engine_applies_the_reranker_to_its_results(tmp_path):
    class Reverse:
        def rescore(self, query, results):
            return list(reversed(results))

    manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "m.db"))
    vectors = SQLiteVectorStore(tmp_path / "v.db", dimension=128)
    plain = RetrievalEngine(manager, vectors, HashingEmbedder(128))
    for obj in ("mug", "apple", "book"):
        plain.store_and_index(
            build_semantic_memory(
                obj, "located_on", "shelf", provenance=MemoryProvenance.OBSERVATION
            )
        )
    reranked = RetrievalEngine(
        manager, vectors, HashingEmbedder(128), reranker=Reverse()
    )
    a = [r.memory.memory_id for r in plain.retrieve("mug located_on shelf", top_k=3)]
    b = [r.memory.memory_id for r in reranked.retrieve("mug located_on shelf", top_k=3)]
    assert len(a) >= 2 and b == list(reversed(a))


# -- switching embedders re-embeds the existing memories ------------------------------------


def test_switching_embedder_reembeds_existing_memories(tmp_path):
    cfg = MemoryConfig(
        enabled=True, database_path=tmp_path / "m.db", vector_store_path=tmp_path / "v"
    )
    old = build_retrieval_engine(cfg, EmbeddingConfig("hashing", 128, "", "cpu"))
    old.store_and_index(
        build_semantic_memory(
            "mug", "located_on", "shelf", provenance=MemoryProvenance.OBSERVATION
        )
    )
    assert [
        r.memory.content for r in old.retrieve("mug located_on shelf", top_k=1)
    ] == ["mug located_on shelf"]

    new = build_retrieval_engine(
        cfg, EmbeddingConfig("hashing", 256, "", "cpu")
    )  # different dimension
    assert [
        r.memory.content for r in new.retrieve("mug located_on shelf", top_k=1)
    ] == ["mug located_on shelf"]
