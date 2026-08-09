"""
semantics.py (backend/memory)

Purpose
-------
Phase 6.2's type-specific structure for the four `MemoryType`s, layered
entirely on top of Phase 6.1's `Memory` model with zero changes to it.
`Memory.metadata` was designed in Phase 6.1 specifically as "the
escalation path" for structured, type-specific fields (see
`models.Memory`'s docstring) -- this module is that escalation
happening: one typed helper model per memory type
(`SemanticTriple`/`EpisodicDetails`/`FailureDetails`/`UserFact`), each
`(de)serializable` to/from `Memory.metadata`, plus one factory function
per type (`build_semantic_memory`, ...) that constructs a `Memory`
whose `content` (the canonical embedding input -- see
`representation.py`) and `metadata` (the structured fields) are always
derived from the *same* structured inputs, so they can never drift out
of sync with each other.

Why factories, not just "construct `Memory` by hand"
----------------------------------------------------------
A hand-built `Memory(content="the red mug is on the table", metadata=
{"subject": "red_mug", ...})` has no guarantee `content` and `metadata`
agree -- a caller could describe one relationship in `content` and a
different one in `metadata`. Each `build_*_memory` function derives
`content` deterministically *from* the structured fields (via
`representation.py`'s per-type formatter), so "equivalent structured
input always produces an equivalent `Memory.content`" is a property of
the code, not a convention callers must remember to uphold -- directly
enabling the "equivalent memories produce equivalent embedding inputs"
test the phase spec calls for.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from memory.models import Memory, MemoryProvenance, MemoryType
from memory.representation import (
    format_episodic_content,
    format_failure_content,
    format_semantic_triple_content,
)


def _apply_deterministic_overrides(
    memory: Memory, memory_id: Optional[str], created_at: Optional[float]
) -> Memory:
    """
    Applies the optional `memory_id`/`created_at` overrides every
    `build_*_memory` factory accepts (see `build_semantic_memory`'s
    docstring) via post-construction attribute assignment -- `Memory`
    has `validate_assignment=True`, so this is still validated, and it
    keeps every factory's constructor call a plain, fully-keyword
    `Memory(...)` call mypy can check field-by-field (a `**kwargs`
    dict, tried first, cannot be checked against a Pydantic model's
    synthesized `__init__` and was rejected for that reason).
    """
    if memory_id is not None:
        memory.memory_id = memory_id
    if created_at is not None:
        memory.created_at = created_at
        memory.updated_at = created_at
    return memory


# ---------------------------------------------------------------------
# Semantic memory: subject / predicate / object triples
# ---------------------------------------------------------------------


class SemanticTriple(BaseModel):
    """
    A semantic-memory fact -- "durable-ish knowledge about the world,"
    per the phase spec, e.g. `refrigerator -> located_in -> kitchen`.
    Kept as a plain subject/predicate/object triple (not a full RDF/
    knowledge-graph model -- explicitly out of scope for 6.2) so future
    reasoning can match on `subject`/`predicate` without parsing
    `Memory.content` text.
    """

    model_config = ConfigDict(extra="forbid")

    subject: str
    predicate: str
    object: str

    @classmethod
    def from_metadata(cls, metadata: dict) -> "SemanticTriple":
        return cls(
            subject=metadata["subject"],
            predicate=metadata["predicate"],
            object=metadata["object"],
        )


def build_semantic_memory(
    subject: str,
    predicate: str,
    object: str,
    *,
    provenance: MemoryProvenance,
    confidence: float = 1.0,
    observed_at: Optional[float] = None,
    episode_id: Optional[str] = None,
    task_id: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
    memory_id: Optional[str] = None,
    created_at: Optional[float] = None,
) -> Memory:
    """
    Builds a `MemoryType.SEMANTIC` `Memory` from a triple. `memory_id`/
    `created_at` are optional overrides of `Memory`'s own defaults
    (random UUID / `time.time()`) -- used by
    `backend/memory_evaluation/dataset.py` to build a fully
    deterministic, reproducible evaluation dataset; ordinary callers
    should leave both unset.
    """
    triple = SemanticTriple(subject=subject, predicate=predicate, object=object)
    metadata = dict(extra_metadata or {})
    metadata.update(triple.model_dump())
    memory = Memory(
        memory_type=MemoryType.SEMANTIC,
        content=format_semantic_triple_content(triple),
        provenance=provenance,
        confidence=confidence,
        observed_at=observed_at,
        episode_id=episode_id,
        task_id=task_id,
        metadata=metadata,
    )
    return _apply_deterministic_overrides(memory, memory_id, created_at)


# ---------------------------------------------------------------------
# User memory: reuses the same triple shape (subject defaults to "user")
# ---------------------------------------------------------------------


class UserFact(BaseModel):
    """
    A user-specific fact/preference -- e.g. `user -> prefers -> tea`.
    Deliberately the same triple shape as `SemanticTriple` (the phase
    spec's own examples are triples) -- kept as a distinct type only so
    call sites read `UserFact`/`build_user_memory` rather than reusing
    `SemanticTriple` under a misleading name for a conceptually
    different (user-scoped, not world-scoped) fact.
    """

    model_config = ConfigDict(extra="forbid")

    subject: str = "user"
    predicate: str
    object: str

    @classmethod
    def from_metadata(cls, metadata: dict) -> "UserFact":
        return cls(
            subject=metadata.get("subject", "user"),
            predicate=metadata["predicate"],
            object=metadata["object"],
        )


def build_user_memory(
    predicate: str,
    object: str,
    *,
    provenance: MemoryProvenance = MemoryProvenance.USER_INPUT,
    subject: str = "user",
    confidence: float = 1.0,
    observed_at: Optional[float] = None,
    extra_metadata: Optional[dict] = None,
    memory_id: Optional[str] = None,
    created_at: Optional[float] = None,
) -> Memory:
    """
    Builds a `MemoryType.USER` `Memory` from a user fact/preference.
    See `build_semantic_memory`'s docstring for `memory_id`/
    `created_at`.
    """
    fact = UserFact(subject=subject, predicate=predicate, object=object)
    metadata = dict(extra_metadata or {})
    metadata.update(fact.model_dump())
    memory = Memory(
        memory_type=MemoryType.USER,
        content=format_semantic_triple_content(fact),
        provenance=provenance,
        confidence=confidence,
        observed_at=observed_at,
        metadata=metadata,
    )
    return _apply_deterministic_overrides(memory, memory_id, created_at)


# ---------------------------------------------------------------------
# Episodic memory: one past task/execution experience
# ---------------------------------------------------------------------


class EpisodicDetails(BaseModel):
    """
    Structured detail for one episodic memory -- expected to be built
    from an `execution.models.ExecutionRecord` by a future milestone
    (Phase 6.1's `Memory.episode_id`/`task_id` already carry that
    record's `execution_id`/`task_id`; this class carries everything
    else worth remembering about the episode). `outcome` is a plain
    string (`"success"`/`"failure"`/`"cancelled"`), not
    `execution.models.ExecutionStatus`, so this module never imports
    `backend/execution/` -- Phase 6.2 stays execution-independent, per
    the phase spec's "no execution -> memory integration yet" boundary;
    a future integration milestone maps `ExecutionStatus` to this
    string itself.
    """

    model_config = ConfigDict(extra="forbid")

    task_summary: str
    outcome: str
    location: Optional[str] = None
    duration_seconds: Optional[float] = None
    relevant_objects: List[str] = Field(default_factory=list)


def build_episodic_memory(
    details: EpisodicDetails,
    *,
    provenance: MemoryProvenance = MemoryProvenance.EXECUTION,
    confidence: float = 1.0,
    observed_at: Optional[float] = None,
    episode_id: Optional[str] = None,
    task_id: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
    memory_id: Optional[str] = None,
    created_at: Optional[float] = None,
) -> Memory:
    """
    Builds a `MemoryType.EPISODIC` `Memory` from `EpisodicDetails`. See
    `build_semantic_memory`'s docstring for `memory_id`/`created_at`.
    """
    metadata = dict(extra_metadata or {})
    metadata.update(details.model_dump())
    memory = Memory(
        memory_type=MemoryType.EPISODIC,
        content=format_episodic_content(details),
        provenance=provenance,
        confidence=confidence,
        observed_at=observed_at,
        episode_id=episode_id,
        task_id=task_id,
        metadata=metadata,
    )
    return _apply_deterministic_overrides(memory, memory_id, created_at)


# ---------------------------------------------------------------------
# Failure memory: one past execution failure
# ---------------------------------------------------------------------


class FailureDetails(BaseModel):
    """
    Structured detail for one failure memory. `error_code` is a plain
    string (mirroring `EpisodicDetails.outcome`'s rationale) rather than
    `execution.errors.ExecutionErrorCode`, keeping this module free of
    an `execution/` import; a future integration milestone is expected
    to pass `error_code.value` in.
    """

    model_config = ConfigDict(extra="forbid")

    task: str
    action: str
    failure_reason: str
    cause: Optional[str] = None
    context: Optional[str] = None
    recovery: Optional[str] = None
    outcome: Optional[str] = None
    error_code: Optional[str] = None


def build_failure_memory(
    details: FailureDetails,
    *,
    provenance: MemoryProvenance = MemoryProvenance.EXECUTION,
    confidence: float = 1.0,
    observed_at: Optional[float] = None,
    episode_id: Optional[str] = None,
    task_id: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
    memory_id: Optional[str] = None,
    created_at: Optional[float] = None,
) -> Memory:
    """
    Builds a `MemoryType.FAILURE` `Memory` from `FailureDetails`. See
    `build_semantic_memory`'s docstring for `memory_id`/`created_at`.
    """
    metadata = dict(extra_metadata or {})
    metadata.update(details.model_dump())
    memory = Memory(
        memory_type=MemoryType.FAILURE,
        content=format_failure_content(details),
        provenance=provenance,
        confidence=confidence,
        observed_at=observed_at,
        episode_id=episode_id,
        task_id=task_id,
        metadata=metadata,
    )
    return _apply_deterministic_overrides(memory, memory_id, created_at)
