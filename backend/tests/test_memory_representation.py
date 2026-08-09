"""
test_memory_representation.py

Purpose
-------
Tests for `memory.representation.canonical_text` and the per-type
`format_*_content` functions -- Phase 6.2 spec section 7's "the
representation must be deterministic, documented, reproducible" and
"tests ensuring equivalent memories produce equivalent embedding
inputs."
"""

from __future__ import annotations

from memory.embeddings import HashingEmbedder
from memory.models import MemoryProvenance
from memory.representation import canonical_text
from memory.semantics import (
    EpisodicDetails,
    FailureDetails,
    build_episodic_memory,
    build_failure_memory,
    build_semantic_memory,
    build_user_memory,
)


class TestCanonicalTextIsMemoryContent:
    def test_canonical_text_returns_memory_content(self):
        memory = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        assert canonical_text(memory) == memory.content


class TestEquivalentInputsProduceEquivalentRepresentations:
    def test_two_semantic_memories_with_same_triple_produce_identical_content(self):
        a = build_semantic_memory(
            "apple",
            "typically_stored_in",
            "lower_cabinet",
            provenance=MemoryProvenance.INFERENCE,
        )
        b = build_semantic_memory(
            "apple",
            "typically_stored_in",
            "lower_cabinet",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.5,
        )
        # Same triple, different provenance/confidence -- content (the
        # embedding input) must still be byte-identical.
        assert canonical_text(a) == canonical_text(b)

    def test_two_semantic_memories_with_same_triple_embed_identically(self):
        embedder = HashingEmbedder(dimension=64)
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
        assert embedder.embed(canonical_text(a)) == embedder.embed(canonical_text(b))

    def test_different_triples_produce_different_content(self):
        a = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        b = build_semantic_memory(
            "red_mug",
            "located_on",
            "kitchen_counter",
            provenance=MemoryProvenance.OBSERVATION,
        )
        assert canonical_text(a) != canonical_text(b)

    def test_episodic_memories_with_same_details_produce_identical_content(self):
        details = EpisodicDetails(
            task_summary="bring the red mug",
            outcome="success",
            location="kitchen",
            relevant_objects=["red mug", "dining table"],
        )
        a = build_episodic_memory(details)
        b = build_episodic_memory(details)
        assert canonical_text(a) == canonical_text(b)

    def test_failure_memories_with_same_details_produce_identical_content(self):
        details = FailureDetails(
            task="reach the kitchen",
            action="navigate",
            failure_reason="blocked by chair",
        )
        a = build_failure_memory(details)
        b = build_failure_memory(details)
        assert canonical_text(a) == canonical_text(b)

    def test_user_memories_with_same_fact_produce_identical_content(self):
        a = build_user_memory("prefers", "tea")
        b = build_user_memory("prefers", "tea")
        assert canonical_text(a) == canonical_text(b)


class TestContentDoesNotContainRawJson:
    def test_semantic_content_has_no_json_braces(self):
        memory = build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        assert "{" not in memory.content
        assert "}" not in memory.content

    def test_episodic_content_has_no_json_braces(self):
        memory = build_episodic_memory(
            EpisodicDetails(task_summary="bring apple", outcome="success")
        )
        assert "{" not in memory.content
        assert "}" not in memory.content
