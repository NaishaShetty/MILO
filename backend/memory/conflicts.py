"""
conflicts.py (backend/memory)

Purpose
-------
Basic duplicate/conflict-awareness for semantic and user memories --
sections 15/16 of the phase spec. Deliberately minimal: this module
never deletes, merges, or silently overwrites a memory's factual
content. When a new observation duplicates or conflicts with an
existing `ACTIVE` memory, both memories are kept and the *relationship*
between them is recorded in the new memory's `metadata` -- a full
belief-revision/knowledge-graph-consolidation system is explicitly out
of scope for 6.2 (the phase spec's own words: "do NOT build a
sophisticated knowledge graph/consolidation system yet").

Why relationships are tagged on the *new* memory, not written onto the
old one
------------------------------------------------------------------------
Writing to the old memory's `metadata` would be a mutation of
historical evidence's associated data after the fact; `manager.update()`
supports that (Phase 6.1 permits mutable-metadata updates), but doing
it automatically, on every new observation, changes the historical
record every time new information arrives -- exactly what section 17
("do not silently overwrite historical evidence... prefer old
observation + new observation") warns against for *factual content*
and, by the same logic, for provenance-relevant metadata about that
evidence. The new memory recording "I relate to this prior memory in
this way" leaves the old memory's own record untouched.

What counts as a duplicate vs. a conflict (semantic/user memories only)
-------------------------------------------------------------------------
Both comparisons are structural (subject/predicate compared as exact
strings), never a text-similarity judgment call -- deterministic and
explainable, per the phase spec's "avoid over-engineering" note:

- **duplicate_of**: same `subject`, `predicate`, AND `object` as an
  existing `ACTIVE` memory of the same type -- the new observation
  re-confirms the same fact (e.g. the mug was seen on the dining table
  twice). Both are kept (repeated observation is itself evidence -- a
  fact seen 3 times is more credible than seen once -- a future
  consolidation milestone can use the count).
- **conflicts_with**: same `subject` and `predicate` but a DIFFERENT
  `object` (e.g. `red_mug located_on dining_table` vs. `red_mug
  located_on kitchen_counter`) -- the world changed, or one observation
  is wrong; 6.2 does not decide which (section 16: "do NOT assume the
  first memory was wrong").

Episodic/failure memories are not compared here -- each represents a
distinct, unrepeatable past event by construction (a specific
`episode_id`), so "duplicate episode" is not a meaningful concept at
this layer.
"""

from __future__ import annotations

from typing import List, Optional

from memory.manager import MemoryManager
from memory.models import Memory, MemoryStatus, MemoryType
from memory.semantics import SemanticTriple

#: Metadata key holding the list of `{"memory_id": ..., "relation":
#: ...}` relationship records this module writes onto a newly-stored
#: memory. `relation` is one of `"duplicate_of"`/`"conflicts_with"`.
RELATED_MEMORIES_KEY = "related_memories"


def _triple_of(memory: Memory) -> Optional[SemanticTriple]:
    try:
        return SemanticTriple.from_metadata(memory.metadata)
    except (KeyError, TypeError):
        return None


def detect_relationship(existing: Memory, candidate: Memory) -> Optional[str]:
    """
    Returns `"duplicate_of"`, `"conflicts_with"`, or `None` (no
    relationship) between two `SEMANTIC`/`USER` memories. See this
    module's docstring for the exact rule. Returns `None` immediately
    for any pair that is not both `SEMANTIC`/`USER` typed, or whose
    metadata does not carry a `subject`/`predicate`/`object` triple
    (i.e. a memory not built via `semantics.build_semantic_memory`/
    `build_user_memory`).
    """
    if existing.memory_type != candidate.memory_type:
        return None
    if existing.memory_type not in (MemoryType.SEMANTIC, MemoryType.USER):
        return None

    existing_triple = _triple_of(existing)
    candidate_triple = _triple_of(candidate)
    if existing_triple is None or candidate_triple is None:
        return None

    if existing_triple.subject != candidate_triple.subject:
        return None
    if existing_triple.predicate != candidate_triple.predicate:
        return None
    if existing_triple.object == candidate_triple.object:
        return "duplicate_of"
    return "conflicts_with"


def find_related_memories(manager: MemoryManager, candidate: Memory) -> List[dict]:
    """
    Scans existing `ACTIVE` memories of `candidate.memory_type` and
    returns `{"memory_id": ..., "relation": ...}` entries for every one
    `detect_relationship()` links to `candidate`. Linear scan over
    same-type memories -- acceptable at this project's research scale
    (matching `sqlite_vector_store.py`'s brute-force-is-fine rationale);
    a future milestone could index by `(subject, predicate)` if this
    ever becomes a bottleneck.
    """
    existing_memories = manager.list(
        memory_type=candidate.memory_type, status=MemoryStatus.ACTIVE
    )
    related = []
    for existing in existing_memories:
        if existing.memory_id == candidate.memory_id:
            continue
        relation = detect_relationship(existing, candidate)
        if relation is not None:
            related.append({"memory_id": existing.memory_id, "relation": relation})
    return related


def store_semantic_observation(manager: MemoryManager, candidate: Memory) -> Memory:
    """
    Stores `candidate` (a `SEMANTIC`/`USER` memory, typically built via
    `semantics.build_semantic_memory`/`build_user_memory`) after
    tagging it with any `duplicate_of`/`conflicts_with` relationships
    to existing `ACTIVE` memories -- section 15/16's "mark their
    relationship rather than silently deleting" and "preserve both
    observations when appropriate." Never mutates or deletes an
    existing memory; only ever writes `candidate`'s own metadata before
    it is first persisted.

    Callers that also want the new memory embedded/indexed should call
    `RetrievalEngine.index_memory(result)` afterward (kept separate so
    this module has no dependency on the embedding layer -- conflict
    detection is a purely structural, embedding-independent
    comparison).
    """
    related = find_related_memories(manager, candidate)
    if related:
        candidate.metadata[RELATED_MEMORIES_KEY] = related
    return manager.store(candidate)
