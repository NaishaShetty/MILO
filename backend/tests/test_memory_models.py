"""
test_memory_models.py

Purpose
-------
Unit tests for `memory.models`: valid `Memory` construction, closed
enums, bounded/validated `Confidence`, timestamp defaults,
provenance/lifecycle representation, metadata, and serialization
round-tripping -- Phase 6.1 spec section 12's "Domain models" test
list.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from memory.models import Memory, MemoryProvenance, MemoryStatus, MemoryType


def test_memory_type_covers_the_four_required_types():
    assert {t.value for t in MemoryType} == {
        "semantic",
        "episodic",
        "failure",
        "user",
    }


def test_memory_provenance_covers_required_sources():
    assert {p.value for p in MemoryProvenance} == {
        "observation",
        "execution",
        "user_input",
        "inference",
        "reflection",
        "system",
    }


def test_memory_status_covers_active_and_archived():
    assert {s.value for s in MemoryStatus} == {"active", "archived"}


def test_valid_memory_constructs_with_sensible_defaults():
    memory = Memory(
        memory_type=MemoryType.EPISODIC,
        content="Picked up the apple from the counter.",
        provenance=MemoryProvenance.EXECUTION,
    )
    assert memory.memory_id
    assert memory.status == MemoryStatus.ACTIVE
    assert memory.confidence == 1.0
    assert memory.created_at > 0
    assert memory.updated_at > 0
    assert memory.observed_at is None
    assert memory.episode_id is None
    assert memory.task_id is None
    assert memory.metadata == {}


def test_memory_accepts_full_field_set():
    memory = Memory(
        memory_type=MemoryType.FAILURE,
        content="Pickup failed: object not visible.",
        provenance=MemoryProvenance.EXECUTION,
        status=MemoryStatus.ARCHIVED,
        confidence=0.4,
        observed_at=1000.0,
        episode_id="exec-123",
        task_id="task-456",
        metadata={"error_code": "object_not_found"},
    )
    assert memory.status == MemoryStatus.ARCHIVED
    assert memory.confidence == 0.4
    assert memory.observed_at == 1000.0
    assert memory.episode_id == "exec-123"
    assert memory.task_id == "task-456"
    assert memory.metadata == {"error_code": "object_not_found"}


def test_invalid_memory_type_raises_at_construction():
    with pytest.raises(ValidationError):
        Memory(
            memory_type="not_a_real_type",
            content="x",
            provenance=MemoryProvenance.SYSTEM,
        )


def test_invalid_provenance_raises_at_construction():
    with pytest.raises(ValidationError):
        Memory(
            memory_type=MemoryType.SEMANTIC,
            content="x",
            provenance="not_a_real_source",
        )


@pytest.mark.parametrize("bad_confidence", [-0.01, 1.01, -5.0, 100.0])
def test_confidence_out_of_range_raises_at_construction(bad_confidence):
    with pytest.raises(ValidationError):
        Memory(
            memory_type=MemoryType.SEMANTIC,
            content="x",
            provenance=MemoryProvenance.SYSTEM,
            confidence=bad_confidence,
        )


@pytest.mark.parametrize("good_confidence", [0.0, 0.5, 1.0])
def test_confidence_boundary_values_are_accepted(good_confidence):
    memory = Memory(
        memory_type=MemoryType.SEMANTIC,
        content="x",
        provenance=MemoryProvenance.SYSTEM,
        confidence=good_confidence,
    )
    assert memory.confidence == good_confidence


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        Memory(
            memory_type=MemoryType.SEMANTIC,
            content="x",
            provenance=MemoryProvenance.SYSTEM,
            not_a_real_field=True,
        )


def test_memory_serializes_and_round_trips():
    memory = Memory(
        memory_type=MemoryType.USER,
        content="User prefers mugs stored in the cupboard.",
        provenance=MemoryProvenance.USER_INPUT,
        confidence=0.9,
        episode_id="exec-1",
        task_id="task-1",
        metadata={"topic": "storage_preference"},
    )
    payload = memory.model_dump()
    rebuilt = Memory.model_validate(payload)
    assert rebuilt == memory
    assert rebuilt.memory_type == MemoryType.USER


def test_memory_json_round_trip_preserves_enum_values():
    memory = Memory(
        memory_type=MemoryType.SEMANTIC,
        content="The mug is usually in the cupboard.",
        provenance=MemoryProvenance.INFERENCE,
    )
    json_payload = memory.model_dump(mode="json")
    assert json_payload["memory_type"] == "semantic"
    assert json_payload["provenance"] == "inference"
    assert json_payload["status"] == "active"
    rebuilt = Memory.model_validate_json(memory.model_dump_json())
    assert rebuilt == memory


def test_two_memories_get_distinct_ids_by_default():
    a = Memory(
        memory_type=MemoryType.SEMANTIC,
        content="a",
        provenance=MemoryProvenance.SYSTEM,
    )
    b = Memory(
        memory_type=MemoryType.SEMANTIC,
        content="b",
        provenance=MemoryProvenance.SYSTEM,
    )
    assert a.memory_id != b.memory_id
