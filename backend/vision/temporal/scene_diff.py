"""
scene_diff.py

Purpose
-------
Pure comparison of two consecutive `Scene`s into a list of `SceneChange`
events -- the "what changed" half of Phase 3.x.6's Temporal Scene
Representation. Deliberately a pure function, not a class: diffing two
already-perceived scenes needs no model, no state, and nothing beyond
what `TemporalScene.update()` already has on hand (see that module for
the stateful orchestration this feeds into).

Identity requirement
---------------------
Every change below is keyed by `Detection.tracking_id`. A `Scene` whose
detections were never run through a tracker (`tracking_id is None`
throughout) cannot be diffed for identity-based change -- such
detections are silently skipped rather than raising, since "no tracker
configured" is a valid (if less capable) pipeline configuration, not an
error condition this function should punish.

What this function can and cannot tell you
------------------------------------------------
From two consecutive `Scene`s alone:
  - NEW / REAPPEARED: distinguishable, because `IoUTracker` already
    marks a reacquired detection's `attributes["track_status"] ==
    "reacquired"` (see `iou_tracker.py`) -- this function trusts that
    signal rather than re-deriving it.
  - MOVED: only computed when both the previous and current detection
    have `position_3d` (i.e. a depth stage ran) -- 2D bbox drift alone
    is not reliable evidence of physical movement (camera motion,
    detector jitter), so without depth this function makes no movement
    claim at all rather than a noisy one.
  - OCCLUDED: emitted the instant an object stops appearing. This is
    optimistic by construction -- it does NOT know whether the
    underlying track will later expire (`TrackStatus.LOST`) or come
    back (`TrackStatus.REACQUIRED`); `TemporalScene.update()` upgrades
    a stale `OCCLUDED` entry to `REMOVED` once the tracker confirms the
    track is actually `LOST` (see that module). Diffing two scenes in
    isolation cannot make that distinction -- it requires the tracker's
    own state, which lives beyond either scene.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from scene.detection import Detection
from scene.scene import Scene


class ChangeType(str, Enum):
    """Kind of change a `SceneChange` represents. `str` subclass so it
    serializes directly to JSON for the API/UI layer."""

    NEW = "new"
    REMOVED = "removed"
    MOVED = "moved"
    OCCLUDED = "occluded"
    REAPPEARED = "reappeared"


@dataclass
class SceneChange:
    """One detected change between two consecutive scenes.

    Attributes:
        change_type: What kind of change this is.
        tracking_id: The `Detection.tracking_id` this change is about.
        label: The object's label, for human-readable display without a
            second lookup.
        detail: Short, human-readable description (e.g. a MOVED event's
            distance moved) -- for UI/logging, not machine-parsed.
    """

    change_type: ChangeType
    tracking_id: int
    label: str
    detail: str


def _by_tracking_id(scene: Scene) -> Dict[int, Detection]:
    return {
        detection.tracking_id: detection
        for detection in scene.detections
        if detection.tracking_id is not None
    }


def _distance_3d(a: List[float], b: List[float]) -> float:
    return sum((a_i - b_i) ** 2 for a_i, b_i in zip(a, b)) ** 0.5


def diff_scenes(
    previous: Optional[Scene], current: Scene, move_threshold_m: float = 0.1
) -> List[SceneChange]:
    """Computes `SceneChange`s between `previous` and `current`.

    Args:
        previous: The prior frame's `Scene`, or `None` for the very
            first frame (produces no changes -- nothing to compare
            against; every detection in `current` is a track's first
            appearance, not a reportable "change").
        current: The current frame's `Scene`.
        move_threshold_m: Minimum 3D displacement (meters) to report a
            MOVED change; see module docstring for why this only
            applies when both detections have `position_3d`.

    Returns:
        A list of `SceneChange`, in no particular order.
    """

    if previous is None:
        return []

    previous_by_id = _by_tracking_id(previous)
    current_by_id = _by_tracking_id(current)

    changes: List[SceneChange] = []

    for tracking_id, detection in current_by_id.items():
        if tracking_id not in previous_by_id:
            reappeared = detection.attributes.get("track_status") == "reacquired"
            changes.append(
                SceneChange(
                    change_type=(
                        ChangeType.REAPPEARED if reappeared else ChangeType.NEW
                    ),
                    tracking_id=tracking_id,
                    label=detection.label,
                    detail=(
                        "Reappeared after being temporarily occluded."
                        if reappeared
                        else "First observed this frame."
                    ),
                )
            )
            continue

        previous_detection = previous_by_id[tracking_id]
        if (
            detection.position_3d is not None
            and previous_detection.position_3d is not None
        ):
            distance = _distance_3d(
                detection.position_3d, previous_detection.position_3d
            )
            if distance >= move_threshold_m:
                changes.append(
                    SceneChange(
                        change_type=ChangeType.MOVED,
                        tracking_id=tracking_id,
                        label=detection.label,
                        detail=f"Moved {distance:.2f}m.",
                    )
                )

    for tracking_id, detection in previous_by_id.items():
        if tracking_id not in current_by_id:
            changes.append(
                SceneChange(
                    change_type=ChangeType.OCCLUDED,
                    tracking_id=tracking_id,
                    label=detection.label,
                    detail="No longer detected this frame.",
                )
            )

    return changes
