"""
test_memory_semantics.py

Purpose
-------
Tests for `memory.semantics`'s per-type structured models and
`build_*_memory` factories -- that each factory produces a correctly
typed `Memory` whose `metadata` round-trips back into its structured
model, and that `content`/`metadata` are always derived from the same
input (never independently settable in a way that could drift).
"""

from __future__ import annotations

from memory.models import MemoryProvenance, MemoryType
from memory.semantics import (
    EpisodicDetails,
    FailureDetails,
    SemanticTriple,
    UserFact,
    build_episodic_memory,
    build_failure_memory,
    build_semantic_memory,
    build_user_memory,
)


class TestSemanticMemory:
    def test_builds_semantic_type_with_triple_metadata(self):
        memory = build_semantic_memory(
            "refrigerator",
            "located_in",
            "kitchen",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.95,
        )
        assert memory.memory_type == MemoryType.SEMANTIC
        assert memory.metadata["subject"] == "refrigerator"
        assert memory.metadata["predicate"] == "located_in"
        assert memory.metadata["object"] == "kitchen"
        assert memory.confidence == 0.95

    def test_metadata_round_trips_through_semantic_triple(self):
        memory = build_semantic_memory(
            "apple",
            "typically_stored_in",
            "lower_cabinet",
            provenance=MemoryProvenance.INFERENCE,
        )
        triple = SemanticTriple.from_metadata(memory.metadata)
        assert triple.subject == "apple"
        assert triple.predicate == "typically_stored_in"
        assert triple.object == "lower_cabinet"

    def test_extra_metadata_is_preserved_alongside_triple_fields(self):
        memory = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
            extra_metadata={"detector": "grounding_dino"},
        )
        assert memory.metadata["detector"] == "grounding_dino"
        assert memory.metadata["subject"] == "red_mug"

    def test_memory_id_and_created_at_overrides(self):
        memory = build_semantic_memory(
            "a",
            "b",
            "c",
            provenance=MemoryProvenance.SYSTEM,
            memory_id="fixed-id",
            created_at=1000.0,
        )
        assert memory.memory_id == "fixed-id"
        assert memory.created_at == 1000.0
        assert memory.updated_at == 1000.0

    def test_default_memory_id_is_still_a_uuid_when_unset(self):
        a = build_semantic_memory("a", "b", "c", provenance=MemoryProvenance.SYSTEM)
        b = build_semantic_memory("a", "b", "c", provenance=MemoryProvenance.SYSTEM)
        assert a.memory_id != b.memory_id


class TestUserMemory:
    def test_builds_user_type_with_default_subject(self):
        memory = build_user_memory("prefers", "tea")
        assert memory.memory_type == MemoryType.USER
        assert memory.metadata["subject"] == "user"
        assert memory.metadata["predicate"] == "prefers"
        assert memory.metadata["object"] == "tea"
        assert memory.provenance == MemoryProvenance.USER_INPUT

    def test_metadata_round_trips_through_user_fact(self):
        memory = build_user_memory("stores_fruit_in", "lower_cabinet")
        fact = UserFact.from_metadata(memory.metadata)
        assert fact.subject == "user"
        assert fact.predicate == "stores_fruit_in"
        assert fact.object == "lower_cabinet"

    def test_custom_subject_is_honored(self):
        memory = build_user_memory("owns", "red_mug", subject="alice")
        assert memory.metadata["subject"] == "alice"


class TestEpisodicMemory:
    def test_builds_episodic_type_with_details_metadata(self):
        details = EpisodicDetails(
            task_summary="bring the red mug",
            outcome="success",
            location="kitchen",
            duration_seconds=42.0,
            relevant_objects=["red mug", "dining table"],
        )
        memory = build_episodic_memory(details, episode_id="ep-1", task_id="task-1")
        assert memory.memory_type == MemoryType.EPISODIC
        assert memory.episode_id == "ep-1"
        assert memory.task_id == "task-1"
        assert memory.metadata["outcome"] == "success"
        assert memory.metadata["relevant_objects"] == ["red mug", "dining table"]

    def test_content_mentions_task_and_outcome(self):
        details = EpisodicDetails(task_summary="bring the apple", outcome="success")
        memory = build_episodic_memory(details)
        assert "bring the apple" in memory.content
        assert "success" in memory.content


class TestFailureMemory:
    def test_builds_failure_type_with_details_metadata(self):
        details = FailureDetails(
            task="reach the kitchen",
            action="navigate",
            failure_reason="navigation blocked by chair",
            cause="chair in the way",
            recovery="took an alternate route",
            outcome="success",
        )
        memory = build_failure_memory(details, episode_id="ep-2")
        assert memory.memory_type == MemoryType.FAILURE
        assert memory.episode_id == "ep-2"
        assert memory.metadata["cause"] == "chair in the way"
        assert memory.metadata["recovery"] == "took an alternate route"

    def test_content_mentions_task_action_and_failure_reason(self):
        details = FailureDetails(
            task="open the refrigerator",
            action="open",
            failure_reason="door was closed and blocked opening",
        )
        memory = build_failure_memory(details)
        assert "open the refrigerator" in memory.content
        assert "open" in memory.content
        assert "door was closed and blocked opening" in memory.content

    def test_optional_fields_are_omitted_from_content_when_unset(self):
        details = FailureDetails(task="t", action="a", failure_reason="r")
        memory = build_failure_memory(details)
        assert "Cause:" not in memory.content
        assert "Recovery:" not in memory.content
