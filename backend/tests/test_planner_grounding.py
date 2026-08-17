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


def _detection(label: str, depth=None) -> Detection:
    return Detection(label=label, confidence=0.9, bbox=[0, 0, 1, 1], depth=depth)


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
