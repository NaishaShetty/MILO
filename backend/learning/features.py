"""
features.py (backend/learning)

The ONE place a world snapshot is turned into features. Training reads rows
written with these functions and (Phase B) serving calls the same ones, so
there is no train/serve skew.

`world_features(metadata, target)` -- facts about one target object from
simulator metadata: is it visible, how far, open/closed, switched on, is the
robot holding something, and a `reachable` flag (visible and within arm's
reach). `failure_type(...)` maps an executor error to a label.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from execution.resolver import ObjectResolver
from learning.schema import FAILURE_TYPES

#: AI2-THOR's interaction range; anything farther is treated as out of reach.
REACH_METERS = 1.5

_resolver = ObjectResolver()


def world_features(
    metadata: Optional[Dict[str, Any]], target: Optional[str]
) -> Dict[str, Any]:
    """Numeric/categorical facts about `target` (and the hand) right now."""
    meta = metadata or {}
    held = meta.get("inventoryObjects") or []
    out: Dict[str, Any] = {
        "target_found": 0,
        "visible": 0,
        "distance": -1.0,
        "is_open": -1,  # -1 unknown / not openable
        "is_on": -1,
        "reachable": 0,
        "held": (
            str(
                held[0].get("objectType")
                or str(held[0].get("objectId", "")).split("|")[0]
            ).lower()
            if held
            else "none"
        ),
        "object_class": (target or "none").strip().lower(),
    }
    if not target:
        return out
    object_id = _resolver.resolve(target, meta)
    obj = next(
        (o for o in meta.get("objects") or [] if o.get("objectId") == object_id), None
    )
    if obj is None:
        return out
    distance = float(obj.get("distance", -1.0))
    visible = bool(obj.get("visible", True))
    out.update(
        target_found=1,
        visible=int(visible),
        distance=distance,
        is_open=-1 if obj.get("isOpen") is None else int(bool(obj["isOpen"])),
        is_on=-1 if obj.get("isToggled") is None else int(bool(obj["isToggled"])),
        reachable=int(visible and 0 <= distance <= REACH_METERS),
    )
    return out


def failure_type(
    error_code: Optional[str], message: Optional[str], success: bool
) -> str:
    """One of `schema.FAILURE_TYPES`."""
    if success:
        return "none"
    code = (error_code or "").upper()
    text = (message or "").lower()
    if code == "ACTION_TIMEOUT" or "timed out" in text or "timeout" in text:
        return "timeout"
    if code == "OBJECT_NOT_FOUND" or "no live object" in text:
        return "wrong_object"
    if "visible" in text:
        return "not_visible"
    if code == "OBJECT_NOT_REACHABLE" or "reach" in text:
        return "not_reachable"
    if code == "NAVIGATION_FAILED" or "blocked" in text or "path" in text:
        return "blocked"
    return "other"


assert "none" in FAILURE_TYPES
