"""
trust.py (backend/memory)

Memory you can trust (roadmap 2, Phase 5). Every memory has a **source** (derived from
its provenance), a confidence, a creation time and an age-based **decay**; the user can
**pin** one (no decay, wins ties) or it can be **quarantined** (kept for review, never
used). Defences against wrong or malicious memories:

1. **Trust weighting** -- what the user said > what MILO saw/did > skills and inferences
   > anything imported. Used by `habits.usual_places` (where things go) and retrieval.
2. **Screening on write** -- an imported memory is quarantined if it contradicts a more
   trusted memory about the same thing, or reads like an instruction / absolute claim
   ("always", "never", "ignore ...").
3. **Reconciling with what MILO sees** -- a location fact that the live scene
   contradicts loses confidence; contradicted twice (or once if imported) it is
   quarantined.

    MILO_MEMORY_DEFENCE = 1 | 0    (default 1; 0 = the old ranking, for comparison)
"""

from __future__ import annotations

import math
import os
import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

from memory.models import Memory, MemoryProvenance, MemoryStatus, MemoryType

#: User-facing source of a memory.
SOURCE = {
    MemoryProvenance.USER_INPUT: "user",
    MemoryProvenance.OBSERVATION: "observation",
    MemoryProvenance.EXECUTION: "observation",
    MemoryProvenance.SKILL: "skill",
    MemoryProvenance.INFERENCE: "skill",
    MemoryProvenance.REFLECTION: "skill",
    MemoryProvenance.SYSTEM: "imported",
    MemoryProvenance.IMPORTED: "imported",
}
TRUST = {"user": 3, "observation": 2, "skill": 1, "imported": 0}
#: Days for an un-pinned memory's weight to halve (user statements decay slowest).
HALF_LIFE_DAYS = {"user": 365.0, "observation": 30.0, "skill": 60.0, "imported": 14.0}
_SUSPICIOUS = re.compile(
    r"\b(always|never|everything|every time|ignore|must|don't trust|do not trust|"
    r"delete|override|instead of the user)\b",
    re.I,
)


def defence_on() -> bool:
    return os.environ.get("MILO_MEMORY_DEFENCE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def source_of(memory: Memory) -> str:
    return SOURCE.get(memory.provenance, "imported")


def pinned(memory: Memory) -> bool:
    return bool((memory.metadata or {}).get("pinned"))


def effective_confidence(memory: Memory, now: Optional[float] = None) -> float:
    if pinned(memory):
        return float(memory.confidence)
    age_days = max(0.0, ((now or time.time()) - memory.created_at) / 86400.0)
    half = HALF_LIFE_DAYS[source_of(memory)]
    return float(memory.confidence) * math.pow(0.5, age_days / half)


def rank(memory: Memory, now: Optional[float] = None) -> tuple:
    """Higher is more trusted: pinned, then source, then decayed confidence, then newer."""
    return (
        1 if pinned(memory) else 0,
        TRUST[source_of(memory)],
        effective_confidence(memory, now),
        memory.created_at,
    )


def describe(memory: Memory, now: Optional[float] = None) -> Dict[str, Any]:
    meta = memory.metadata or {}
    return {
        "source": source_of(memory),
        "trust": TRUST[source_of(memory)],
        "effective_confidence": round(effective_confidence(memory, now), 3),
        "pinned": pinned(memory),
        "quarantined": memory.status == MemoryStatus.QUARANTINED,
        "quarantine_reason": meta.get("quarantine_reason"),
        "contradicted": int(meta.get("contradicted", 0)),
    }


# -- screening and reconciling ----------------------------------------------------------------


def _triple(memory: Memory) -> Optional[tuple]:
    meta = memory.metadata or {}
    if not {"subject", "predicate", "object"} <= set(meta):
        return None
    return (
        str(meta["subject"]).lower(),
        str(meta["predicate"]).lower(),
        str(meta["object"]).lower(),
    )


def screen(new: Memory, existing: Iterable[Memory]) -> Optional[str]:
    """Why a new memory should be quarantined, or None. Only imported memories are
    screened: what the user said and what MILO saw are taken at face value."""
    if not defence_on() or source_of(new) != "imported":
        return None
    if _SUSPICIOUS.search(new.content or ""):
        return "it reads like an instruction or an absolute claim"
    t = _triple(new)
    if t is None:
        return None
    for old in existing:
        if old.status != MemoryStatus.ACTIVE or old.memory_id == new.memory_id:
            continue
        o = _triple(old)
        if o and o[0] == t[0] and o[2] != t[2] and TRUST[source_of(old)] > 0:
            return f"it contradicts what I know from a {source_of(old)} ({old.content})"
    return None


def contradictions(
    metadata: Optional[Mapping[str, Any]], memories: Iterable[Memory]
) -> List[Memory]:
    """Location facts (not user preferences) the live scene contradicts: the object is
    visible right now, sitting in/on something else."""
    if not metadata:
        return []
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for o in metadata.get("objects") or []:
        by_type.setdefault(str(o.get("objectType", "")).lower(), []).append(o)
    out = []
    for m in memories:
        if m.status != MemoryStatus.ACTIVE or m.memory_type == MemoryType.USER:
            continue
        t = _triple(m)
        if t is None or t[1] not in (
            "located_on",
            "stored_in",
            "observed_on",
            "observed_in",
        ):
            continue
        seen = [o for o in by_type.get(t[0].replace(" ", ""), []) if o.get("visible")]
        if not seen:
            continue
        parents = {
            str(p).split("|")[0].lower()
            for o in seen
            for p in (o.get("parentReceptacles") or [])
        }
        if parents and t[2].replace(" ", "") not in parents:
            out.append(m)
    return out
