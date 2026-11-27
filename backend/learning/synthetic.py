"""
synthetic.py (backend/learning)

A fast, headless, deterministic stand-in for the AI2-THOR `Simulator`, with
*controlled failure injection*, used to generate the first training dataset
(AI2-THOR itself needs a GPU/display and ~seconds per step; see
`learning/README.md` for how to point the generator at the real thing).

It implements exactly the surface the execution layer calls
(`get_metadata`, `navigate_to`, `navigate_home`, `pickup_object`,
`put_object`, `open_object`, `close_object`, `toggle_object_on/off`,
`drop_held_object`), with AI2-THOR-shaped metadata, and a few behaviours
that matter for learning: interaction needs the object to be visible and
within reach, `navigate_to` brings you next to the target, objects have a
parent receptacle that `put` updates.

Fault kinds (`faults.kind`):
- `blocked_path`   `navigate_to` fails ("path blocked") `times` times, then works;
- `out_of_reach`   the target stays out of reach after navigation `times` times;
- `door_stuck`     `open` fails `times` times;
- `timeout`        an action raises `TimeoutError` `times` times;
- `wrong_detection` the target is reported not visible after navigation `times` times;
- `missing_object` the target is not in the scene at all (the executor cannot find it).
`times=99` makes a fault effectively permanent. A fault `target` is an objectType
(lower case), or an exact objectId ("Shelf|1") to hit one object of a type.

Out of view (opt-in, for the benchmark's memory tier): an object marked `"hidden": True`
is not visible, can't be walked to directly and isn't revealed by looking around; it
appears only when MILO walks to the receptacle it is actually on. Knowing (remembering)
where it usually is is then the difference between finding it and not.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

ITEMS = [
    "Apple",
    "Mug",
    "Book",
    "Bowl",
    "Cup",
    "Plate",
    "Egg",
    "Bottle",
    "Potato",
    "Tomato",
]
RECEPTACLES = [
    ("Fridge", True),
    ("Table", False),
    ("CounterTop", False),
    ("Shelf", False),
    ("Desk", False),
    ("Drawer", True),
    ("Cabinet", True),
    ("Sofa", False),
]
TOGGLES = ["LightSwitch", "Faucet", "Toaster", "Television"]
FAULT_KINDS = [
    "blocked_path",
    "out_of_reach",
    "door_stuck",
    "timeout",
    "wrong_detection",
    "missing_object",
]


@dataclass
class Faults:
    kind: str = "none"
    target: Optional[str] = None  # objectType (lower) the fault applies to
    times: int = 1


class FakeEvent:
    def __init__(self, metadata: Dict[str, Any]) -> None:
        self.metadata = metadata


def make_scene(scene_id: str, seed: int) -> List[Dict[str, Any]]:
    rng = random.Random(f"{scene_id}-{seed}")
    objects: List[Dict[str, Any]] = []
    receptacles = rng.sample(RECEPTACLES, rng.randint(4, 6))
    for name, openable in receptacles:
        obj: Dict[str, Any] = {
            "objectId": f"{name}|1",
            "objectType": name,
            "distance": round(rng.uniform(1.0, 4.5), 2),
            "visible": True,
            "pickupable": False,
        }
        if openable:
            obj.update(openable=True, isOpen=False)
        objects.append(obj)
    for name in rng.sample(TOGGLES, rng.randint(1, 3)):
        objects.append(
            {
                "objectId": f"{name}|1",
                "objectType": name,
                "distance": round(rng.uniform(1.0, 4.0), 2),
                "visible": True,
                "pickupable": False,
                "isToggled": rng.random() < 0.3,
            }
        )
    for name in rng.sample(ITEMS, rng.randint(3, 6)):
        parent = rng.choice([r for r in receptacles if not r[1]] or receptacles)[0]
        objects.append(
            {
                "objectId": f"{name}|1",
                "objectType": name,
                "distance": round(rng.uniform(0.6, 4.0), 2),
                "visible": True,
                "pickupable": True,
                "parentReceptacles": [f"{parent}|1"],
            }
        )
    return objects


class SyntheticSimulator:
    def __init__(
        self, objects: List[Dict[str, Any]], faults: Optional[Faults] = None
    ) -> None:
        faults = faults or Faults()
        if faults.kind == "missing_object" and faults.target:
            objects = [o for o in objects if o["objectType"].lower() != faults.target]
        self.objects = objects
        for o in self.objects:
            if o.get("hidden"):
                o["visible"] = False
        self.inventory_objects: List[Dict[str, Any]] = []
        self.faults = faults or Faults()
        self._fault_hits = 0
        self.clock_s = 0.0  # simulated time spent so far
        self._current = "navigate"
        self.calls: List[str] = []

    # -- helpers -----------------------------------------------------------
    def _obj(self, object_id: str) -> Optional[Dict[str, Any]]:
        return next((o for o in self.objects if o["objectId"] == object_id), None)

    def _is_fault_target(self, obj: Optional[Dict[str, Any]]) -> bool:
        return (
            obj is not None
            and self.faults.kind != "none"
            and (
                self.faults.target is None
                or obj["objectType"].lower() == self.faults.target
                or obj["objectId"] == self.faults.target
            )
        )

    def _fault_active(self) -> bool:
        return self._fault_hits < self.faults.times

    #: Simulated seconds per action; a failure costs extra, a timeout a lot.
    _SECONDS = {
        "navigate": 4.0,
        "pickup": 1.5,
        "put": 1.5,
        "open": 1.0,
        "close": 1.0,
        "toggle": 1.0,
    }

    def _event(self, ok: bool, error: str = "") -> FakeEvent:
        seconds = self._SECONDS.get(self._current, 1.0) * (1.0 if ok else 1.6)
        self.clock_s += seconds
        return FakeEvent(
            {
                "simDurationMs": seconds * 1000.0,
                "lastActionSuccess": ok,
                "errorMessage": error,
                "objects": self.objects,
                "inventoryObjects": self.inventory_objects,
            }
        )

    def get_metadata(self) -> Dict[str, Any]:
        return {"objects": self.objects, "inventoryObjects": self.inventory_objects}

    def _maybe_timeout(self, obj: Optional[Dict[str, Any]]) -> None:
        if (
            self.faults.kind == "timeout"
            and self._is_fault_target(obj)
            and self._fault_active()
        ):
            self._fault_hits += 1
            self.clock_s += 10.0
            raise TimeoutError("simulator call timed out")

    # -- actions -----------------------------------------------------------
    def navigate_to(self, object_id: str) -> FakeEvent:
        self._current = "navigate"
        obj = self._obj(object_id)
        self._maybe_timeout(obj)
        if obj is None:
            return self._event(False, "object not found")
        if obj.get("hidden"):
            return self._event(False, "object not visible from here")
        if (
            self.faults.kind == "blocked_path"
            and self._is_fault_target(obj)
            and self._fault_active()
        ):
            self._fault_hits += 1
            return self._event(False, "path blocked")
        for other in self.objects:
            other["distance"] = round(abs(other["distance"] - obj["distance"]) + 1.8, 2)
            if other.get("hidden") and object_id in (
                other.get("parentReceptacles") or []
            ):
                other["hidden"] = False  # walked to where it really is: now in view
            other["visible"] = not other.get("hidden")
        obj["distance"] = 0.8
        if self._is_fault_target(obj) and self._fault_active():
            if self.faults.kind == "out_of_reach":
                self._fault_hits += 1
                obj["distance"] = 2.6
            elif self.faults.kind == "wrong_detection":
                self._fault_hits += 1
                obj["visible"] = False
        return self._event(True)

    def navigate_home(self) -> FakeEvent:
        self._current = "navigate"
        return self._event(True)

    def _interactable(
        self, obj: Optional[Dict[str, Any]], name: str
    ) -> Optional[FakeEvent]:
        if obj is None:
            return self._event(False, f"cannot {name}: object not found")
        self._maybe_timeout(obj)
        if not obj.get("visible", True):
            return self._event(False, f"cannot {name}: object not visible")
        if obj["distance"] > 1.5:
            return self._event(False, f"cannot {name}: object not reachable")
        return None

    # What an object can do, as AI2-THOR enforces it. Until 2026-11-27 the synthetic
    # simulator allowed every action on every object, so "pick up the fridge" or "open
    # the apple" succeeded here (benchmark tier "impossible" found it). An object with
    # no flag at all (hand-built test scenes) keeps the old, permissive behaviour where
    # that is safe: pickupable unless it says otherwise (`planner.affordances`).
    def _cannot(self, obj: Dict[str, Any], name: str) -> Optional[FakeEvent]:
        from planner.affordances import can_open, can_pick_up, can_switch, is_receptacle

        kind = obj.get("objectType", "object")
        if name == "pick up" and not can_pick_up(obj):
            return self._event(False, f"cannot pick up: {kind} is not pickupable")
        if name in ("open", "close") and not can_open(obj):
            return self._event(False, f"cannot {name}: {kind} is not openable")
        if name == "toggle" and not can_switch(obj):
            return self._event(
                False, f"cannot toggle: {kind} can't be switched on or off"
            )
        if name == "put" and not is_receptacle(obj):
            return self._event(False, f"cannot put: {kind} is not a receptacle")
        return None

    def pickup_object(self, object_id: str) -> FakeEvent:
        self._current = "pickup"
        obj = self._obj(object_id)
        bad = self._interactable(obj, "pick up")
        if bad is not None:
            return bad
        assert obj is not None
        refused = self._cannot(obj, "pick up")
        if refused is not None:
            return refused
        if self.inventory_objects:
            return self._event(False, "hand is full")
        self.inventory_objects.append(
            {"objectId": object_id, "objectType": obj["objectType"]}
        )
        obj["isPickedUp"] = True
        obj["parentReceptacles"] = None
        return self._event(True)

    def put_object(self, object_id: str) -> FakeEvent:
        self._current = "put"
        target = self._obj(object_id)
        bad = self._interactable(target, "put")
        if bad is not None:
            return bad
        assert target is not None
        refused = self._cannot(target, "put")
        if refused is not None:
            return refused
        for held in self.inventory_objects:
            item = self._obj(held["objectId"])
            if item is not None:
                item["isPickedUp"] = False
                item["parentReceptacles"] = [object_id]
        self.inventory_objects = []
        return self._event(True)

    def open_object(self, object_id: str) -> FakeEvent:
        self._current = "open"
        obj = self._obj(object_id)
        bad = self._interactable(obj, "open")
        if bad is not None:
            return bad
        assert obj is not None
        refused = self._cannot(obj, "open")
        if refused is not None:
            return refused
        if (
            self.faults.kind == "door_stuck"
            and self._is_fault_target(obj)
            and self._fault_active()
        ):
            self._fault_hits += 1
            return self._event(False, "door is stuck")
        obj["isOpen"] = True
        return self._event(True)

    def close_object(self, object_id: str) -> FakeEvent:
        self._current = "close"
        obj = self._obj(object_id)
        bad = self._interactable(obj, "close")
        if bad is not None:
            return bad
        assert obj is not None
        refused = self._cannot(obj, "close")
        if refused is not None:
            return refused
        obj["isOpen"] = False
        return self._event(True)

    def _toggle(self, object_id: str, on: bool) -> FakeEvent:
        self._current = "toggle"
        obj = self._obj(object_id)
        bad = self._interactable(obj, "toggle")
        if bad is not None:
            return bad
        assert obj is not None
        refused = self._cannot(obj, "toggle")
        if refused is not None:
            return refused
        obj["isToggled"] = on
        return self._event(True)

    def toggle_object_on(self, object_id: str) -> FakeEvent:
        return self._toggle(object_id, True)

    def toggle_object_off(self, object_id: str) -> FakeEvent:
        return self._toggle(object_id, False)

    def push_object(self, object_id: str) -> FakeEvent:
        obj = self._obj(object_id)
        refused = self._interactable(obj, "push")
        if refused is not None:
            return refused
        assert obj is not None
        obj["distance"] = round(float(obj["distance"]) + 0.3, 2)
        return self._event(True)

    def look_around(self) -> FakeEvent:
        for o in self.objects:
            o["visible"] = not o.get("hidden")
        return self._event(True)

    def drop_held_object(self) -> FakeEvent:
        self._current = "put"
        self.inventory_objects = []
        return self._event(True)
