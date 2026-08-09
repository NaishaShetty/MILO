"""
vision/tracking

Purpose
-------
Home for multi-frame object tracking (assigning stable
`Detection.tracking_id`s across frames, e.g. via IoU matching or a
learned tracker). Separate from `vision/detectors` because tracking
is inherently stateful across calls (it must remember previous
frames' detections), whereas a detector is stateless per-frame.

Phase 3.x: implemented. See `base_tracker.py` for the interface and
`iou_tracker.py` for the default IoU-matching implementation; `track.py`
holds the persistent `Track`/`TrackStatus` state a tracker maintains
across frames.
"""
