"""
undo.py (backend/oversight)

Undo = the inverse actions of what a mission did, newest first, using the state
recorded just before each step (`task_state.undo_log`):

    open -> close          close -> open
    turn_on -> turn_off    turn_off -> turn_on
    pickup -> put it back where it was        place -> take it back where it was
    push, put_down -> can't be undone (listed, never attempted)

`FixedPlanner` runs such a plan through the normal orchestrator (traces, goal checks):
its success conditions are the "before" state, so the world decides whether the undo
worked.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from planner.models import Plan, PlanningResult, PlanStep, ValidationResult

IRREVERSIBLE = {"push", "put_down"}
_TOGGLE = {
    "open": "close",
    "close": "open",
    "turn_on": "turn_off",
    "turn_off": "turn_on",
}


def _kind(object_id: Optional[str]) -> Optional[str]:
    return object_id.split("|", 1)[0].lower() if object_id else None


def inverse_plan(
    undo_log: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
    """(steps, things that can't be undone, success predicates) for an undo.

    Steps undo the newest action first. Success is the state *before the mission*: for
    each object only the inverse of its earliest change counts (open-then-close of the
    fridge must end closed, not "open and closed")."""
    steps: List[Dict[str, Any]] = []
    cannot: List[str] = []
    success: Dict[Tuple[str, str], Dict[str, Any]] = {}
    returned: set = set()
    for entry in reversed(undo_log):
        action, target = entry["action"], entry.get("target")
        before = entry.get("before") or {}
        if action in IRREVERSIBLE:
            cannot.append(f"{action.replace('_', ' ')} the {_kind(target) or target}")
            continue
        if action in _TOGGLE:
            inverse = _TOGGLE[action]
            steps += [
                {"action": "navigate", "target": target},
                {"action": inverse, "target": target},
            ]
            kind = {
                "close": "is_closed",
                "open": "is_open",
                "turn_off": "toggled_off",
                "turn_on": "toggled_on",
            }[inverse]
            group = "door" if action in ("open", "close") else "power"
            success[(group, str(target))] = {"kind": kind, "object": target}
        elif action in ("pickup", "place"):
            if target in returned:
                continue  # already put back by undoing its later "place"
            home = before.get("parent")
            if not home:
                cannot.append(
                    f"put the {_kind(target) or target} back (I don't know where it was)"
                )
                continue
            if action == "place":
                steps += [
                    {"action": "navigate", "target": target},
                    {"action": "pickup", "target": target},
                ]
            steps += [
                {"action": "navigate", "target": home},
                {"action": "place", "target": target, "container": home},
            ]
            success[("where", str(target))] = {
                "kind": "in_receptacle",
                "object": target,
                "receptacle": home,
            }
            returned.add(target)
    # the executor only walks to things it has located first
    located: List[Dict[str, Any]] = []
    for s in steps:
        if s["action"] == "navigate":
            located.append({"action": "locate", "target": s["target"]})
        located.append(s)
    return located, cannot, list(success.values())


class FixedPlanner:
    """Runs a plan given in advance (undo). `pending[key]` = (steps, success)."""

    planner_type = "fixed"

    def __init__(self) -> None:
        self.pending: Dict[str, Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = {}

    def plan(self, task: Any, state: Any, memory_context: Any = None) -> PlanningResult:
        started = time.perf_counter()
        key = getattr(task, "estimated_goal", None) or ""
        steps, success = self.pending.get(key, ([], []))
        if not steps:
            return PlanningResult(
                success=False,
                plan=None,
                validation=None,
                errors=["There's nothing I can undo."],
                planner_type=self.planner_type,
                latency_ms=0.0,
            )
        plan = Plan(
            task_id=task.task_id or "",
            planner_type=self.planner_type,
            goal_summary={"goal": "undo"},
            steps=[
                PlanStep(
                    step_id=i,
                    action=s["action"],
                    target=s.get("target"),
                    parameters=(
                        {"container": s["container"]} if s.get("container") else {}
                    ),
                    description=f"{s['action']} {s.get('target') or ''}".strip(),
                )
                for i, s in enumerate(steps, start=1)
            ],
            metadata={"success_predicates": success, "undo": True},
        )
        return PlanningResult(
            success=True,
            plan=plan,
            validation=ValidationResult(valid=True),
            errors=[],
            planner_type=self.planner_type,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    replan = plan
