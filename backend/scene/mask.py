"""
mask.py

Purpose
-------
Defines the Mask data model: a segmentation result attached to a
Detection.

Responsibilities
-----------------
- Hold the raw binary mask plus the handful of properties that are
  cheap to compute once at creation time (`area`) or are naturally
  produced alongside it (`bbox`).
- Stay a plain data container -- Mask does not run segmentation,
  compute polygons/contours, or compare masks itself.

Why this abstraction exists
-----------------------------
A segmenter (SAM2) could just as easily set `detection.mask` to a raw
`np.ndarray`. The problem is everything you'd want to *do* with a mask
next -- polygon extraction, contour tracing, centroid, IoU against
another mask, visible ratio under occlusion -- is not a property of a
bare array. Without a wrapper, those become free functions scattered
across whichever module happens to need them first (`vision/`,
`scene/`, a notebook, ...), each one re-deriving how to interpret the
array (dtype, 0/1 vs 0/255, HxW vs HxWx1).

Wrapping the array in `Mask` now, even though only `binary`, `area`,
and `bbox` are populated today, gives future methods
(`Mask.polygon()`, `Mask.centroid()`, `Mask.iou(other)`,
`Mask.visible_ratio()`, ...) one obvious home, and lets `Detection`
type its `mask` field as `Optional[Mask]` instead of `Optional[Any]`.

`area` and `bbox` are stored (not computed on the fly) because a
segmenter naturally has both on hand at mask-creation time -- `area`
from summing the binary array once, `bbox` from the same box the
segmenter was prompted with or the mask's own tight bounding box.
Storing them avoids recomputing over the full array on every access.

Who is allowed to depend on this file
-----------------------------------------
As of the Phase 2 API freeze (see
`docs/architecture/api_contracts.md`), `Mask`'s field schema is a
frozen public interface. Every future module -- Language, Planner,
Memory, Execution, Frontend -- reading `Detection.mask` should rely on
this field set rather than on which segmenter produced it.
"""

from dataclasses import dataclass
from typing import List

import numpy as np


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
class Mask:
    """A single object's segmentation mask.

    A plain data container -- see the module docstring for why the
    raw array is wrapped rather than stored directly on `Detection`.

    Attributes:
        binary: Boolean `numpy.ndarray` of shape `(H, W)`, `True`
            where the object is present. `H`/`W` match the source
            image the mask was produced from.
        area: Pixel count of `binary` (i.e. `binary.sum()`), computed
            once at creation time.
        bbox: `[x1, y1, x2, y2]` bounding box associated with this
            mask -- typically the same box the segmenter was prompted
            with.
    """

    binary: np.ndarray
    area: int
    bbox: List[float]
