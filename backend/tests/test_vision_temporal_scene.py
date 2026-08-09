"""
test_vision_temporal_scene.py

Purpose
-------
Deterministic tests for `vision/temporal/scene_diff.py` and
`temporal_scene.py` -- synthetic `Scene`/`Detection` sequences only, no
tracker/model/simulator required, covering the project's required
temporal-scene cases: new, removed, moved, occluded, reappeared object.
"""

from scene.detection import Detection
from scene.scene import Scene
from vision.temporal.scene_diff import ChangeType, diff_scenes
from vision.temporal.temporal_scene import TemporalScene


def _detection(tracking_id, label="apple", position_3d=None, track_status=None):
    detection = Detection(label=label, confidence=0.9, bbox=[0, 0, 10, 10])
    detection.tracking_id = tracking_id
    detection.position_3d = position_3d
    if track_status is not None:
        detection.attributes["track_status"] = track_status
    return detection


def _scene(*detections):
    scene = Scene()
    for detection in detections:
        scene.add_detection(detection)
    return scene


# ---------------------------------------------------------------------------
# diff_scenes
# ---------------------------------------------------------------------------


def test_first_frame_produces_no_changes():
    current = _scene(_detection(1))
    assert diff_scenes(None, current) == []


def test_new_object_detected():
    previous = _scene()
    current = _scene(_detection(1))

    changes = diff_scenes(previous, current)

    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.NEW
    assert changes[0].tracking_id == 1


def test_object_occluded():
    previous = _scene(_detection(1))
    current = _scene()

    changes = diff_scenes(previous, current)

    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.OCCLUDED
    assert changes[0].tracking_id == 1


def test_object_reappeared_uses_tracker_status_signal():
    previous = _scene()
    current = _scene(_detection(1, track_status="reacquired"))

    changes = diff_scenes(previous, current)

    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.REAPPEARED


def test_object_moved_detected_via_position_3d():
    previous = _scene(_detection(1, position_3d=[0.0, 0.0, 1.0]))
    current = _scene(_detection(1, position_3d=[0.0, 0.0, 2.0]))

    changes = diff_scenes(previous, current, move_threshold_m=0.5)

    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.MOVED


def test_small_position_change_below_threshold_is_not_moved():
    previous = _scene(_detection(1, position_3d=[0.0, 0.0, 1.0]))
    current = _scene(_detection(1, position_3d=[0.0, 0.0, 1.02]))

    changes = diff_scenes(previous, current, move_threshold_m=0.5)

    assert changes == []


def test_no_position_3d_produces_no_moved_claim():
    previous = _scene(_detection(1, position_3d=None))
    current = _scene(_detection(1, position_3d=None))

    assert diff_scenes(previous, current) == []


def test_detections_without_tracking_id_are_ignored():
    previous = _scene(Detection(label="apple", confidence=0.9, bbox=[0, 0, 1, 1]))
    current = _scene(Detection(label="apple", confidence=0.9, bbox=[0, 0, 1, 1]))

    assert diff_scenes(previous, current) == []


# ---------------------------------------------------------------------------
# TemporalScene
# ---------------------------------------------------------------------------


def test_temporal_scene_tracks_current_and_previous():
    temporal = TemporalScene()

    scene1 = _scene(_detection(1))
    temporal.update(scene1)
    assert temporal.current is scene1
    assert temporal.previous is None

    scene2 = _scene(_detection(1))
    temporal.update(scene2)
    assert temporal.current is scene2
    assert temporal.previous is scene1


def test_temporal_scene_history_is_bounded():
    temporal = TemporalScene(history_size=2)

    temporal.update(_scene(_detection(1)))
    temporal.update(_scene(_detection(1)))
    temporal.update(_scene(_detection(1)))

    assert len(temporal.get_history()) == 2


def test_temporal_scene_upgrades_occlusion_to_removed_with_tracker():
    class _FakeTrack:
        def __init__(self, status):
            self.status = status

    class _FakeTracker:
        def __init__(self, tracks):
            self.tracks = tracks

    temporal = TemporalScene()

    temporal.update(_scene(_detection(1)))  # frame 1: present
    changes = temporal.update(_scene())  # frame 2: occluded

    assert changes[0].change_type == ChangeType.OCCLUDED

    tracker = _FakeTracker({1: _FakeTrack(status="lost")})
    changes = temporal.update(_scene(), tracker=tracker)  # frame 3: confirmed lost

    assert any(
        c.change_type == ChangeType.REMOVED and c.tracking_id == 1 for c in changes
    )


def test_temporal_scene_without_tracker_never_upgrades_to_removed():
    temporal = TemporalScene()

    temporal.update(_scene(_detection(1)))
    changes = temporal.update(_scene())
    assert changes[0].change_type == ChangeType.OCCLUDED

    changes = temporal.update(_scene())  # still occluded, no tracker passed
    assert all(c.change_type != ChangeType.REMOVED for c in changes)
