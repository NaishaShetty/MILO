"""
live_state.py (backend/planning_evaluation)

Purpose
-------
`GOAL_CHECKS` (`planner.validator`) only ever runs against the
planner's own simulated `WorldState` -- it verifies the plan *would*
satisfy the goal if every step ran with no error, never that it
actually did in the real scene (`orchestration.task_runner.
TaskRunResult.succeeded`/`execution.models.ExecutionRecord.status`
only report "did every dispatched step complete without a simulator
error"). This module closes that gap for the benchmark specifically:
`check_goal_live()` re-implements each `GOAL_CHECKS` predicate against
a live `Simulator.get_metadata()` snapshot taken AFTER execution,
using AI2-THOR's own ground-truth object fields (`isPickedUp`,
`parentReceptacles`, `isOpen`) instead of the planner's replayed
symbolic state.

Why this lives here, not in `planner.validator`
--------------------------------------------------
`validator.GOAL_CHECKS`'s contract is deliberately "predicate over a
`WorldState`," used at plan-validation time before anything executes
-- there is no live AI2-THOR metadata available yet at that point.
Re-purposing the same functions to also accept live metadata would
blur two different questions ("would this plan work" vs "did it
actually work") into one dict of callables; this benchmark-only
module keeps them separate while mirroring the exact same goal
semantics, object-for-object, so a result here is directly comparable
to what `validator.py` predicted before execution.

Known simplification: `tier1_locate` (`find`/`locate`/...)
------------------------------------------------------------
There is no physical "has been located" fact to check against live
metadata the way `is_held`/`location`/`is_open` have real analogues
(`isPickedUp`/`parentReceptacles`/`isOpen`) -- "locating" is a
perception event, and `Vision`'s `ground_world_state()` (Phase C) is
not wired into this evaluator (future work -- see `dataset/v1.0/
README.md`'s "Known limitations"). This module's live check for
`tier1_locate` therefore answers a narrower, honest question instead:
does an object of the named type exist anywhere in the live scene?
Every task in `dataset/v1.0/` was authored from a live metadata scan
(see `tasks.json`'s `generated_by` field), so this should always pass
in practice -- it exists to catch a regression, not to measure
locating accuracy.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from execution.resolver import ObjectResolver
from schemas.task import SingleTask

_resolver = ObjectResolver()


def _by_object_id(metadata: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        obj["objectId"]: obj
        for obj in (metadata.get("objects") or [])
        if isinstance(obj.get("objectId"), str)
    }


def _resolve(name: Optional[str], metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    object_id = _resolver.resolve(name, metadata)
    if object_id is None:
        return None
    return _by_object_id(metadata).get(object_id)


def check_goal_live(task: SingleTask, metadata: Dict[str, Any]) -> Optional[bool]:
    """
    Live-metadata analogue of `planner.validator.GOAL_CHECKS`. Returns
    `None` (unverifiable) for a goal this module has no live check
    for, matching `GOAL_CHECKS`'s own "open, not closed, goal
    vocabulary" convention.
    """
    goal = (task.goal or "").strip().lower()

    if goal in ("pick_up", "fetch", "deliver"):
        obj = _resolve(task.object, metadata)
        if obj is None:
            return False
        return bool(obj.get("isPickedUp"))

    if goal in ("store", "put_away", "pick_and_place", "place"):
        obj = _resolve(task.object, metadata)
        target = _resolve(task.target, metadata)
        if obj is None or target is None:
            return False
        parents = obj.get("parentReceptacles") or []
        return (not obj.get("isPickedUp")) and target.get("objectId") in parents

    if goal == "open":
        ref = _resolve(task.object or task.target, metadata)
        return bool(ref.get("isOpen")) if ref is not None else False

    if goal == "close":
        ref = _resolve(task.object or task.target, metadata)
        return (ref.get("isOpen") is False) if ref is not None else False

    if goal in ("find", "search_for", "locate", "inspect", "count"):
        ref = _resolve(task.object or task.target, metadata)
        return ref is not None

    return None
