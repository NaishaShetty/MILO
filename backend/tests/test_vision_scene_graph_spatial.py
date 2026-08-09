"""
test_vision_scene_graph_spatial.py

Purpose
-------
Tests the Phase 3.x depth-aware `NEAR` relationship added to
`HeuristicSceneGraph`, verifying it's purely additive: existing Phase 2
2D-only behavior (one relationship per pair) is unchanged when no
detection has `position_3d`, and `NEAR` is emitted alongside (not
instead of) the 2D relationship when depth is available.
"""

from scene.detection import Detection
from scene.relationship import RelationshipType
from scene.scene import Scene
from vision.scene_graph.heuristic_scene_graph import HeuristicSceneGraph


def _detection(bbox, position_3d=None):
    return Detection(label="object", confidence=0.9, bbox=bbox, position_3d=position_3d)


def test_no_position_3d_produces_exactly_one_relationship_per_pair():
    scene = Scene()
    scene.add_detection(_detection([0, 0, 10, 10]))
    scene.add_detection(_detection([100, 100, 110, 110]))

    HeuristicSceneGraph().process(None, scene)

    assert len(scene.relationships) == 1
    assert scene.relationships[0].predicate != RelationshipType.NEAR


def test_close_3d_positions_add_near_relationship():
    scene = Scene()
    scene.add_detection(_detection([0, 0, 10, 10], position_3d=[0.0, 0.0, 1.0]))
    scene.add_detection(_detection([100, 100, 110, 110], position_3d=[0.1, 0.0, 1.0]))

    HeuristicSceneGraph().process(None, scene)

    near_relationships = [
        r for r in scene.relationships if r.predicate == RelationshipType.NEAR
    ]
    assert len(near_relationships) == 1
    # The 2D directional relationship is still present alongside NEAR.
    assert len(scene.relationships) == 2


def test_far_3d_positions_do_not_add_near_relationship():
    scene = Scene()
    scene.add_detection(_detection([0, 0, 10, 10], position_3d=[0.0, 0.0, 1.0]))
    scene.add_detection(_detection([100, 100, 110, 110], position_3d=[5.0, 0.0, 1.0]))

    HeuristicSceneGraph().process(None, scene)

    assert all(r.predicate != RelationshipType.NEAR for r in scene.relationships)
    assert len(scene.relationships) == 1


def test_one_missing_position_3d_does_not_add_near_relationship():
    scene = Scene()
    scene.add_detection(_detection([0, 0, 10, 10], position_3d=[0.0, 0.0, 1.0]))
    scene.add_detection(_detection([100, 100, 110, 110], position_3d=None))

    HeuristicSceneGraph().process(None, scene)

    assert all(r.predicate != RelationshipType.NEAR for r in scene.relationships)
