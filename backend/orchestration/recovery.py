"""
recovery.py (backend/orchestration)

In-mission recovery: targeted plan fixes the `Orchestrator` applies between a failed
attempt and the next one, for the two failure kinds a plain retry/replan cannot fix.

A retry re-runs the *same* plan, and the executor skips every step already marked
completed -- so the `navigate` that left MILO unable to see or reach the object never
runs again, and the next attempt fails the same way. A replan gives the same steps.
So, before the next attempt:

    "not visible"   -> insert `look_around` just before the step that failed;
    "not reachable" -> insert a fresh `navigate` to the target before it (re-approach).
                       A second time for the same step: look around first, then
                       re-approach from wherever that leaves MILO.
    "blocked"       -> the first time, a plain retry (most blockages clear). The second
                       time for the same place, mark that instance as blocked and point
                       the rest of the plan at the nearest other one of the same kind
                       ("Shelf|2" instead of the blocked "Shelf|1"), for the rest of the
                       mission, replans included. The orchestrator also remembers the
                       blocked instance, so the next mission avoids it before acting.

Each fix is applied at most `MAX_PER_STEP` times per (failure, action, target) in one
mission, and the orchestrator's own `max_replans` still bounds the attempts. Failure
memory (`memory.lessons`) does the look-around on the *next* mission; this does it now.

    MILO_INMISSION_RECOVERY = 1 | 0     (default 1; 0 = plain retry/replan as before)

`Orchestrator(in_mission_recovery=True|False)` overrides the variable for one
orchestrator (the training-data generator turns it off to keep its dataset fixed).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

from execution.models import ExecutionRecord, StepStatus
from execution.resolver import ObjectResolver
from planner.models import Plan, PlanStep

_resolver = ObjectResolver()

MAX_PER_STEP = 2


def enabled() -> bool:
    return os.environ.get("MILO_INMISSION_RECOVERY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _name(target: Optional[str]) -> str:
    return (target or "").split("|", 1)[0].lower()


def _failed_step(record: ExecutionRecord) -> Optional[Tuple[str, Optional[str], str]]:
    """(action, target, failure kind) of the step that failed, if it is one we fix."""
    from learning.features import failure_type

    for s in record.step_results:
        if s.status != StepStatus.FAILED:
            continue
        error = s.error
        kind = failure_type(
            getattr(getattr(error, "code", None), "value", None),
            getattr(error, "message", None),
            False,
        )
        if kind in ("not_visible", "not_reachable"):
            return s.action, s.target, kind
        if kind == "blocked" and s.action == "navigate":
            return s.action, s.target, kind
        return None
    return None


def instances(name: str, metadata: Mapping[str, Any]) -> List[str]:
    """objectIds of every object of this kind, nearest first."""
    found = _resolver._candidates(name, dict(metadata))
    found.sort(key=lambda o: o.get("distance", float("inf")))
    return [str(o["objectId"]) for o in found if o.get("objectId")]


def avoid(
    plan: Plan, avoided: Mapping[str, List[str]], metadata: Mapping[str, Any]
) -> List[Tuple[str, str]]:
    """Point the plan's remaining steps that name a kind of place ("shelf") at the
    nearest instance that isn't known to be blocked. Returns (kind, instance) changes.
    """
    changes = []
    for name, bad in avoided.items():
        blocked = {b.lower() for b in bad}
        ids = instances(name, metadata)
        if not blocked & {i.lower() for i in ids}:
            continue
        alt = next((i for i in ids if i.lower() not in blocked), None)
        if alt is None:
            continue
        changed = False
        for step in plan.steps:
            if step.status == StepStatus.COMPLETED:
                continue
            if step.target and "|" not in step.target and _name(step.target) == name:
                step.target = alt
                changed = True
            container = (step.parameters or {}).get("container")
            if (
                isinstance(container, str)
                and "|" not in container
                and _name(container) == name
            ):
                step.parameters = {**step.parameters, "container": alt}
                changed = True
        if changed:
            changes.append((name, alt))
    return changes


def _switch_instance(
    plan: Plan,
    action: str,
    target: Optional[str],
    counts: Dict[Any, Any],
    metadata: Optional[Mapping[str, Any]],
) -> Optional[str]:
    name = _name(target)
    key = ("blocked", action, name)
    counts[key] = counts.get(key, 0) + 1
    if counts[key] < 2 or metadata is None:
        return None  # the first time, a plain retry: most blockages clear
    bad: List[str] = counts.setdefault("avoid", {}).setdefault(name, [])
    ids = instances(name, metadata)
    blocked = (
        target
        if target and "|" in target
        else next((i for i in ids if i not in bad), None)
    )
    if blocked and blocked not in bad:
        bad.append(blocked)
    if not avoid(plan, {name: bad}, metadata):
        return None
    plan.metadata.setdefault("in_mission_recovery", []).append(
        {"failure": "blocked", "action": action, "target": name, "avoided": list(bad)}
    )
    return f"The way to the {name} is blocked, so I'll use another {name}."


def mitigate(
    plan: Plan,
    record: ExecutionRecord,
    counts: Dict[Any, Any],
    metadata: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Adjusts `plan` in place after the failed attempt `record`; returns what MILO
    says about it (None if nothing applies). `counts` is the mission's tally; it also
    keeps the instances found blocked, so a replan keeps avoiding them."""
    if metadata is not None and counts.get("avoid"):
        avoid(plan, counts["avoid"], metadata)
    failed = _failed_step(record)
    if failed is None:
        return None
    action, target, kind = failed
    if kind == "blocked":
        return _switch_instance(plan, action, target, counts, metadata)
    name = _name(target)
    key = (kind, action, name)
    if counts.get(key, 0) >= MAX_PER_STEP:
        return None
    index = next(
        (
            i
            for i, s in enumerate(plan.steps)
            if s.status != StepStatus.COMPLETED
            and s.action == action
            and _name(s.target) == name
        ),
        None,
    )
    if index is None:
        return None
    nth = counts.get(key, 0)
    counts[key] = nth + 1

    look = PlanStep(
        step_id=1, action="look_around", target=None, description="Look around"
    )
    if kind == "not_visible":
        extra = [look]
        said = f"I couldn't see the {name}, so I'll look around before trying again."
    else:
        approach_to = target or name
        template = next(
            (
                s
                for s in plan.steps[:index]
                if s.action == "navigate" and _name(s.target) == name
            ),
            None,
        )
        nav = (
            template.model_copy(
                update={
                    "status": StepStatus.PENDING,
                    "explanation": None,
                    "confidence": None,
                    "why": None,
                },
                deep=True,
            )
            if template is not None
            else PlanStep(
                step_id=1,
                action="navigate",
                target=approach_to,
                description=f"Navigate to {name}",
            )
        )
        extra = [look, nav] if nth else [nav]
        said = (
            f"I couldn't reach the {name}, so I'll look around and approach it "
            "from another side."
            if nth
            else f"I couldn't reach the {name}, so I'll walk up to it again."
        )
    plan.steps = plan.steps[:index] + extra + plan.steps[index:]
    for i, s in enumerate(plan.steps, start=1):
        s.step_id = i
    plan.metadata.setdefault("in_mission_recovery", []).append(
        {"failure": kind, "action": action, "target": name}
    )
    return said
