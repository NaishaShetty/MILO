"""
affordances.py (backend/planner)

What an object in the scene can do (be picked up, opened, switched, hold things), read
from simulator metadata, and a check that a plan doesn't ask an object to do something
it can't. Used in two places so they never disagree:

- `orchestration.orchestrator` checks a new plan before acting, so "pick up the fridge"
  is refused up front instead of failing halfway after walking over;
- `learning.synthetic.SyntheticSimulator` refuses the same actions, as AI2-THOR does.

AI2-THOR metadata carries `pickupable`, `openable`, `toggleable` and `receptacle` on
every object. The synthetic home's objects carry `pickupable` always, `openable` only on
things that open, and `isToggled` only on switches; receptacles are inferred. An object
with no flag is given the benefit of the doubt, and an object the scene doesn't show at
all is never judged here (it may simply be out of view).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

#: Pickupable things that are also receptacles in AI2-THOR (an apple can go in a bowl).
CONTAINER_ITEMS = {"bowl", "plate", "mug", "cup", "pot", "pan", "box"}


#: Keys that say what an object can do. An object with none of them (a hand-built test
#: scene) says nothing about itself, so nothing is ruled out for it.
_FLAGS = ("pickupable", "openable", "toggleable", "receptacle", "isToggled")


def _unflagged(obj: Dict[str, Any]) -> bool:
    return not any(k in obj for k in _FLAGS)


def can_pick_up(obj: Dict[str, Any]) -> bool:
    return obj.get("pickupable") is not False


def can_open(obj: Dict[str, Any]) -> bool:
    return _unflagged(obj) or bool(obj.get("openable"))


def can_switch(obj: Dict[str, Any]) -> bool:
    if _unflagged(obj):
        return True
    if "toggleable" in obj:
        return bool(obj["toggleable"])
    return "isToggled" in obj


def is_receptacle(obj: Dict[str, Any]) -> bool:
    if _unflagged(obj):
        return True
    if "receptacle" in obj:
        return bool(obj["receptacle"])
    if _norm(str(obj.get("objectType", ""))) in CONTAINER_ITEMS:
        return True
    # furniture: not pickupable and not a switch
    return obj.get("pickupable") is False and "isToggled" not in obj


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _matching(
    objects: Iterable[Dict[str, Any]], name: Optional[str]
) -> List[Dict[str, Any]]:
    if not name:
        return []
    by_id = [o for o in objects if o.get("objectId") == name]
    if by_id:
        return by_id
    wanted = _norm(name.split("|")[0])
    return [o for o in objects if _norm(str(o.get("objectType", ""))) == wanted]


#: action -> (capability check, words for "I can't ... : it ...")
_NEEDS = {
    "pickup": (can_pick_up, "pick up", "it can't be picked up"),
    "open": (can_open, "open", "it doesn't open"),
    "close": (can_open, "close", "it doesn't open or close"),
    "turn_on": (can_switch, "switch on", "it can't be switched on or off"),
    "turn_off": (can_switch, "switch off", "it can't be switched on or off"),
}


def impossible_step(
    steps: Iterable[Any], metadata: Optional[Dict[str, Any]]
) -> Optional[str]:
    """A plain reason the plan can't work, from the first step that asks an object in
    the scene to do something none of its kind can; None if nothing is known to be
    impossible. `steps` are `PlanStep`s (action, target, parameters)."""
    objects = list((metadata or {}).get("objects") or [])
    if not objects:
        return None
    for step in steps:
        action = getattr(step, "action", None)
        target = getattr(step, "target", None)
        if action in _NEEDS:
            check, verb, why = _NEEDS[action]
            found = _matching(objects, target)
            if found and not any(check(o) for o in found):
                return f"I can't {verb} the {target}: {why}"
        if action == "place":
            container = (getattr(step, "parameters", None) or {}).get("container")
            found = _matching(objects, container)
            if found and not any(is_receptacle(o) for o in found):
                return f"I can't put the {target} on or in the {container}: nothing can go there"
    return None
