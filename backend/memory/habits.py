"""
habits.py (backend/memory)

Purpose
-------
Reads MILO's memories for *where things usually live*: a pure function
from a list of memories to `{object: (place, relation)}`. It is what
"tidy up" and "put it away" use to decide where each thing goes, and what
the interpreter's "put it away" rule asks.

Precedence, most trusted first:

1. what the user explicitly said (`MemoryType.USER`: "the mug goes on the
   shelf") beats anything MILO merely observed;
2. within a type, higher confidence wins;
3. at equal confidence, the newer memory wins.

Only `ACTIVE` memories count, so "forget this" (archiving) takes a habit
out of play immediately.

`relation` is `"stored_in"` (inside a container: open it, put it in, close
it) or `"located_on"` (rests on a surface).
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from memory.models import Memory, MemoryStatus, MemoryType
from memory.semantics import SemanticTriple

#: Predicates that mean "this is where the subject lives". Mirrors (and
#: extends) `planner.rule_based._LOCATION_PREDICATES`.
INSIDE_PREDICATES = frozenset({"stored_in", "typically_stored_in", "located_in"})
SURFACE_PREDICATES = frozenset({"located_on", "observed_on", "usually_on"})
_ALL = INSIDE_PREDICATES | SURFACE_PREDICATES | {"observed_in"}


def _rank(memory: Memory) -> tuple:
    from memory.trust import defence_on, rank

    if defence_on():
        # pinned, then source trust (user > observation > skill > imported), then
        # decayed confidence, then newer -- see `memory.trust`
        return rank(memory)
    user_first = 1 if memory.memory_type == MemoryType.USER else 0
    return (user_first, memory.confidence, memory.created_at)


def usual_places(memories: Iterable[Memory]) -> Dict[str, Tuple[str, str]]:
    """`{object name: (place, relation)}` from the best memory per object."""
    best: Dict[str, Tuple[tuple, Tuple[str, str]]] = {}
    for memory in memories:
        if memory.status != MemoryStatus.ACTIVE:
            continue
        if memory.memory_type not in (MemoryType.SEMANTIC, MemoryType.USER):
            continue
        try:
            triple = SemanticTriple.from_metadata(memory.metadata)
        except (KeyError, TypeError):
            continue
        if triple.predicate not in _ALL:
            continue
        subject = triple.subject.strip().lower().replace("_", " ")
        place = triple.object.strip().lower().replace("_", " ")
        relation = (
            "stored_in" if triple.predicate in INSIDE_PREDICATES else "located_on"
        )
        rank = _rank(memory)
        if subject not in best or rank > best[subject][0]:
            best[subject] = (rank, (place, relation))
    return {subject: value for subject, (_, value) in best.items()}


def usual_place_of(memories: Iterable[Memory], obj: str) -> Optional[Tuple[str, str]]:
    return usual_places(memories).get(obj.strip().lower().replace("_", " "))
