"""
composite.py (backend/orchestration)

Purpose
-------
Expands the two *composite* library tasks -- "clear the table" and "tidy
up" -- into ordinary single-object sub-goals once MILO can look at the
room. A `SingleTask(goal="clear_table", source_location="table",
target_location="counter")` says *what* is wanted, not *which objects*;
this module reads the simulator's metadata (and, for tidy-up, MILO's
memory of where things usually live) and returns one `place`/`store`
sub-goal per object. The planners then compose those exactly like any
other multi-object task (`Planner.plan_multi`).

Kept free of any simulator or planner import: input is a plain AI2-THOR
style metadata dict (`objects`: list of dicts with `objectId`,
`objectType`, `pickupable`, `isPickedUp`, `parentReceptacles` /
`parentReceptacle`, `openable`), so it is unit-testable with a few dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from schemas.task import SingleTask

#: Safety cap: one request never turns into an unbounded pile of work.
MAX_SUBTASKS = 10


@dataclass
class Expansion:
    subtasks: List[SingleTask] = field(default_factory=list)
    #: Set when there is nothing to do (or why), shown to the user as-is.
    message: Optional[str] = None


def _type(obj: Dict[str, Any]) -> str:
    return str(obj.get("objectType") or "").strip().lower()


def _parents(obj: Dict[str, Any]) -> List[str]:
    raw = obj.get("parentReceptacles")
    if raw:
        return [str(x) for x in raw]
    single = obj.get("parentReceptacle")
    return [str(single)] if single else []


def _by_id(objects: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(o.get("objectId")): o for o in objects}


def _matches(obj_type: str, name: str) -> bool:
    name = name.strip().lower().replace(" ", "")
    obj_type = obj_type.replace(" ", "")
    return bool(name) and (obj_type == name or name in obj_type)


def _movable(objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        o
        for o in objects
        if o.get("pickupable") is not False  # unknown counts as movable
        and not o.get("isPickedUp")
        and _parents(o)
    ]


def _place_goal(
    obj_name: str, dest_name: str, objects: List[Dict[str, Any]]
) -> SingleTask:
    """`store` (open/close the destination) if it is openable, else `place`."""
    dest = next((o for o in objects if _matches(_type(o), dest_name)), None)
    goal = "store" if dest is not None and dest.get("openable") else "place"
    return SingleTask(goal=goal, object=obj_name, target=dest_name)


def expand_clear_table(task: SingleTask, metadata: Dict[str, Any]) -> Expansion:
    source = (task.source_location or task.object or "table").strip().lower()
    dest = (task.target_location or task.target or "").strip().lower()
    if not dest:
        return Expansion(message=f"Where should I put the things from the {source}?")
    objects: List[Dict[str, Any]] = list(metadata.get("objects") or [])
    by_id = _by_id(objects)
    source_ids = {str(o.get("objectId")) for o in objects if _matches(_type(o), source)}
    if not source_ids:
        return Expansion(message=f"I can't see a {source} here.")

    subtasks: List[SingleTask] = []
    for obj in _movable(objects):
        if _matches(_type(obj), source) or _matches(_type(obj), dest):
            continue
        if source_ids & set(_parents(obj)):
            subtasks.append(_place_goal(_type(obj), dest, objects))
        if len(subtasks) >= MAX_SUBTASKS:
            break
    del by_id
    if not subtasks:
        return Expansion(message=f"The {source} is already clear.")
    return Expansion(subtasks=subtasks)


def expand_tidy_up(
    task: SingleTask,
    metadata: Dict[str, Any],
    usual_places: Dict[str, Tuple[str, str]],
) -> Expansion:
    """One sub-goal for every object MILO knows a usual place for and that is
    currently somewhere else."""
    if not usual_places:
        return Expansion(
            message="I don't know where things usually go yet. Tell me, for "
            'example "the mug goes on the shelf", and I\'ll tidy up next time.'
        )
    objects: List[Dict[str, Any]] = list(metadata.get("objects") or [])
    by_id = _by_id(objects)
    subtasks: List[SingleTask] = []
    seen = set()
    for obj in _movable(objects):
        name = _type(obj)
        known = usual_places.get(name)
        if known is None or name in seen:
            continue
        place, _relation = known
        parent_types = [_type(by_id[p]) for p in _parents(obj) if p in by_id]
        if any(_matches(pt, place) for pt in parent_types):
            continue  # already where it belongs
        seen.add(name)
        subtasks.append(_place_goal(name, place, objects))
        if len(subtasks) >= MAX_SUBTASKS:
            break
    if not subtasks:
        return Expansion(message="Everything is already where it usually lives.")
    return Expansion(subtasks=subtasks)


def expand_composite(
    task: SingleTask,
    metadata: Dict[str, Any],
    usual_places: Optional[Dict[str, Tuple[str, str]]] = None,
) -> Expansion:
    goal = (task.goal or "").strip().lower()
    if goal == "clear_table":
        return expand_clear_table(task, metadata)
    if goal == "tidy_up":
        return expand_tidy_up(task, metadata, usual_places or {})
    return Expansion(message=f"I don't know how to expand '{goal}'.")
