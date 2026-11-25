"""
ambiguity.py (backend/oversight)

Asks one question instead of guessing:

- **Which one?** the command names an object type the room has more than one of
  ("bring me the cup" with two cups) and nothing (colour, size) picks one. Choices are
  the real objects, described by where they are ("the cup on the shelf"), each pinned to
  its simulator id so the answer is exact.
- **Where to?** the command needs a destination MILO doesn't know ("put the mug away"
  with no remembered place). Choices are the places in the room.

Each choice is `{"label", "instruction", "object_id"?}`: the client sends `instruction`
(and `object_id`, if any) back as a new task.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from execution.resolver import ObjectResolver

_resolver = ObjectResolver()


def display_name(name: Optional[str]) -> str:
    """ "Cup|2" -> "cup"; anything else unchanged."""
    if name and "|" in name:
        return name.split("|", 1)[0].lower()
    return name or ""


def _where(obj: Mapping[str, Any], objects: List[Mapping[str, Any]]) -> str:
    parents = obj.get("parentReceptacles") or []
    if parents:
        parent = next((o for o in objects if o.get("objectId") == parents[0]), None)
        if parent is not None:
            kind = str(parent.get("objectType", "")).lower()
            prep = "in" if parent.get("openable") else "on"
            return f"{prep} the {kind}"
    return f"{float(obj.get('distance', 0)):.1f} m away"


def same_kind(name: str, metadata: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Every live object the resolver would consider a match for `name`."""
    objects = list((metadata or {}).get("objects") or [])
    first = _resolver.resolve(name, dict(metadata or {}))
    if first is None:
        return []
    kind = next(
        (o.get("objectType") for o in objects if o.get("objectId") == first), None
    )
    return [o for o in objects if o.get("objectType") == kind]


def which_one(
    task: Any, instruction: str, metadata: Optional[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    """A "which one?" question for `task.object`, or None when it is unambiguous."""
    name = getattr(task, "object", None)
    if not name or "|" in name or getattr(task, "attributes", None) is not None:
        return None
    matches = same_kind(name, metadata or {})
    if len(matches) < 2:
        return None
    objects = list((metadata or {}).get("objects") or [])
    kind = display_name(str(matches[0].get("objectType", name))).lower()
    choices = [
        {
            "label": f"the {kind} {_where(o, objects)}",
            "instruction": instruction,
            "object_id": o.get("objectId"),
        }
        for o in sorted(matches, key=lambda o: float(o.get("distance", 0)))
    ]
    return {
        "kind": "clarify",
        "message": f"I can see {len(matches)} {kind}s. Which one do you mean?",
        "choices": choices,
        "details": {"slot": "object"},
    }


def where_to(obj: str, metadata: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Destination choices for "put the X away" when MILO doesn't know the place."""
    out = []
    for o in (metadata or {}).get("objects") or []:
        if o.get("pickupable") or o.get("isToggled") is not None:
            continue
        place = str(o.get("objectType", "")).lower()
        prep = "in" if o.get("openable") else "on"
        out.append(
            {
                "label": f"{prep} the {place}",
                "instruction": f"put the {obj} {prep} the {place}",
            }
        )
    return out
