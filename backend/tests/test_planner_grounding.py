"""
test_planner_grounding.py

Purpose
-------
Unit tests for `planner.grounding.ground_world_state()`, the
`SpatialScene -> WorldState` translation layer: does a live vision
`Scene` correctly answer the planner's "have I seen this object, and
where" questions, layered on top of (never replacing) existing state.

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_grounding.py -v
"""

from __future__ import annotations

from planner.grounding import ground_world_state
from planner.state import WorldState
from scene.detection import Detection
from scene.relationship import Relationship, RelationshipType
from scene.scene import Scene


def _detection(label: str, depth=None, is_open=None) -> Detection:
    attributes = {} if is_open is None else {"is_open": is_open}
    return Detection(
        label=label,
        confidence=0.9,
        bbox=[0, 0, 1, 1],
        depth=depth,
        attributes=attributes,
    )


def test_detected_object_is_marked_located():
    scene = Scene(detections=[_detection("mug")])

    state = ground_world_state(scene)

    assert state.object("mug").is_located is True


def test_close_detection_is_marked_near_robot():
    scene = Scene(detections=[_detection("mug", depth=0.5)])

    state = ground_world_state(scene)

    assert state.object("mug").is_near_robot is True


def test_far_detection_is_not_marked_near_robot():
    scene = Scene(detections=[_detection("mug", depth=5.0)])

    state = ground_world_state(scene)

    assert state.object("mug").is_near_robot is False


def test_inside_relationship_sets_location_to_container_label():
    scene = Scene(
        detections=[_detection("mug"), _detection("cabinet")],
        relationships=[
            Relationship(subject_id=0, predicate=RelationshipType.INSIDE, object_id=1)
        ],
    )

    state = ground_world_state(scene)

    assert state.object("mug").location == "cabinet"


def test_non_inside_relationship_does_not_set_location():
    scene = Scene(
        detections=[_detection("mug"), _detection("table")],
        relationships=[
            Relationship(subject_id=0, predicate=RelationshipType.NEAR, object_id=1)
        ],
    )

    state = ground_world_state(scene)

    assert state.object("mug").location is None


def test_layers_on_top_of_existing_state_without_erasing_unseen_objects():
    state = WorldState.initial()
    state.object("refrigerator").is_open = True
    scene = Scene(detections=[_detection("mug")])

    result = ground_world_state(scene, state)

    assert result is state
    assert state.object("mug").is_located is True
    assert state.object("refrigerator").is_open is True
    assert state.object("refrigerator").is_located is False


def test_detection_re_seen_stays_located_even_if_previously_unlocated():
    state = WorldState.initial()
    state.object("mug")  # auto-vivified, unlocated
    scene = Scene(detections=[_detection("mug")])

    ground_world_state(scene, state)

    assert state.object("mug").is_located is True


# ----------------------------------------------------------------------
# is_open: vision-vs-symbolic reconciliation
# ----------------------------------------------------------------------


def test_vision_is_open_true_sets_object_state():
    scene = Scene(detections=[_detection("fridge", is_open=True)])

    state = ground_world_state(scene)

    assert state.object("fridge").is_open is True


def test_vision_is_open_false_sets_object_state():
    scene = Scene(detections=[_detection("fridge", is_open=False)])

    state = ground_world_state(scene)

    assert state.object("fridge").is_open is False


def test_vision_is_open_overrides_disagreeing_symbolic_value():
    """Vision is stronger evidence than a stale symbolic belief --
    the two disagree here on purpose (symbolic says open, vision says
    closed), and vision must win. See grounding.py's module docstring
    ("is_open: vision vs. symbolic metadata -- vision wins,
    documented")."""
    state = WorldState.initial()
    state.object("fridge").is_open = True  # stale/symbolic belief
    scene = Scene(detections=[_detection("fridge", is_open=False)])

    ground_world_state(scene, state)

    assert state.object("fridge").is_open is False


def test_unclassified_detection_leaves_existing_is_open_unchanged():
    """No `is_open` key in `attributes` (classifier didn't run, or
    wasn't confident) must never be treated as evidence of anything --
    an existing symbolic value survives untouched."""
    state = WorldState.initial()
    state.object("fridge").is_open = True
    scene = Scene(detections=[_detection("fridge")])  # no is_open signal

    ground_world_state(scene, state)

    assert state.object("fridge").is_open is True


# ----------------------------------------------------------------------
# robot_holding: depth-proxied held-object heuristic
# ----------------------------------------------------------------------


def test_very_close_detection_sets_robot_holding():
    scene = Scene(detections=[_detection("mug", depth=0.2)])

    state = ground_world_state(scene)

    assert state.robot_holding == "mug"


def test_near_but_not_held_close_detection_does_not_set_robot_holding():
    """0.8m clears `is_near_robot`'s 1.5m threshold but not the
    stricter held-object threshold (0.5m default) -- being nearby is
    not the same as being held."""
    scene = Scene(detections=[_detection("mug", depth=0.8)])

    state = ground_world_state(scene)

    assert state.object("mug").is_near_robot is True
    assert state.robot_holding is None


def test_no_held_candidate_does_not_clear_existing_robot_holding():
    """This scene has no close detection at all -- must never be
    read as 'hand is now empty.' See grounding.py's module docstring
    ("robot_holding: positive vision evidence only, never clears")."""
    state = WorldState.initial()
    state.robot_holding = "spray_bottle"
    scene = Scene(detections=[_detection("table", depth=3.0)])

    ground_world_state(scene, state)

    assert state.robot_holding == "spray_bottle"


def test_closest_of_multiple_held_candidates_is_chosen():
    scene = Scene(
        detections=[
            _detection("mug", depth=0.4),
            _detection("bowl", depth=0.15),
        ]
    )

    state = ground_world_state(scene)

    assert state.robot_holding == "bowl"
