"""
lessons.py (backend/memory)

Failure memory: after a mission fails, MILO keeps a one-line lesson -- what it was
doing, which step failed and why -- as a semantic memory. Before planning the same kind
of task again it recalls matching lessons, says so, and adjusts the plan where it knows
how:

    "not visible" after walking to something -> look around before using it

Other failure kinds (out of reach, blocked, door stuck, timeout) are recalled and said
out loud ("Last time I couldn't reach the bowl.") but don't change the plan.

    MILO_FAILURE_MEMORY = 1 | 0     (default 1)
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

from memory.models import Memory, MemoryProvenance, MemoryStatus
from planner.models import Plan, PlanStep

PREDICATE = "failed_because"
_WHY = {
    "not_visible": "couldn't see",
    "wrong_object": "couldn't find",
    "not_reachable": "couldn't reach",
    "blocked": "found the way blocked to",
    "timeout": "timed out on",
}


def enabled() -> bool:
    return os.environ.get("MILO_FAILURE_MEMORY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _key(goal: Optional[str], obj: Optional[str]) -> str:
    name = (obj or "").split("|", 1)[0].lower()
    return f"lesson:{(goal or '').lower()}:{name}"


def lesson_from(
    task_state: Any, goal: Optional[str], obj: Optional[str]
) -> Optional[Dict[str, Any]]:
    """The lesson a failed mission teaches, or None if there is nothing specific."""
    failed = None
    for record in reversed(task_state.execution_history):
        failed = next(
            (s for s in record.step_results if s.status.value in ("failed", "blocked")),
            None,
        )
        if failed is not None:
            break
    if failed is None:
        return None
    from learning.features import failure_type

    error = failed.error
    category = failure_type(
        getattr(getattr(error, "code", None), "value", None),
        getattr(error, "message", None),
        False,
    )
    step = next(
        (
            s
            for s in (task_state.current_plan.steps if task_state.current_plan else [])
            if s.step_id == failed.step_id
        ),
        None,
    )
    action = step.action if step else "act"
    target = (step.target if step else None) or obj
    name = (target or "").split("|", 1)[0].lower()
    verb = _WHY.get(category, "had trouble with")
    return {
        "key": _key(goal, obj),
        "goal": goal,
        "object": (obj or "").split("|", 1)[0].lower(),
        "action": action,
        "target": name,
        "failure": category,
        "text": f"Last time I {verb} the {name} ({action.replace('_', ' ')})",
    }


def recall(
    memories: Iterable[Memory], goal: Optional[str], obj: Optional[str]
) -> List[Dict[str, Any]]:
    key = _key(goal, obj)
    out = []
    for m in memories:
        meta = m.metadata or {}
        if (
            m.status == MemoryStatus.ACTIVE
            and meta.get("subject") == key
            and meta.get("lesson")
        ):
            out.append(meta["lesson"])
    return out


def apply(plan: Plan, lessons: List[Dict[str, Any]]) -> Optional[str]:
    """Adjusts `plan` in place for lessons MILO knows how to act on; returns what it
    will say (None if no lesson applies)."""
    if not lessons:
        return None
    unseen = {x["target"] for x in lessons if x.get("failure") == "not_visible"}
    changed = False
    if unseen:
        steps: List[PlanStep] = []
        for s in plan.steps:
            steps.append(s)
            name = (s.target or "").split("|", 1)[0].lower()
            if s.action == "navigate" and name in unseen:
                steps.append(
                    PlanStep(
                        step_id=len(steps) + 1,  # renumbered below
                        action="look_around",
                        target=None,
                        description="Look around",
                    )
                )
                changed = True
        for i, s in enumerate(steps, start=1):
            s.step_id = i
        plan.steps = steps
    text = lessons[-1]["text"]
    return f"{text}, so I'll look around first." if changed else f"{text}."


def remember(memory_agent: Any, lesson: Dict[str, Any], **ids: Any) -> Optional[Memory]:
    if memory_agent is None:
        return None
    from memory.semantics import build_semantic_memory

    memory = build_semantic_memory(
        lesson["key"],
        PREDICATE,
        lesson["failure"].lower(),
        provenance=MemoryProvenance.REFLECTION,
        confidence=0.8,
        extra_metadata={"lesson": lesson},
        **{k: v for k, v in ids.items() if k in ("episode_id", "task_id")},
    )
    memory.content = lesson["text"]
    engine = getattr(memory_agent, "engine", None) or getattr(
        memory_agent, "_engine", None
    )
    try:
        return engine.store_and_index(memory) if engine is not None else None
    except Exception:
        return None
