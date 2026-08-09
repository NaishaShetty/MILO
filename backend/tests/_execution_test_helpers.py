"""
_execution_test_helpers.py

Purpose
-------
Shared, deterministic fakes for the Phase 5 Execution test suite
(`test_execution_*.py`, `test_api_execution.py`). Not named `test_*.py`
so pytest never collects it as a test module itself -- mirrors
`test_simulator_lifecycle.py`'s "monkeypatch/fake the AI2-THOR
boundary, never launch Unity in a unit test" discipline, but centralized
here since multiple execution test modules need the identical fake
`Simulator` surface (`move_ahead`, `pickup_object`, `get_metadata`, ...).

`FakeSimulator` implements every method `execution.dispatcher.
ActionDispatcher` and `execution.controller.ExecutionController` call
on a `Simulator`, backed by a tiny in-memory scene (`objects`,
`inventoryObjects`) it mutates in response to actions -- close enough
to real AI2-THOR semantics (`lastActionSuccess`, `isOpen`,
`inventoryObjects`) for `validator.ResultValidator`'s postcondition
checks to exercise both the success and failure paths meaningfully,
without ever importing `ai2thor`.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


class FakeEvent:
    """Stand-in for an AI2-THOR `Event` -- the only attribute this
    project's code ever reads off one is `.metadata`."""

    def __init__(self, metadata: Dict[str, Any]) -> None:
        self.metadata = metadata


class FakeSimulator:
    """
    A minimal, in-memory stand-in for `simulator.simulator.Simulator`.

    `objects` is a list of AI2-THOR-shaped object dicts (`objectId`,
    `objectType`, `distance`, `isOpen`); `inventoryObjects` mirrors
    AI2-THOR's own held-object list. `fail_actions` (a set of
    `ActionType.value` strings) makes the named action always report
    `lastActionSuccess=False` -- used to exercise failure paths.
    `hooks` (action name -> callable) lets a test run arbitrary code
    (e.g. blocking on a `threading.Event`, or raising) when an action
    is dispatched, for retry/timeout/cancellation tests.
    """

    def __init__(
        self,
        objects: Optional[List[Dict[str, Any]]] = None,
        *,
        fail_actions: Optional[set] = None,
        hooks: Optional[Dict[str, Callable[[], None]]] = None,
    ) -> None:
        self.objects: List[Dict[str, Any]] = objects if objects is not None else []
        self.inventory_objects: List[Dict[str, Any]] = []
        self._fail_actions = fail_actions or set()
        self._hooks = hooks or {}
        self.calls: List[Dict[str, Any]] = []

    # -- introspection helpers --------------------------------------

    def _object(self, object_id: str) -> Optional[Dict[str, Any]]:
        return next((o for o in self.objects if o.get("objectId") == object_id), None)

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "objects": self.objects,
            "inventoryObjects": self.inventory_objects,
            "lastActionSuccess": True,
            "errorMessage": "",
            "agent": {"position": {"x": 0, "y": 0, "z": 0}},
        }

    # -- action surface (mirrors Simulator) --------------------------

    def _record_and_maybe_hook(self, name: str, **kwargs: Any) -> None:
        self.calls.append({"action": name, **kwargs})
        hook = self._hooks.get(name)
        if hook is not None:
            hook()

    def _simple_event(self, name: str) -> FakeEvent:
        self._record_and_maybe_hook(name)
        success = name not in self._fail_actions
        return FakeEvent({"lastActionSuccess": success, "errorMessage": ""})

    def move_ahead(self) -> FakeEvent:
        return self._simple_event("move_ahead")

    def move_back(self) -> FakeEvent:
        return self._simple_event("move_back")

    def turn_left(self) -> FakeEvent:
        return self._simple_event("rotate_left")

    def turn_right(self) -> FakeEvent:
        return self._simple_event("rotate_right")

    def look_up(self) -> FakeEvent:
        return self._simple_event("look_up")

    def look_down(self) -> FakeEvent:
        return self._simple_event("look_down")

    def navigate_to(self, object_id: str) -> FakeEvent:
        self._record_and_maybe_hook("navigate", object_id=object_id)
        obj = self._object(object_id)
        success = obj is not None and "navigate" not in self._fail_actions
        return FakeEvent(
            {
                "lastActionSuccess": success,
                "errorMessage": "" if success else "object not reachable",
                "objects": self.objects,
            }
        )

    def pickup_object(self, object_id: str) -> FakeEvent:
        self._record_and_maybe_hook("pickup", object_id=object_id)
        obj = self._object(object_id)
        success = obj is not None and "pickup" not in self._fail_actions
        if success:
            self.inventory_objects.append({"objectId": object_id})
        return FakeEvent(
            {
                "lastActionSuccess": success,
                "errorMessage": "" if success else "cannot pick up object",
                "objects": self.objects,
                "inventoryObjects": self.inventory_objects,
            }
        )

    def put_object(self, object_id: str) -> FakeEvent:
        self._record_and_maybe_hook("put", object_id=object_id)
        success = "put" not in self._fail_actions
        if success:
            self.inventory_objects = []
        return FakeEvent(
            {
                "lastActionSuccess": success,
                "errorMessage": "" if success else "cannot put object",
                "objects": self.objects,
                "inventoryObjects": self.inventory_objects,
            }
        )

    def open_object(self, object_id: str) -> FakeEvent:
        self._record_and_maybe_hook("open", object_id=object_id)
        obj = self._object(object_id)
        success = obj is not None and "open" not in self._fail_actions
        if success and obj is not None:
            obj["isOpen"] = True
        return FakeEvent(
            {
                "lastActionSuccess": success,
                "errorMessage": "" if success else "cannot open object",
                "objects": self.objects,
            }
        )

    def close_object(self, object_id: str) -> FakeEvent:
        self._record_and_maybe_hook("close", object_id=object_id)
        obj = self._object(object_id)
        success = obj is not None and "close" not in self._fail_actions
        if success and obj is not None:
            obj["isOpen"] = False
        return FakeEvent(
            {
                "lastActionSuccess": success,
                "errorMessage": "" if success else "cannot close object",
                "objects": self.objects,
            }
        )


def apple_and_fridge_scene() -> List[Dict[str, Any]]:
    """A minimal two-object scene matching the README's 'store apple in
    refrigerator' demonstration task."""
    return [
        {"objectId": "Apple|1", "objectType": "Apple", "distance": 1.0, "isOpen": None},
        {
            "objectId": "Fridge|1",
            "objectType": "Refrigerator",
            "distance": 2.0,
            "isOpen": False,
        },
    ]
