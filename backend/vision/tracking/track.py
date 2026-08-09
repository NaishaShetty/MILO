"""
track.py

Purpose
-------
Defines `TrackStatus` and `Track` -- the persistent, per-object identity
state a tracker maintains across frames (Phase 3.x.5, "Persistent Object
Identity"). This is where `first_seen`/`last_seen`/`frame_count`/
`previous_position`/etc. live, deliberately NOT on `Detection`.

Why this isn't just more fields on `Detection`
---------------------------------------------------
`Detection`'s field schema is frozen (Phase 2 API freeze, see
`docs/architecture/api_contracts.md`) and, more fundamentally, describes
*one frame's* observation of an object -- it has no notion of "since
when have I been seeing this." `Track` is the tracker's own, private
bookkeeping across many frames; `Detection.tracking_id` is the only
bridge between the two (an `int` key into whichever tracker's `Track`
store produced it). A `Detection.attributes["track_status"]` mirror is
set by the tracker for convenience (see `iou_tracker.py`) so
`SceneVisualizer`/the scene graph, which only ever see `Detection`, can
display status without reaching into tracker internals -- but `Track`
itself is not part of `Scene` and is not a frozen interface.

Track lifecycle
----------------
    NEW -> TRACKED -> TEMPORARILY_LOST -> REACQUIRED -> TRACKED
                              |
                              v
                            LOST

- NEW: first frame a track was created; not yet confirmed across a
  second frame.
- TRACKED: matched to a detection in the immediately preceding frame.
- TEMPORARILY_LOST: no matching detection this frame, but within
  `TrackerConfig.max_missed_frames` -- e.g. brief occlusion (see the
  project's "Object Permanence" example: bottle visible, occluded,
  visible again).
- REACQUIRED: was `TEMPORARILY_LOST`, matched again this frame. A
  transient status -- the next successful match reports `TRACKED`.
- LOST: exceeded `max_missed_frames` consecutive misses. Excluded from
  future matching (see `iou_tracker.py::_candidate_tracks`) -- this
  project does not promise perfect re-identification after a track is
  declared lost; a later reappearance of the same physical object gets
  a new track/ID. This is a documented limitation, not a bug: without
  appearance features, nothing distinguishes "the same mug reappeared"
  from "a different, identical-looking mug appeared," so re-matching an
  indefinitely-old lost track would risk far more false identity merges
  than it fixes.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class TrackStatus(str, Enum):
    """Lifecycle state of a `Track`. See module docstring for the state
    diagram. A `str` subclass so it serializes directly to JSON (API
    responses, `Detection.attributes["track_status"]`) without a
    separate encoder."""

    NEW = "new"
    TRACKED = "tracked"
    TEMPORARILY_LOST = "temporarily_lost"
    REACQUIRED = "reacquired"
    LOST = "lost"


@dataclass
class Track:
    """Persistent, cross-frame identity and state for one physical object.

    Attributes:
        track_id: Stable identifier, matches `Detection.tracking_id` for
            every detection matched to this track.
        label: Object class name, at track creation time. Used as a
            hard constraint during matching (see `iou_tracker.py`) --
            a track never silently changes label.
        first_seen: Frame index this track was created on.
        last_seen: Frame index this track was last matched to a
            detection on (not updated while `TEMPORARILY_LOST`).
        frame_count: Number of frames this track has been matched to a
            detection (excludes missed frames).
        current_bbox: Most recent matched `[x1, y1, x2, y2]`.
        previous_bbox: The bbox before `current_bbox` (from the prior
            *matched* frame) -- lets a caller show movement
            (`t0 -> A`, `t1 -> B`) per the project's temporal-tracking
            UI requirement.
        current_position_3d: Most recent matched 3D position, if depth
            was available (`None` otherwise).
        previous_position_3d: The 3D position before `current_position_3d`.
        status: Current `TrackStatus`.
        confidence: Most recent matched detection's confidence.
        missed_frames: Consecutive frames since the last match. Reset
            to `0` on every successful match.
    """

    track_id: int
    label: str
    first_seen: int
    last_seen: int
    frame_count: int
    current_bbox: List[float]
    previous_bbox: Optional[List[float]]
    current_position_3d: Optional[List[float]]
    previous_position_3d: Optional[List[float]]
    status: TrackStatus
    confidence: float
    missed_frames: int
