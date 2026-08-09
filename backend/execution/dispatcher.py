"""
dispatcher.py (backend/execution)

Purpose
-------
`ActionDispatcher` is the single centralized boundary translating one
`Action` into exactly one `simulator.simulator.Simulator` method call --
section 3's "Action Registry / Dispatcher" requirement. Nothing else in
this project should ever call a `Simulator` method directly to carry
out a plan step; every such call is expected to funnel through
`ActionDispatcher.dispatch()`, so "which simulator call does
`ActionType.PICKUP` map to" has exactly one answer, in exactly one
place:

```
ActionType.MOVE_AHEAD -> Simulator.move_ahead()
ActionType.MOVE_BACK  -> Simulator.move_back()
ActionType.ROTATE_LEFT -> Simulator.turn_left()
ActionType.ROTATE_RIGHT -> Simulator.turn_right()
ActionType.LOOK_UP    -> Simulator.look_up()
ActionType.LOOK_DOWN  -> Simulator.look_down()
ActionType.NAVIGATE   -> Simulator.navigate_to(object_id)
ActionType.PICKUP     -> Simulator.pickup_object(object_id)
ActionType.PUT        -> Simulator.put_object(container_id)
ActionType.OPEN       -> Simulator.open_object(object_id)
ActionType.CLOSE      -> Simulator.close_object(object_id)
ActionType.LOCATE     -> no simulator call (see below)
```

Why `LOCATE` never calls the simulator
-----------------------------------------
Phase 4's `locate` action means "this object is now perceived/known"
(`planner.actions.ACTION_REGISTRY[LOCATE]`) -- a symbolic bookkeeping
step with no AI2-THOR equivalent action. Grounding it against a real
perception call is Vision's job (`backend/vision/`), not Execution's --
this dispatcher treats it as a deliberate no-op that still produces a
normal successful `ActionResult`, rather than either fabricating a
"detection" or refusing to dispatch a Phase-4-generated plan.

Why this returns a raw AI2-THOR event/metadata dict, not an `ActionResult`
------------------------------------------------------------------------------
Deciding whether a dispatched call actually *succeeded* is
`validator.ResultValidator`'s job, not this module's -- section 8's
"do not treat a simulator response as automatically successful"
boundary. `dispatch()` returns exactly what the underlying `Simulator`
call returned (an AI2-THOR `Event`-like object exposing `.metadata`,
or `None` for `LOCATE`); `controller.py` is the only caller, and it
always pipes this straight into `ResultValidator.validate()` before
ever constructing an `ActionResult`.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from execution.models import Action, ActionType
from simulator.simulator import Simulator


class UnknownActionTypeError(ValueError):
    """
    Raised when asked to dispatch an `ActionType` this dispatcher has
    no registered handler for. In practice unreachable through normal
    use (`ActionType` is a closed enum and every member is registered
    below) -- kept as a loud failure rather than a silent no-op in case
    a future `ActionType` is added without a matching dispatch entry.
    """


class ActionDispatcher:
    """
    Wraps one `Simulator` instance and dispatches `Action`s against it.
    Stateless beyond that wrapped `Simulator` -- every `ActionType` ->
    `Simulator` method mapping lives in `_HANDLERS` below, built once
    per instance so each handler closes over `self._simulator` instead
    of the module needing a global registry.
    """

    def __init__(self, simulator: Simulator) -> None:
        self._simulator = simulator
        self._handlers: Dict[ActionType, Callable[[Action], Any]] = {
            ActionType.MOVE_AHEAD: lambda a: self._simulator.move_ahead(),
            ActionType.MOVE_BACK: lambda a: self._simulator.move_back(),
            ActionType.ROTATE_LEFT: lambda a: self._simulator.turn_left(),
            ActionType.ROTATE_RIGHT: lambda a: self._simulator.turn_right(),
            ActionType.LOOK_UP: lambda a: self._simulator.look_up(),
            ActionType.LOOK_DOWN: lambda a: self._simulator.look_down(),
            ActionType.NAVIGATE: lambda a: self._simulator.navigate_to(
                self._require_object_id(a)
            ),
            ActionType.PICKUP: lambda a: self._simulator.pickup_object(
                self._require_object_id(a)
            ),
            ActionType.PUT: lambda a: self._simulator.put_object(
                self._require_param(a, "container_id")
            ),
            ActionType.OPEN: lambda a: self._simulator.open_object(
                self._require_object_id(a)
            ),
            ActionType.CLOSE: lambda a: self._simulator.close_object(
                self._require_object_id(a)
            ),
            ActionType.LOCATE: lambda a: None,
        }

    @staticmethod
    def _require_object_id(action: Action) -> str:
        return ActionDispatcher._require_param(action, "object_id")

    @staticmethod
    def _require_param(action: Action, key: str) -> str:
        value = action.parameters.get(key)
        if not value:
            raise ValueError(
                f"Action {action.action_type.value!r} requires "
                f"parameters[{key!r}], got {action.parameters!r}."
            )
        return str(value)

    def dispatch(self, action: Action) -> Optional[Any]:
        """
        Executes `action` against the wrapped `Simulator` and returns
        whatever that `Simulator` call returned (an AI2-THOR event, or
        `None` for `LOCATE`). Raises `ValueError` if a required
        parameter is missing (an `Action` malformed enough that it
        cannot be dispatched at all -- `controller.py` catches this and
        reports it as `ExecutionErrorCode.INVALID_PARAMETER`, never lets
        it propagate as an unhandled 500).
        """
        handler = self._handlers.get(action.action_type)
        if handler is None:
            raise UnknownActionTypeError(
                f"No dispatch handler registered for {action.action_type!r}."
            )
        return handler(action)
