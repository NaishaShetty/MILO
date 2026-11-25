"""
predicates.py (backend/verification)

Checkable goal conditions. Each `Predicate` reads the simulator's own object
metadata (AI2-THOR's `objects` / `inventoryObjects`, or the synthetic simulator's
copy of them) and says whether it holds and, if not, why -- so "did it work?" is
answered by the world, not by a model's or a planner's opinion.

Kinds
-----
    held(object)                  the robot is holding it
    hand_empty()                  the robot holds nothing
    in_receptacle(object, place)  it sits in/on the receptacle
    is_open(object) / is_closed(object)
    toggled_on(object) / toggled_off(object)
    visible(object)               it is in view
    near(object)                  it is within arm's reach

`goal_predicates(task)` gives the predicates that define success for each task-library
goal; `check_all` evaluates a list. Predicates round-trip through `to_dict`/`from_dict`
so a planner can state them as JSON.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from execution.resolver import ObjectResolver

REACH_METERS = 1.5
KINDS = (
    "held",
    "hand_empty",
    "in_receptacle",
    "is_open",
    "is_closed",
    "toggled_on",
    "toggled_off",
    "visible",
    "near",
)
_resolver = ObjectResolver()


@dataclass(frozen=True)
class PredicateResult:
    predicate: "Predicate"
    ok: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.predicate.to_dict(),
            "text": self.predicate.describe(),
            "ok": self.ok,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Predicate:
    kind: str
    object: Optional[str] = None
    receptacle: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown predicate kind {self.kind!r}")
        if self.kind != "hand_empty" and not self.object:
            raise ValueError(f"predicate {self.kind!r} needs an object")
        if self.kind == "in_receptacle" and not self.receptacle:
            raise ValueError("in_receptacle needs a receptacle")

    # -- serialisation ---------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Predicate":
        return cls(
            kind=str(data["kind"]),
            object=data.get("object"),
            receptacle=data.get("receptacle"),
        )

    def describe(self) -> str:
        o, r = self.object, self.receptacle
        return {
            "held": f"holding the {o}",
            "hand_empty": "hands are empty",
            "in_receptacle": f"the {o} is in/on the {r}",
            "is_open": f"the {o} is open",
            "is_closed": f"the {o} is closed",
            "toggled_on": f"the {o} is on",
            "toggled_off": f"the {o} is off",
            "visible": f"the {o} is in view",
            "near": f"next to the {o}",
        }[self.kind]

    # -- evaluation -----------------------------------------------------------------

    def check(self, metadata: Optional[Mapping[str, Any]]) -> PredicateResult:
        meta: Dict[str, Any] = dict(metadata or {})
        held = meta.get("inventoryObjects") or []
        held_ids = {str(h.get("objectId")) for h in held}
        if self.kind == "hand_empty":
            return self._result(not held, "still holding something")
        object_id = _resolver.resolve(self.object, meta)
        obj = _find(meta, object_id)
        if self.kind == "held":
            ok = object_id is not None and object_id in held_ids
            return self._result(ok, f"not holding the {self.object}")
        if obj is None:
            return self._result(False, f"I can't find the {self.object}")
        if self.kind == "in_receptacle":
            place_id = _resolver.resolve(self.receptacle, meta)
            parents = [str(p) for p in (obj.get("parentReceptacles") or [])]
            ok = place_id is not None and place_id in parents
            return self._result(
                ok, f"the {self.object} is not in/on the {self.receptacle}"
            )
        if self.kind in ("is_open", "is_closed"):
            state = obj.get("isOpen")
            if state is None:
                return self._result(False, f"the {self.object} can't open or close")
            want = self.kind == "is_open"
            return self._result(
                bool(state) == want,
                f"the {self.object} is {'closed' if want else 'open'}",
            )
        if self.kind in ("toggled_on", "toggled_off"):
            state = obj.get("isToggled")
            if state is None:
                return self._result(False, f"the {self.object} can't switch on or off")
            want = self.kind == "toggled_on"
            return self._result(
                bool(state) == want, f"the {self.object} is {'off' if want else 'on'}"
            )
        if self.kind == "visible":
            return self._result(
                bool(obj.get("visible", False)), f"the {self.object} is not in view"
            )
        distance = float(obj.get("distance", -1.0))
        return self._result(
            0 <= distance <= REACH_METERS, f"not close enough to the {self.object}"
        )

    def _result(self, ok: bool, reason_if_not: str) -> PredicateResult:
        return PredicateResult(self, ok, "" if ok else reason_if_not)


def _find(meta: Mapping[str, Any], object_id: Optional[str]) -> Optional[Dict]:
    if object_id is None:
        return None
    return next(
        (o for o in meta.get("objects") or [] if o.get("objectId") == object_id), None
    )


def check_all(
    predicates: Sequence[Predicate], metadata: Optional[Mapping[str, Any]]
) -> List[PredicateResult]:
    return [p.check(metadata) for p in predicates]


def goal_predicates(task: Any) -> List[Predicate]:
    """What success means for a task-library goal (`[]` = nothing checkable)."""
    goal = (getattr(task, "goal", None) or "").lower()
    obj = getattr(task, "object", None)
    target = getattr(task, "target", None) or getattr(task, "target_location", None)
    if goal in ("fetch", "pick_up") and obj:
        return [Predicate("held", obj)]
    if goal in ("store", "place") and obj and target:
        return [Predicate("in_receptacle", obj, target), Predicate("hand_empty")]
    if goal == "deliver" and obj and target:
        return [Predicate("held", obj), Predicate("near", target)]
    if goal in ("open", "close") and (obj or target):
        return [Predicate("is_open" if goal == "open" else "is_closed", obj or target)]
    if goal in ("turn_on", "turn_off") and obj:
        return [Predicate("toggled_on" if goal == "turn_on" else "toggled_off", obj)]
    if goal in ("find", "locate", "search_for") and obj:
        return [Predicate("visible", obj)]
    if goal == "navigate_to" and target:
        return [Predicate("near", target)]
    return []
