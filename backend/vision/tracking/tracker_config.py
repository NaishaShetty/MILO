"""
tracker_config.py

Purpose
-------
Deployment-tunable thresholds for `IoUTracker`, following the same
`from_env()`-classmethod convention as `language/config.py` and
`vision/depth/depth_config.py`. Keeps association thresholds out of
`iou_tracker.py` as configuration rather than magic numbers, per the
project's "make thresholds configurable" requirement.
"""

import os
from dataclasses import dataclass


def _parse_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name!r} must be a number, got {raw!r}."
        ) from exc


def _parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name!r} must be an integer, got {raw!r}."
        ) from exc


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class TrackerConfig:
    """Association and lifecycle thresholds for `IoUTracker`.

    Attributes:
        iou_threshold: Minimum bounding-box IoU for a detection to be
            considered a match to an existing track. Chosen as the
            starting association signal because it's what's always
            available (every detection has a bbox); see
            `iou_tracker.py`'s module docstring for why this project
            starts here rather than a heavier strategy.
        max_missed_frames: Consecutive frames a track may go unmatched
            before it transitions from `TEMPORARILY_LOST` to `LOST`
            (see `track.py`'s lifecycle docs). Governs how much
            occlusion the tracker tolerates before giving up on a
            track.
        use_3d_distance: When `True`, a detection with no bbox overlap
            against a track can still match if both have
            `position_3d` set and are within `max_3d_distance_m` --
            handles a detection whose bbox has drifted (e.g. camera
            motion) but whose 3D position is still close. When `False`,
            matching is bbox-IoU only.
        max_3d_distance_m: Maximum 3D Euclidean distance (meters) for
            the `use_3d_distance` fallback above.
    """

    iou_threshold: float
    max_missed_frames: int
    use_3d_distance: bool
    max_3d_distance_m: float

    @classmethod
    def from_env(cls) -> "TrackerConfig":
        return cls(
            iou_threshold=_parse_float_env("VISION_TRACKER_IOU_THRESHOLD", 0.3),
            max_missed_frames=_parse_int_env("VISION_TRACKER_MAX_MISSED_FRAMES", 5),
            use_3d_distance=_parse_bool_env("VISION_TRACKER_USE_3D_DISTANCE", True),
            max_3d_distance_m=_parse_float_env("VISION_TRACKER_MAX_3D_DISTANCE_M", 0.5),
        )
