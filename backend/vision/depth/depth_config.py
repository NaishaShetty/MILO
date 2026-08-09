"""
depth_config.py

Purpose
-------
Deployment-tunable thresholds for the depth subsystem -- how much of an
object's mask/bbox region must have valid depth before we trust the
result, and what counts as an implausible depth reading. Follows the
project's `from_env()`-classmethod convention already used by
`language/config.py`'s `LLMRuntimeConfig`, so these values are
configuration, not magic numbers buried in `base_depth_estimator.py`.

Why these two knobs and not more
-----------------------------------
`min_valid_pixel_ratio` and `max_plausible_depth_meters` are the two
thresholds `BaseDepthEstimator._extract_object_depth` actually needs to
decide "is this object's depth trustworthy" (see that module's
docstring). Model choice, camera intrinsics, and tracker/scene-graph
thresholds each have their own dedicated config object
(`config/model_config.py`, `vision/spatial/camera_intrinsics.py`,
`vision/tracking/tracker_config.py`) rather than being folded in here --
one file per concern, matching `language/config.py`'s explicit rationale
for not merging unrelated settings.
"""

import os
from dataclasses import dataclass


def _parse_float_env(name: str, default: float) -> float:
    """Reads a float env var, raising a clear error if set-but-invalid
    rather than letting a bare `ValueError` surface far from the cause."""

    raw = os.environ.get(name)

    if raw is None:
        return default

    try:
        return float(raw)

    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name!r} must be a number, got {raw!r}."
        ) from exc


@dataclass(frozen=True)
class DepthConfig:
    """Thresholds governing when object-level depth is trusted.

    Attributes:
        min_valid_pixel_ratio: Minimum fraction of an object's sampled
            pixels (mask, or bbox region when no mask exists) that must
            have finite, plausible depth for `Detection.depth` to be
            set at all. Below this, depth is left `None` -- an explicit
            "missing/invalid depth" state rather than a noisy guess from
            mostly-invalid pixels (e.g. an object mostly occluded or
            right at the depth sensor's edge).
        max_plausible_depth_meters: Depth readings above this are
            treated as invalid/sensor-noise rather than a real distance
            -- AI2-THOR rooms and Depth Anything's usable range are both
            well under typical building-scale distances, so a reading
            far beyond this is far more likely to be a rendering
            artifact (e.g. depth through a window/skybox) than a real
            object.
    """

    min_valid_pixel_ratio: float
    max_plausible_depth_meters: float

    @classmethod
    def from_env(cls) -> "DepthConfig":
        return cls(
            min_valid_pixel_ratio=_parse_float_env("VISION_MIN_VALID_DEPTH_RATIO", 0.5),
            max_plausible_depth_meters=_parse_float_env(
                "VISION_MAX_PLAUSIBLE_DEPTH_METERS", 20.0
            ),
        )
