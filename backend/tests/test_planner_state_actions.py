"""
test_planner_state_actions.py

Purpose
-------
Unit tests for `planner/state.py` (`WorldState`, `ObjectState`) and
`planner/actions.py` (`ACTION_REGISTRY`, preconditions, effects).
Covers section 14's "State simulation" and "Preconditions" bullets:
state transitions, object ownership/location, container open/close
state, and valid/invalid precondition checks for pickup/placement/
open/close.

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_state_actions.py -v
"""

from planner.actions import (
    ACTION_REGISTRY,
    CLOSE,
    NAVIGATE,
    OPEN,
    PICKUP,
    PLACE,
    get_action_spec,
)
from planner.state import WorldState


def test_auto_vivifies_unknown_object():
    state = WorldState.initial()
    assert not state.has_seen("apple")
    obj = state.object("apple")
    assert state.has_seen("apple")
    assert obj.is_located is False and obj.is_held is False


def test_clone_is_independent():
    state = WorldState.initial()
    state.object("apple").is_located = True
    clone = state.clone()
    clone.object("apple").is_located = False
    assert state.object("apple").is_located is True


def test_navigate_precondition_requires_locate_first():
    state = WorldState.initial()
    spec = get_action_spec(NAVIGATE)
    assert spec.check_preconditions(state, "apple", {})  # fails: not located
    state.object("apple").is_located = True
    assert not spec.check_preconditions(state, "apple", {})  # now passes


def test_pickup_precondition_valid_and_invalid():
    state = WorldState.initial()
    spec = get_action_spec(PICKUP)
    # invalid: not near robot yet
    assert spec.check_preconditions(state, "apple", {})
    state.object("apple").is_near_robot = True
    # valid: near, hand empty, not held
    assert not spec.check_preconditions(state, "apple", {})
    state.robot_holding = "mug"
    # invalid: hand not empty
    assert spec.check_preconditions(state, "apple", {})


def test_pickup_effect_updates_ownership_and_location():
    state = WorldState.initial()
    state.object("apple").is_near_robot = True
    get_action_spec(PICKUP).apply_effect(state, "apple", {})
    assert state.robot_holding == "apple"
    assert state.object("apple").is_held is True
    assert state.object("apple").location == "robot"


def test_open_close_state_transitions():
    state = WorldState.initial()
    state.object("refrigerator").is_near_robot = True
    open_spec = get_action_spec(OPEN)
    close_spec = get_action_spec(CLOSE)

    assert not open_spec.check_preconditions(state, "refrigerator", {})
    open_spec.apply_effect(state, "refrigerator", {})
    assert state.object("refrigerator").is_open is True

    # closing before opening again should now be valid (it's open)
    assert not close_spec.check_preconditions(state, "refrigerator", {})
    close_spec.apply_effect(state, "refrigerator", {})
    assert state.object("refrigerator").is_open is False

    # closing an already-closed object is invalid
    assert close_spec.check_preconditions(state, "refrigerator", {})


def test_place_requires_holding_and_open_container():
    state = WorldState.initial()
    place_spec = get_action_spec(PLACE)
    params = {"container": "refrigerator"}

    # invalid: not holding apple
    assert place_spec.check_preconditions(state, "apple", params)

    state.robot_holding = "apple"
    state.object("apple").is_held = True
    # container never opened (is_open is None) -> treated as ready
    assert not place_spec.check_preconditions(state, "apple", params)

    # container explicitly closed -> invalid
    state.object("refrigerator").is_open = False
    assert place_spec.check_preconditions(state, "apple", params)

    state.object("refrigerator").is_open = True
    assert not place_spec.check_preconditions(state, "apple", params)

    place_spec.apply_effect(state, "apple", params)
    assert state.object("apple").location == "refrigerator"
    assert state.object("apple").is_held is False
    assert state.robot_holding is None


def test_action_registry_contains_every_expected_action():
    for name in (NAVIGATE, PICKUP, PLACE, OPEN, CLOSE, "locate", "put_down", "act"):
        assert name in ACTION_REGISTRY
