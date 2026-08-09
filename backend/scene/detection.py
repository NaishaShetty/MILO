"""
detection.py

Purpose
-------
Defines the Detection data model: one detected object within a Scene.

Responsibilities
-----------------
- Hold everything known about a single detected object.
- Stay a plain data container -- Detection does not perform detection,
  segmentation, tracking, or 3D projection itself; those are the jobs
  of the detector/segmenter/tracker/depth modules that fill these
  fields in.

Why this abstraction exists
-----------------------------
Instead of passing dictionaries throughout the project, we use a
strongly typed data model. `label`, `confidence`, and `bbox` are
required because every detector produces them today. The remaining
fields (`mask`, `tracking_id`, `depth`, `position_3d`, `attributes`)
are optional placeholders for perception modules that don't exist yet:

- `mask`        -- filled in by a future segmenter (SAM2), as a `Mask`
                   (scene/mask.py) rather than a bare array -- see that
                   file for why.
- `tracking_id` -- filled in by a future tracker, to link the same
                   physical object across frames.
- `depth`       -- filled in by a future depth-estimation module.
- `position_3d` -- derived from `depth` + camera intrinsics, once
                   available.
- `attributes`  -- an open-ended bag for anything else a future module
                   wants to attach (color, material, VLM-derived
                   descriptions, ...) without requiring a schema change
                   here every time.

Declaring these now, unimplemented, means `GroundingDINODetector` (and
any future detector) can keep constructing `Detection(label=...,
confidence=..., bbox=...)` unchanged, while downstream code can already
be written against the full field set.

Who is allowed to depend on this file
-----------------------------------------
As of the Phase 2 API freeze (see
`docs/architecture/api_contracts.md`), `Detection`'s field schema is a
frozen public interface. Every future module -- Language, Planner,
Memory, Execution, Frontend -- reading `Scene.detections` should rely
on this field set (and its documented meaning) rather than on which
detector/segmenter/tracker produced a given instance.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from scene.mask import Mask


# --------------------------------------------------------------------
# Public API (Frozen after Phase 2)
#
# Language
# Planner
# Memory
# Execution
# Frontend
#
# depend on this interface.
#
# Avoid breaking changes unless absolutely necessary.
# --------------------------------------------------------------------
@dataclass
class Detection:
    """One detected object within a `Scene`.

    A plain, strongly typed data container -- see the module
    docstring for why each optional field exists before any producer
    fills it in.

    Attributes:
        label: Object class name, e.g. `"refrigerator"`.
        confidence: Detector confidence score in `[0, 1]`.
        bbox: `[x1, y1, x2, y2]` pixel bounding box.
        mask: Pixel-accurate segmentation mask, set by a
            `BaseSegmenter` stage (e.g. `SAM2Segmenter`). `None` until
            a segmenter has run.
        tracking_id: Persistent identity linking this detection to the
            same physical object across frames. `None` until a
            tracker stage exists.
        depth: Estimated depth at this detection. `None` until a depth
            stage exists.
        position_3d: 3D position derived from `depth` and camera
            intrinsics. `None` until a depth stage exists.
        attributes: Open-ended bag for additional per-detection data
            (color, material, VLM-derived descriptions, ...) that
            doesn't warrant its own field.
    """

    label: str
    confidence: float
    bbox: List[float]

    mask: Optional[Mask] = None
    tracking_id: Optional[int] = None
    depth: Optional[float] = None
    position_3d: Optional[List[float]] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
