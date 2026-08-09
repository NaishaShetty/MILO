"""
test_vision_tracking.py

Purpose
-------
Deterministic tests for `vision/tracking/iou_tracker.py` -- no model
weights, no simulator, purely synthetic `Detection`/`Scene` sequences
driven directly at `IoUTracker.process()`, matching the project's
requirement to cover: new object, existing object, multiple objects,
temporary disappearance, reappearance, track expiration, ID stability,
and object movement.
"""

from scene.detection import Detection
from scene.scene import Scene
from vision.tracking.iou_tracker import IoUTracker
from vision.tracking.track import TrackStatus
from vision.tracking.tracker_config import TrackerConfig


def _scene(*detections: Detection) -> Scene:
    scene = Scene()
    for detection in detections:
        scene.add_detection(detection)
    return scene


def _tracker(**overrides) -> IoUTracker:
    config = TrackerConfig(
        iou_threshold=0.3,
        max_missed_frames=2,
        use_3d_distance=True,
        max_3d_distance_m=0.5,
    )
    config = TrackerConfig(**{**config.__dict__, **overrides})
    return IoUTracker(config=config)


def test_new_object_gets_assigned_a_track_id_and_status_new():
    tracker = _tracker()
    scene = _scene(Detection(label="apple", confidence=0.9, bbox=[0, 0, 10, 10]))

    tracker.process(None, scene)

    detection = scene.detections[0]
    assert detection.tracking_id is not None
    assert detection.attributes["track_status"] == TrackStatus.NEW.value


def test_existing_object_keeps_same_id_across_frames():
    tracker = _tracker()

    scene1 = _scene(Detection(label="apple", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene1)
    first_id = scene1.detections[0].tracking_id

    # Slightly moved bbox, still high overlap.
    scene2 = _scene(Detection(label="apple", confidence=0.9, bbox=[1, 1, 11, 11]))
    tracker.process(None, scene2)

    assert scene2.detections[0].tracking_id == first_id
    assert scene2.detections[0].attributes["track_status"] == TrackStatus.TRACKED.value


def test_multiple_objects_tracked_independently():
    tracker = _tracker()

    scene1 = _scene(
        Detection(label="apple", confidence=0.9, bbox=[0, 0, 10, 10]),
        Detection(label="mug", confidence=0.9, bbox=[50, 50, 60, 60]),
    )
    tracker.process(None, scene1)
    apple_id = scene1.detections[0].tracking_id
    mug_id = scene1.detections[1].tracking_id
    assert apple_id != mug_id

    scene2 = _scene(
        Detection(label="apple", confidence=0.9, bbox=[1, 1, 11, 11]),
        Detection(label="mug", confidence=0.9, bbox=[51, 51, 61, 61]),
    )
    tracker.process(None, scene2)

    assert scene2.detections[0].tracking_id == apple_id
    assert scene2.detections[1].tracking_id == mug_id


def test_temporary_disappearance_marks_temporarily_lost_not_lost():
    tracker = _tracker(max_missed_frames=2)

    scene1 = _scene(Detection(label="bottle", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene1)
    track_id = scene1.detections[0].tracking_id

    # Bottle occluded: no detection this frame.
    tracker.process(None, _scene())

    track = tracker.tracks[track_id]
    assert track.status == TrackStatus.TEMPORARILY_LOST
    assert track.missed_frames == 1


def test_reappearance_reacquires_same_track_id():
    tracker = _tracker(max_missed_frames=2)

    scene1 = _scene(Detection(label="bottle", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene1)
    track_id = scene1.detections[0].tracking_id

    tracker.process(None, _scene())  # occluded

    scene3 = _scene(Detection(label="bottle", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene3)

    assert scene3.detections[0].tracking_id == track_id
    assert (
        scene3.detections[0].attributes["track_status"] == TrackStatus.REACQUIRED.value
    )


def test_track_expires_after_max_missed_frames():
    tracker = _tracker(max_missed_frames=2)

    scene1 = _scene(Detection(label="bottle", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene1)
    track_id = scene1.detections[0].tracking_id

    tracker.process(None, _scene())  # miss 1 -> temporarily_lost
    tracker.process(None, _scene())  # miss 2 -> temporarily_lost
    tracker.process(None, _scene())  # miss 3 -> lost

    assert tracker.tracks[track_id].status == TrackStatus.LOST


def test_lost_track_is_not_reacquired_by_a_later_reappearance():
    tracker = _tracker(max_missed_frames=1)

    scene1 = _scene(Detection(label="bottle", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene1)
    original_id = scene1.detections[0].tracking_id

    tracker.process(None, _scene())  # miss 1 -> temporarily_lost
    tracker.process(None, _scene())  # miss 2 -> lost

    scene4 = _scene(Detection(label="bottle", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene4)

    # A new track is started -- lost tracks are not eligible for
    # re-matching (see track.py's documented limitation).
    assert scene4.detections[0].tracking_id != original_id
    assert scene4.detections[0].attributes["track_status"] == TrackStatus.NEW.value


def test_different_label_does_not_match_existing_track():
    tracker = _tracker()

    scene1 = _scene(Detection(label="apple", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene1)
    apple_id = scene1.detections[0].tracking_id

    # Same location, different label -- must not steal the apple's track.
    scene2 = _scene(Detection(label="mug", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene2)

    assert scene2.detections[0].tracking_id != apple_id


def test_object_movement_recorded_as_previous_vs_current_bbox():
    tracker = _tracker()

    scene1 = _scene(Detection(label="apple", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene1)
    track_id = scene1.detections[0].tracking_id

    scene2 = _scene(Detection(label="apple", confidence=0.9, bbox=[2, 2, 12, 12]))
    tracker.process(None, scene2)

    track = tracker.tracks[track_id]
    assert track.previous_bbox == [0, 0, 10, 10]
    assert track.current_bbox == [2, 2, 12, 12]


def test_low_iou_below_threshold_starts_new_track():
    tracker = _tracker()

    scene1 = _scene(Detection(label="apple", confidence=0.9, bbox=[0, 0, 10, 10]))
    tracker.process(None, scene1)
    first_id = scene1.detections[0].tracking_id

    # Far away, no overlap, no 3D position available -> new track.
    scene2 = _scene(Detection(label="apple", confidence=0.9, bbox=[500, 500, 510, 510]))
    tracker.process(None, scene2)

    assert scene2.detections[0].tracking_id != first_id


def test_3d_distance_fallback_matches_when_bbox_moved_far_but_close_in_3d():
    tracker = _tracker(use_3d_distance=True, max_3d_distance_m=1.0)

    scene1 = _scene(
        Detection(
            label="apple",
            confidence=0.9,
            bbox=[0, 0, 10, 10],
            position_3d=[0.0, 0.0, 1.0],
        )
    )
    tracker.process(None, scene1)
    track_id = scene1.detections[0].tracking_id

    # bbox moved far enough that IoU == 0, but 3D position barely moved.
    scene2 = _scene(
        Detection(
            label="apple",
            confidence=0.9,
            bbox=[500, 500, 510, 510],
            position_3d=[0.1, 0.0, 1.0],
        )
    )
    tracker.process(None, scene2)

    assert scene2.detections[0].tracking_id == track_id
