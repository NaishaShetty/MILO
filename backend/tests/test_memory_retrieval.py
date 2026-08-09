"""
test_memory_retrieval.py

Purpose
-------
Tests for `memory.retrieval.RetrievalEngine` -- Phase 6.2 spec section
19's "Ranking tests" (controlled cases for similarity, confidence,
recency, provenance, context; deterministic), "Semantic memory tests"
(store -> embed -> retrieve -> rank), "Episodic memory tests" (task/
episode associations), "Failure memory tests" (natural-language
queries), and "Persistence tests" (vector + structured storage
consistent across restart).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.embeddings import HashingEmbedder
from memory.manager import MemoryManager
from memory.models import MemoryProvenance, MemoryStatus, MemoryType
from memory.retrieval import RankingWeights, RetrievalContext, RetrievalEngine
from memory.semantics import (
    EpisodicDetails,
    FailureDetails,
    build_episodic_memory,
    build_failure_memory,
    build_semantic_memory,
    build_user_memory,
)
from memory.sqlite_store import SQLiteMemoryStore
from memory.sqlite_vector_store import SQLiteVectorStore

FIXED_NOW = 1_700_000_000.0
DAY = 86400.0


def _engine(tmp_path: Path, dimension: int = 128) -> RetrievalEngine:
    manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "m.db"))
    vector_store = SQLiteVectorStore(tmp_path / "v.db", dimension=dimension)
    embedder = HashingEmbedder(dimension=dimension)
    return RetrievalEngine(manager, vector_store, embedder)


class TestEndToEndPipeline:
    def test_semantic_store_embed_retrieve_rank(self, tmp_path):
        engine = _engine(tmp_path)
        target = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.9,
        )
        decoy = build_semantic_memory(
            "refrigerator",
            "located_in",
            "kitchen",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.9,
        )
        engine.store_and_index(target)
        engine.store_and_index(decoy)

        results = engine.retrieve("red mug dining table", top_k=2, now=FIXED_NOW)
        assert results[0].memory.memory_id == target.memory_id
        assert results[0].similarity > results[1].similarity

    def test_episodic_retrieval_by_task_and_objects(self, tmp_path):
        engine = _engine(tmp_path)
        episode = build_episodic_memory(
            EpisodicDetails(
                task_summary="bring the red mug",
                outcome="success",
                location="kitchen",
                relevant_objects=["red mug", "dining table"],
            ),
            episode_id="ep-1",
            task_id="task-1",
        )
        unrelated = build_episodic_memory(
            EpisodicDetails(task_summary="bring the apple", outcome="success"),
            episode_id="ep-2",
            task_id="task-2",
        )
        engine.store_and_index(episode)
        engine.store_and_index(unrelated)

        results = engine.retrieve("bring red mug", top_k=1, now=FIXED_NOW)
        assert results[0].memory.episode_id == "ep-1"
        assert results[0].memory.task_id == "task-1"

    def test_failure_retrieval_by_natural_language_query(self, tmp_path):
        engine = _engine(tmp_path)
        failure = build_failure_memory(
            FailureDetails(
                task="reach the kitchen",
                action="navigate",
                failure_reason="navigation blocked by chair in the kitchen",
                cause="a chair was in the path",
                recovery="took an alternate route around the chair",
            )
        )
        unrelated = build_failure_memory(
            FailureDetails(
                task="open the refrigerator",
                action="open",
                failure_reason="refrigerator door was closed",
            )
        )
        engine.store_and_index(failure)
        engine.store_and_index(unrelated)

        results = engine.retrieve(
            "why did navigation fail in the kitchen chair blocked",
            memory_types=[MemoryType.FAILURE],
            top_k=1,
            now=FIXED_NOW,
        )
        assert results[0].memory.memory_id == failure.memory_id
        assert "chair" in results[0].memory.content


class TestMemoryTypeFilter:
    def test_memory_types_hard_filters_out_other_types(self, tmp_path):
        engine = _engine(tmp_path)
        semantic = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        episodic = build_episodic_memory(
            EpisodicDetails(task_summary="bring red mug", outcome="success")
        )
        engine.store_and_index(semantic)
        engine.store_and_index(episodic)

        results = engine.retrieve(
            "red mug", memory_types=[MemoryType.SEMANTIC], top_k=5, now=FIXED_NOW
        )
        assert all(r.memory.memory_type == MemoryType.SEMANTIC for r in results)


class TestConfidenceRanking:
    def test_lower_similarity_high_confidence_can_outrank_higher_similarity_low_confidence(
        self, tmp_path
    ):
        engine = _engine(tmp_path)
        # Both memories share identical text (identical similarity to
        # the query) so confidence is the only differentiator.
        high_confidence = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.95,
            memory_id="high-conf",
        )
        low_confidence = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.05,
            memory_id="low-conf",
        )
        engine.store_and_index(high_confidence)
        engine.store_and_index(low_confidence)

        results = engine.retrieve(
            "red mug located dining table", top_k=2, now=FIXED_NOW
        )
        assert results[0].memory.memory_id == "high-conf"
        assert results[0].ranking_components["confidence"] == 0.95


class TestProvenanceRanking:
    def test_observation_outranks_inference_at_equal_similarity_and_confidence(
        self, tmp_path
    ):
        engine = _engine(tmp_path)
        observed = build_semantic_memory(
            "apple",
            "typically_stored_in",
            "lower_cabinet",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.8,
            memory_id="observed",
        )
        inferred = build_semantic_memory(
            "apple",
            "typically_stored_in",
            "lower_cabinet",
            provenance=MemoryProvenance.INFERENCE,
            confidence=0.8,
            memory_id="inferred",
        )
        engine.store_and_index(observed)
        engine.store_and_index(inferred)

        results = engine.retrieve("apple lower cabinet", top_k=2, now=FIXED_NOW)
        assert results[0].memory.memory_id == "observed"
        assert (
            results[0].ranking_components["provenance"]
            > results[1].ranking_components["provenance"]
        )


class TestRecencyRanking:
    def test_recent_memory_outranks_old_memory_at_equal_other_components(
        self, tmp_path
    ):
        engine = _engine(tmp_path)
        recent = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.9,
            memory_id="recent",
            created_at=FIXED_NOW - 1 * DAY,
        )
        old = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.9,
            memory_id="old",
            created_at=FIXED_NOW - 365 * DAY,
        )
        engine.store_and_index(recent)
        engine.store_and_index(old)

        results = engine.retrieve("red mug dining table", top_k=2, now=FIXED_NOW)
        assert results[0].memory.memory_id == "recent"
        assert (
            results[0].ranking_components["recency"]
            > results[1].ranking_components["recency"]
        )

    def test_recency_score_is_deterministic_given_now(self, tmp_path):
        weights = RankingWeights()
        memory = build_semantic_memory(
            "a",
            "b",
            "c",
            provenance=MemoryProvenance.SYSTEM,
            created_at=FIXED_NOW - weights.recency_half_life_seconds,
        )
        from memory.retrieval import _recency_score

        score = _recency_score(memory, FIXED_NOW, weights.recency_half_life_seconds)
        assert score == pytest.approx(0.5, abs=1e-9)

    def test_old_memory_is_not_deleted_or_excluded_by_recency_alone(self, tmp_path):
        engine = _engine(tmp_path)
        old = build_semantic_memory(
            "a",
            "b",
            "c",
            provenance=MemoryProvenance.OBSERVATION,
            memory_id="ancient",
            created_at=FIXED_NOW - 3650 * DAY,
        )
        engine.store_and_index(old)
        results = engine.retrieve("a b c", top_k=5, now=FIXED_NOW)
        assert any(r.memory.memory_id == "ancient" for r in results)


class TestContextFiltering:
    def test_archived_memories_excluded_by_default(self, tmp_path):
        engine = _engine(tmp_path)
        archived = build_semantic_memory(
            "a", "b", "c", provenance=MemoryProvenance.OBSERVATION
        )
        archived.status = MemoryStatus.ARCHIVED
        engine.store_and_index(archived)

        results = engine.retrieve("a b c", top_k=5, now=FIXED_NOW)
        assert results == []

    def test_include_archived_returns_archived_memories(self, tmp_path):
        engine = _engine(tmp_path)
        archived = build_semantic_memory(
            "a", "b", "c", provenance=MemoryProvenance.OBSERVATION
        )
        archived.status = MemoryStatus.ARCHIVED
        engine.store_and_index(archived)

        context = RetrievalContext(include_archived=True)
        results = engine.retrieve("a b c", context=context, top_k=5, now=FIXED_NOW)
        assert any(r.memory.memory_id == archived.memory_id for r in results)

    def test_time_window_excludes_out_of_range_memories(self, tmp_path):
        engine = _engine(tmp_path)
        inside = build_semantic_memory(
            "a",
            "b",
            "c",
            provenance=MemoryProvenance.OBSERVATION,
            memory_id="inside",
            created_at=FIXED_NOW - 1 * DAY,
        )
        outside = build_semantic_memory(
            "a",
            "b",
            "c",
            provenance=MemoryProvenance.OBSERVATION,
            memory_id="outside",
            created_at=FIXED_NOW - 100 * DAY,
        )
        engine.store_and_index(inside)
        engine.store_and_index(outside)

        context = RetrievalContext(time_start=FIXED_NOW - 5 * DAY)
        results = engine.retrieve("a b c", context=context, top_k=5, now=FIXED_NOW)
        ids = {r.memory.memory_id for r in results}
        assert ids == {"inside"}

    def test_episode_id_soft_context_boosts_matching_memory(self, tmp_path):
        engine = _engine(tmp_path)
        matching = build_episodic_memory(
            EpisodicDetails(task_summary="bring red mug", outcome="success"),
            episode_id="ep-1",
            memory_id="matching",
        )
        other_episode = build_episodic_memory(
            EpisodicDetails(task_summary="bring red mug", outcome="success"),
            episode_id="ep-2",
            memory_id="other",
        )
        engine.store_and_index(matching)
        engine.store_and_index(other_episode)

        context = RetrievalContext(episode_id="ep-1")
        results = engine.retrieve(
            "bring red mug", context=context, top_k=2, now=FIXED_NOW
        )
        matching_result = next(r for r in results if r.memory.memory_id == "matching")
        other_result = next(r for r in results if r.memory.memory_id == "other")
        assert matching_result.ranking_components["context"] == 1.0
        assert other_result.ranking_components["context"] == 0.0
        assert matching_result.final_score > other_result.final_score

    def test_no_context_given_yields_neutral_context_score(self, tmp_path):
        engine = _engine(tmp_path)
        memory = build_semantic_memory(
            "a", "b", "c", provenance=MemoryProvenance.OBSERVATION
        )
        engine.store_and_index(memory)
        results = engine.retrieve("a b c", top_k=1, now=FIXED_NOW)
        assert results[0].ranking_components["context"] == 1.0

    def test_metadata_filter_partial_match_averages_signals(self, tmp_path):
        engine = _engine(tmp_path)
        memory = build_episodic_memory(
            EpisodicDetails(
                task_summary="bring red mug", outcome="success", location="kitchen"
            ),
            task_id="task-1",
        )
        engine.store_and_index(memory)

        context = RetrievalContext(
            task_id="task-1", metadata_filters={"location": "bathroom"}
        )
        results = engine.retrieve(
            "bring red mug", context=context, top_k=1, now=FIXED_NOW
        )
        # task_id matches (1.0), location does not (0.0) -> average 0.5
        assert results[0].ranking_components["context"] == pytest.approx(0.5)


class TestExplainability:
    def test_every_score_component_is_present_and_explain_is_readable(self, tmp_path):
        engine = _engine(tmp_path)
        memory = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.8,
        )
        engine.store_and_index(memory)
        result = engine.retrieve("red mug dining table", top_k=1, now=FIXED_NOW)[0]

        for key in ("similarity", "confidence", "recency", "provenance", "context"):
            assert key in result.ranking_components
        assert "query" in result.retrieval_metadata
        assert "rank" in result.retrieval_metadata
        assert result.retrieval_metadata["rank"] == 0

        explanation = result.explain()
        assert "Similarity" in explanation
        assert "Confidence" in explanation
        assert "Final score" in explanation


class TestDeterminism:
    def test_repeated_retrieval_is_byte_identical(self, tmp_path):
        engine = _engine(tmp_path)
        for i in range(5):
            engine.store_and_index(
                build_semantic_memory(
                    f"subject{i}",
                    "predicate",
                    "object",
                    provenance=MemoryProvenance.OBSERVATION,
                )
            )
        first = engine.retrieve("subject predicate object", top_k=3, now=FIXED_NOW)
        second = engine.retrieve("subject predicate object", top_k=3, now=FIXED_NOW)
        assert [r.memory.memory_id for r in first] == [
            r.memory.memory_id for r in second
        ]
        assert [r.final_score for r in first] == [r.final_score for r in second]


class TestPersistenceAcrossRestart:
    def test_retrieval_survives_manager_and_vector_store_recreation(self, tmp_path):
        manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "m.db"))
        vector_store = SQLiteVectorStore(tmp_path / "v.db", dimension=64)
        embedder = HashingEmbedder(dimension=64)
        engine = RetrievalEngine(manager, vector_store, embedder)

        memory = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        engine.store_and_index(memory)
        del engine, manager, vector_store

        reopened_manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "m.db"))
        reopened_vector_store = SQLiteVectorStore(tmp_path / "v.db", dimension=64)
        reopened_engine = RetrievalEngine(
            reopened_manager, reopened_vector_store, HashingEmbedder(dimension=64)
        )
        results = reopened_engine.retrieve(
            "red mug dining table", top_k=1, now=FIXED_NOW
        )
        assert results[0].memory.memory_id == memory.memory_id


class TestReindexAndUpdate:
    def test_reindex_all_rebuilds_vector_store_from_structured_store(self, tmp_path):
        manager = MemoryManager(store=SQLiteMemoryStore(tmp_path / "m.db"))
        memory = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        manager.store(memory)  # stored but never indexed

        vector_store = SQLiteVectorStore(tmp_path / "v.db", dimension=64)
        embedder = HashingEmbedder(dimension=64)
        engine = RetrievalEngine(manager, vector_store, embedder)

        assert engine.retrieve("red mug", top_k=5, now=FIXED_NOW) == []
        count = engine.reindex_all()
        assert count == 1
        assert engine.retrieve("red mug", top_k=5, now=FIXED_NOW) != []

    def test_update_and_reindex_reflects_new_content_in_retrieval(self, tmp_path):
        engine = _engine(tmp_path)
        memory = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        engine.store_and_index(memory)

        memory.confidence = 0.42
        engine.update_and_reindex(memory)

        results = engine.retrieve("red mug dining table", top_k=1, now=FIXED_NOW)
        assert results[0].memory.confidence == 0.42

    def test_delete_and_deindex_removes_from_retrieval(self, tmp_path):
        engine = _engine(tmp_path)
        memory = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        engine.store_and_index(memory)
        engine.delete_and_deindex(memory.memory_id)

        results = engine.retrieve("red mug dining table", top_k=5, now=FIXED_NOW)
        assert results == []


class TestUserMemoryRetrieval:
    def test_user_memory_is_retrievable(self, tmp_path):
        engine = _engine(tmp_path)
        preference = build_user_memory("prefers", "tea")
        engine.store_and_index(preference)

        results = engine.retrieve(
            "user prefers tea", memory_types=[MemoryType.USER], top_k=1, now=FIXED_NOW
        )
        assert results[0].memory.memory_id == preference.memory_id
