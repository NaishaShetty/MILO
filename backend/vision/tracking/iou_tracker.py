"""
iou_tracker.py

Purpose
-------
`BaseTracker` implementation using bounding-box IoU (with an optional 3D-
proximity fallback) as the association signal, matched frame-to-frame
via the Hungarian algorithm. This is the tracker `vision/factory.py`
wires in by default.

Why IoU-matching, not something heavier
--------------------------------------------
Per the project spec: "Start with an appropriate simple strategy for the
simulator. Do not introduce unnecessary complexity." AI2-THOR is a
step-based simulator (the agent moves in discrete grid/rotation
increments, and this pipeline runs once per requested frame, not at
video frame-rate) -- object motion between consecutive perceived frames
is typically small relative to their size on screen, which is exactly
the regime bbox-IoU matching handles well without needing appearance
features or a learned re-ID model. `TrackerConfig.use_3d_distance` adds
a documented fallback for the case IoU alone misses (bbox drift from
camera motion) using `Detection.position_3d` when available, rather than
reaching for a heavier tracker before there's evidence IoU isn't enough.

Association algorithm
--------------------------
For each `process()` call:
  1. Build a cost matrix over (current detections) x (candidate tracks
     -- every track not already `LOST`; see `_candidate_tracks`).
     `_match_cost` blocks cross-label matches outright (a track never
     silently changes label), scores same-label pairs by `1 - IoU` when
     they overlap, and falls back to a 3D-distance-based cost when they
     don't (if `TrackerConfig.use_3d_distance`).
  2. Solve optimal one-to-one assignment with
     `scipy.optimize.linear_sum_assignment` (Hungarian algorithm) --
     chosen over greedy nearest-match because greedy matching can lock
     in a locally-good-but-globally-wrong pairing when two detections
     both plausibly match two tracks; Hungarian finds the assignment
     minimizing total cost across all pairs simultaneously.
  3. Assignments whose cost exceeds what `_match_cost` would consider a
     real match (see `_is_acceptable_match`) are discarded -- Hungarian
     will happily pair unrelated detections/tracks if forced to, so
     "assigned by the algorithm" and "an acceptable match" are checked
     separately.
  4. Matched pairs update the existing `Track` (see `track.py`'s
     lifecycle); unmatched tracks get a missed-frame increment;
     unmatched detections start new tracks.

`self._tracks` is instance state, safe because `PerceptionPipeline`
holds one tracker instance for its whole lifetime (see
`base_tracker.py`'s "Statefulness note").
"""

import math
from typing import Dict, List, Optional, Tuple

from scipy.optimize import linear_sum_assignment

from scene.scene import Scene
from vision.tracking.base_tracker import BaseTracker
from vision.tracking.track import Track, TrackStatus
from vision.tracking.tracker_config import TrackerConfig

# Cost assigned to a detection/track pair that must never be matched
# (label mismatch, or no overlap and 3D fallback unavailable/too far).
# Larger than any real cost `_match_cost` can otherwise produce (real
# costs are bounded in `[0, 2]` -- see that method's docstring), so
# `_is_acceptable_match` can cheaply distinguish "Hungarian was forced to
# pick something" from "this is an actual match."
_BLOCKED_COST = 1e6


def _iou(bbox_a: List[float], bbox_b: List[float]) -> float:
    """Intersection-over-union of two `[x1, y1, x2, y2]` boxes."""

    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    intersection = inter_w * inter_h

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection

    if union <= 0:
        return 0.0

    return intersection / union


def _distance_3d(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((a_i - b_i) ** 2 for a_i, b_i in zip(a, b)))


