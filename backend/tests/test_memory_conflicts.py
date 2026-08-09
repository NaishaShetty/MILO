"""
test_memory_conflicts.py

Purpose
-------
Tests for `memory.conflicts` -- Phase 6.2 spec section 19's "Conflict
tests": creating conflicting memories and verifying that both evidence
records remain available, neither is silently destroyed, and retrieval
exposes relevant metadata.
"""

from __future__ import annotations

from memory.conflicts import (
    RELATED_MEMORIES_KEY,
    detect_relationship,
    find_related_memories,
    store_semantic_observation,
)
from memory.manager import MemoryManager
from memory.models import MemoryProvenance, MemoryStatus
from memory.semantics import (
    EpisodicDetails,
    build_episodic_memory,
    build_semantic_memory,
)
from memory.sqlite_store import SQLiteMemoryStore


def _manager(tmp_path):
    return MemoryManager(store=SQLiteMemoryStore(tmp_path / "m.db"))


class TestDetectRelationship:
    def test_same_triple_is_duplicate(self):
        a = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        b = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        assert detect_relationship(a, b) == "duplicate_of"

    def test_same_subject_predicate_different_object_is_conflict(self):
        a = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        b = build_semantic_memory(
            "red_mug",
            "located_on",
            "kitchen_cabinet",
            provenance=MemoryProvenance.OBSERVATION,
        )
        assert detect_relationship(a, b) == "conflicts_with"

    def test_different_predicate_is_unrelated(self):
        a = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        b = build_semantic_memory(
            "red_mug",
            "color_is",
            "red",
            provenance=MemoryProvenance.OBSERVATION,
        )
        assert detect_relationship(a, b) is None

    def test_different_subject_is_unrelated(self):
        a = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        b = build_semantic_memory(
            "blue_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        assert detect_relationship(a, b) is None

    def test_non_semantic_memories_are_never_related(self):
        a = build_episodic_memory(
            EpisodicDetails(task_summary="bring red mug", outcome="success")
        )
        b = build_episodic_memory(
            EpisodicDetails(task_summary="bring red mug", outcome="success")
        )
        assert detect_relationship(a, b) is None


class TestStoreSemanticObservation:
    def test_conflicting_observation_preserves_both_memories(self, tmp_path):
        manager = _manager(tmp_path)
        first = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        second = build_semantic_memory(
            "red_mug",
            "located_on",
            "kitchen_cabinet",
            provenance=MemoryProvenance.OBSERVATION,
        )
        store_semantic_observation(manager, first)
        store_semantic_observation(manager, second)

        # Neither memory was deleted or mutated in place.
        assert manager.get(first.memory_id) is not None
        assert manager.get(first.memory_id).metadata["object"] == "dining_table"
        assert manager.get(second.memory_id) is not None
        assert manager.get(second.memory_id).metadata["object"] == "kitchen_cabinet"
        assert manager.get(first.memory_id).status == MemoryStatus.ACTIVE
        assert manager.get(second.memory_id).status == MemoryStatus.ACTIVE

    def test_new_memory_is_tagged_with_conflict_relationship(self, tmp_path):
        manager = _manager(tmp_path)
        first = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        store_semantic_observation(manager, first)

        second = build_semantic_memory(
            "red_mug",
            "located_on",
            "kitchen_cabinet",
            provenance=MemoryProvenance.OBSERVATION,
        )
        stored_second = store_semantic_observation(manager, second)

        related = stored_second.metadata[RELATED_MEMORIES_KEY]
        assert {"memory_id": first.memory_id, "relation": "conflicts_with"} in related

    def test_old_memory_metadata_is_never_mutated(self, tmp_path):
        manager = _manager(tmp_path)
        first = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        store_semantic_observation(manager, first)

        second = build_semantic_memory(
            "red_mug",
            "located_on",
            "kitchen_cabinet",
            provenance=MemoryProvenance.OBSERVATION,
        )
        store_semantic_observation(manager, second)

        # The relationship is recorded on the NEW memory only.
        assert RELATED_MEMORIES_KEY not in manager.get(first.memory_id).metadata

    def test_duplicate_observation_is_tagged_not_discarded(self, tmp_path):
        manager = _manager(tmp_path)
        first = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        store_semantic_observation(manager, first)

        duplicate = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        stored_duplicate = store_semantic_observation(manager, duplicate)

        # Both records exist -- the duplicate is not silently dropped.
        assert manager.get(first.memory_id) is not None
        assert manager.get(duplicate.memory_id) is not None
        related = stored_duplicate.metadata[RELATED_MEMORIES_KEY]
        assert {"memory_id": first.memory_id, "relation": "duplicate_of"} in related

    def test_archived_memories_are_not_considered_for_relationships(self, tmp_path):
        manager = _manager(tmp_path)
        first = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        stored_first = store_semantic_observation(manager, first)
        stored_first.status = MemoryStatus.ARCHIVED
        manager.update(stored_first)

        second = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        related = find_related_memories(manager, second)
        assert related == []

    def test_no_prior_memories_yields_no_relationships(self, tmp_path):
        manager = _manager(tmp_path)
        memory = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        stored = store_semantic_observation(manager, memory)
        assert RELATED_MEMORIES_KEY not in stored.metadata
