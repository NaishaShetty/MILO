"""
test_execution_dispatcher.py

Purpose
-------
Unit tests for `execution.dispatcher.ActionDispatcher` -- section 18's
"Dispatcher" test list: every `ActionType` maps to the correct
`Simulator` method call, `LOCATE` never touches the simulator, and a
missing required parameter raises rather than dispatching a malformed
call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from execution.dispatcher import ActionDispatcher
from execution.models import Action, ActionType


def _dispatcher():
    simulator = MagicMock()
    return ActionDispatcher(simulator), simulator


@pytest.mark.parametrize(
    "action_type,simulator_method",
    [
        (ActionType.MOVE_AHEAD, "move_ahead"),
        (ActionType.MOVE_BACK, "move_back"),
        (ActionType.ROTATE_LEFT, "turn_left"),
        (ActionType.ROTATE_RIGHT, "turn_right"),
        (ActionType.LOOK_UP, "look_up"),
        (ActionType.LOOK_DOWN, "look_down"),
    ],
)
def test_movement_actions_dispatch_to_correct_simulator_method(
    action_type, simulator_method
):
    dispatcher, simulator = _dispatcher()
    dispatcher.dispatch(Action(action_type=action_type, parameters={}))
    getattr(simulator, simulator_method).assert_called_once_with()


def test_pickup_dispatches_to_pickup_object_with_object_id():
    dispatcher, simulator = _dispatcher()
    dispatcher.dispatch(
        Action(action_type=ActionType.PICKUP, parameters={"object_id": "Apple|1"})
    )
    simulator.pickup_object.assert_called_once_with("Apple|1")


def test_open_dispatches_to_open_object():
    dispatcher, simulator = _dispatcher()
    dispatcher.dispatch(
        Action(action_type=ActionType.OPEN, parameters={"object_id": "Fridge|1"})
    )
    simulator.open_object.assert_called_once_with("Fridge|1")


def test_close_dispatches_to_close_object():
    dispatcher, simulator = _dispatcher()
    dispatcher.dispatch(
        Action(action_type=ActionType.CLOSE, parameters={"object_id": "Fridge|1"})
    )
    simulator.close_object.assert_called_once_with("Fridge|1")


def test_navigate_dispatches_to_navigate_to():
    dispatcher, simulator = _dispatcher()
    dispatcher.dispatch(
        Action(action_type=ActionType.NAVIGATE, parameters={"object_id": "Apple|1"})
    )
    simulator.navigate_to.assert_called_once_with("Apple|1")


def test_put_dispatches_to_put_object_with_container_id():
    dispatcher, simulator = _dispatcher()
    dispatcher.dispatch(
        Action(action_type=ActionType.PUT, parameters={"container_id": "Fridge|1"})
    )
    simulator.put_object.assert_called_once_with("Fridge|1")


def test_locate_never_touches_simulator():
    dispatcher, simulator = _dispatcher()
    result = dispatcher.dispatch(Action(action_type=ActionType.LOCATE, parameters={}))
    assert result is None
    simulator.assert_not_called()
    assert simulator.method_calls == []


@pytest.mark.parametrize(
    "action_type",
    [ActionType.PICKUP, ActionType.OPEN, ActionType.CLOSE, ActionType.NAVIGATE],
)
def test_missing_object_id_raises_value_error(action_type):
    dispatcher, _ = _dispatcher()
    with pytest.raises(ValueError):
        dispatcher.dispatch(Action(action_type=action_type, parameters={}))


def test_put_without_container_id_raises_value_error():
    dispatcher, _ = _dispatcher()
    with pytest.raises(ValueError):
        dispatcher.dispatch(Action(action_type=ActionType.PUT, parameters={}))