class IoUTracker(BaseTracker):
    """Frame-to-frame tracker using IoU (+ optional 3D-proximity
    fallback) matched via the Hungarian algorithm. See module docstring
    for the full association strategy."""

    def __init__(self, config: Optional[TrackerConfig] = None):
        self.config = config or TrackerConfig.from_env()

        self._tracks: Dict[int, Track] = {}
        self._next_track_id = 1
        self._frame_index = 0

    @property
    def tracks(self) -> Dict[int, Track]:
        """Read-only view of every track this tracker has ever created
        (including `LOST` ones) -- consumed by
        `vision/temporal/temporal_scene.py` and the API/UI layer to show
        `first_seen`/`frame_count`/etc. Not part of the frozen
        `process(image, scene)` contract; treat as read-only."""

        return self._tracks

    def process(self, image, scene: Scene) -> Scene:
        """See `BaseTracker.process`. Assigns `detection.tracking_id`
        and mirrors the resulting `TrackStatus` onto
        `detection.attributes["track_status"]` for consumers that only
        see `Detection` (visualizer, scene graph, API)."""

        self._frame_index += 1

        candidate_ids = self._candidate_track_ids()
        detections = scene.detections

        matched_detection_indices, matched_track_ids = self._match(
            detections, candidate_ids
        )

        for detection_index, track_id in zip(
            matched_detection_indices, matched_track_ids
        ):
            self._update_matched_track(detections[detection_index], track_id)

        unmatched_track_ids = set(candidate_ids) - set(matched_track_ids)
        for track_id in unmatched_track_ids:
            self._mark_missed(track_id)

        unmatched_detection_indices = set(range(len(detections))) - set(
            matched_detection_indices
        )
        for detection_index in unmatched_detection_indices:
            self._start_new_track(detections[detection_index])

        return scene

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _candidate_track_ids(self) -> List[int]:
        """Tracks eligible for matching this frame -- everything except
        `LOST` (see `track.py`'s lifecycle docs on why lost tracks are
        excluded from future re-matching)."""

        return [
            track_id
            for track_id, track in self._tracks.items()
            if track.status != TrackStatus.LOST
        ]

    def _match_cost(self, detection, track: Track) -> float:
        """Cost of matching `detection` to `track`. Lower is better.

        Returns:
            `1 - IoU` (range `[0, 1]`) when the boxes overlap and labels
            match; `1 + normalized_3d_distance` (range `(1, 2]`) when
            they don't overlap but a 3D fallback applies; `_BLOCKED_COST`
            otherwise (label mismatch, or no plausible signal at all).
        """

        if detection.label != track.label:
            return _BLOCKED_COST

        iou = _iou(detection.bbox, track.current_bbox)
        if iou > 0:
            return 1.0 - iou

        if (
            self.config.use_3d_distance
            and detection.position_3d is not None
            and track.current_position_3d is not None
        ):
            distance = _distance_3d(detection.position_3d, track.current_position_3d)
            if distance <= self.config.max_3d_distance_m:
                return 1.0 + (distance / self.config.max_3d_distance_m)

        return _BLOCKED_COST

    def _is_acceptable_match(self, cost: float) -> bool:
        """Distinguishes "Hungarian assigned this pair because it had
        to" from "this is actually a match worth keeping" -- see
        `_match_cost`'s docstring for the cost ranges this checks
        against."""

        if cost >= _BLOCKED_COST:
            return False

        if cost <= 1.0:
            return (1.0 - cost) >= self.config.iou_threshold

        return True  # already gated by max_3d_distance_m in _match_cost

    def _match(
        self, detections: List, candidate_ids: List[int]
    ) -> Tuple[List[int], List[int]]:
        """Runs Hungarian assignment over `detections` x `candidate_ids`.

        Returns:
            Parallel lists `(matched_detection_indices,
            matched_track_ids)` for accepted matches only.
        """

        if not detections or not candidate_ids:
            return [], []

        candidates = [self._tracks[track_id] for track_id in candidate_ids]

        cost_matrix = [
            [self._match_cost(detection, track) for track in candidates]
            for detection in detections
        ]

        row_indices, col_indices = linear_sum_assignment(cost_matrix)

        matched_detection_indices: List[int] = []
        matched_track_ids: List[int] = []

        for row, col in zip(row_indices, col_indices):
            cost = cost_matrix[row][col]
            if self._is_acceptable_match(cost):
                matched_detection_indices.append(int(row))
                matched_track_ids.append(candidate_ids[col])

        return matched_detection_indices, matched_track_ids

    # ------------------------------------------------------------------
    # Track state transitions
    # ------------------------------------------------------------------

    def _update_matched_track(self, detection, track_id: int) -> None:
        track = self._tracks[track_id]

        track.previous_bbox = track.current_bbox
        track.previous_position_3d = track.current_position_3d

        track.current_bbox = detection.bbox
        track.current_position_3d = detection.position_3d

        track.last_seen = self._frame_index
        track.frame_count += 1
        track.confidence = detection.confidence
        track.missed_frames = 0
        track.status = (
            TrackStatus.REACQUIRED
            if track.status == TrackStatus.TEMPORARILY_LOST
            else TrackStatus.TRACKED
        )

        detection.tracking_id = track.track_id
        detection.attributes["track_status"] = track.status.value

    def _mark_missed(self, track_id: int) -> None:
        track = self._tracks[track_id]

        track.missed_frames += 1
        track.status = (
            TrackStatus.LOST
            if track.missed_frames > self.config.max_missed_frames
            else TrackStatus.TEMPORARILY_LOST
        )

    def _start_new_track(self, detection) -> None:
        track_id = self._next_track_id
        self._next_track_id += 1

        self._tracks[track_id] = Track(
            track_id=track_id,
            label=detection.label,
            first_seen=self._frame_index,
            last_seen=self._frame_index,
            frame_count=1,
            current_bbox=detection.bbox,
            previous_bbox=None,
            current_position_3d=detection.position_3d,
            previous_position_3d=None,
            status=TrackStatus.NEW,
            confidence=detection.confidence,
            missed_frames=0,
        )

        detection.tracking_id = track_id
        detection.attributes["track_status"] = TrackStatus.NEW.value
