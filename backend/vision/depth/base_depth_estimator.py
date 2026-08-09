"""
base_depth_estimator.py

Purpose
-------
Defines the common interface every depth source implements, plus the
shared logic for turning a per-pixel depth map into per-object depth and
3D position -- the "Depth Estimation" and part of the "2D -> 3D
Localization" subsystems (Phase 3.x.2 / 3.x.3).

Why one base class for two very different depth sources
-------------------------------------------------------------
`GroundTruthDepthEstimator` (AI2-THOR) and `DepthAnythingEstimator`
(learned, monocular) could not be more different in how they produce a
depth map -- one reads it from the simulator, the other runs a neural
network. But once *some* per-pixel depth map exists, turning it into
"how far is this specific detected object" is exactly the same problem
either way: sample the mask (or bbox) region, take a robust statistic,
check how much of it was valid. Duplicating that logic in both classes
would be the exact "no duplicated logic" anti-pattern this project's
engineering requirements call out, and would risk the two sources
silently drifting (e.g. one clamping implausible readings, the other
not). So this class implements `process()` as a template method:
subclasses only supply `_get_depth_map()` (source-specific) and
`source_name` (for `SceneMetadata.DEPTH_SOURCE`); everything after that
is shared and tested once.

Ground-truth vs. predicted depth: never blurred
----------------------------------------------------
Every `Scene` this stage touches gets
`scene.metadata[SceneMetadata.DEPTH_SOURCE]` stamped with either
`"ground_truth"` or `"depth_anything"` (from `source_name`) so nothing
downstream (UI, scene graph, benchmark) can mistake one for the other.
`DepthAnythingEstimator`'s docstring documents why its output is
*relative*, not metric -- this base class deliberately does not try to
"fix" that distinction, only to preserve it.

Object-level depth: robust, not bbox-center
------------------------------------------------
Per the project spec, a single bbox-center pixel is not used when a mask
is available: `_extract_object_depth` takes the **median** depth over
all valid pixels within `detection.mask.binary` when a mask exists,
falling back to the bbox region only when it doesn't (i.e. before
`SAM2Segmenter` has run, or the pipeline is configured without a
segmenter at all). Median (not mean) is used because it's robust to a
few background/edge pixels leaking into the mask or bbox, which a mean
would be dragged by.

2D -> 3D localization is folded in here, not a separate pipeline stage
----------------------------------------------------------------------------
See `vision/spatial/localization.py`'s module docstring for why:
localization is a pure function of `(depth, bbox_center, intrinsics)`
with no state of its own, and adding a 6th `PerceptionPipeline` stage
would mean changing that class's frozen constructor signature for no
benefit. `CameraIntrinsics` is therefore an optional constructor
argument here -- when supplied, `process()` also fills
`Detection.position_3d` right after `Detection.depth`; when omitted
(e.g. intrinsics genuinely unknown), depth is still estimated but
`position_3d` stays `None`.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple

import numpy as np

from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from vision.depth.depth_config import DepthConfig
from vision.spatial.camera_intrinsics import CameraIntrinsics
from vision.spatial.localization import bbox_center, pixel_depth_to_camera_point


class BaseDepthEstimator(ABC):
    """Interface every depth source must implement.

    A `PerceptionPipeline` stage that fills `Scene.depth_image`,
    `Detection.depth`, and (when intrinsics are configured)
    `Detection.position_3d`.
    """

    def __init__(
        self,
        config: Optional[DepthConfig] = None,
        intrinsics: Optional[CameraIntrinsics] = None,
    ):
        """
        Args:
            config: Thresholds for what counts as valid object-level
                depth. Defaults to `DepthConfig.from_env()`.
            intrinsics: Camera intrinsics used to also fill
                `Detection.position_3d`. `None` means "2D depth only,
                no 3D localization" -- a valid, supported configuration
                (see module docstring).
        """

        self.config = config or DepthConfig.from_env()
        self.intrinsics = intrinsics

    # ------------------------------------------------------------------
    # Subclass responsibility: source-specific depth map production.
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def source_name(self) -> str:
        """`"ground_truth"` or `"depth_anything"` -- stamped onto
        `scene.metadata[SceneMetadata.DEPTH_SOURCE]` by `process()` so
        every downstream consumer can tell which kind of depth this
        scene carries."""
        raise NotImplementedError

    @abstractmethod
    def _get_depth_map(self, image: np.ndarray, scene: Scene) -> Optional[np.ndarray]:
        """Produces a per-pixel depth map, in meters, for `image`.

        Args:
            image: RGB `numpy.ndarray` for the current frame.
            scene: The `Scene` being built for this frame.

        Returns:
            A `(H, W)` `float` array of depth in meters (invalid pixels
            as `NaN` or `<= 0`), or `None` if depth is unavailable this
            call (e.g. the simulator wasn't started with
            `render_depth=True`) -- `process()` treats `None` as "no
            depth this frame" and leaves every detection's depth unset
            rather than raising, so a misconfigured depth source
            degrades a scene rather than crashing perception entirely.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared template method -- do not override.
    # ------------------------------------------------------------------

    def process(self, image: np.ndarray, scene: Scene) -> Scene:
        """Fills depth (and, if configured, 3D position) for `scene`.

        Part of the frozen `process(image, scene)` contract shared by
        every perception stage (see
        `docs/architecture/api_contracts.md`).

        Args:
            image: RGB `numpy.ndarray`.
            scene: The `Scene` being built for this frame.

        Returns:
            The same `Scene`, with `depth_image` set (when available),
            `metadata[SceneMetadata.DEPTH_SOURCE]` stamped, and each
            detection's `depth`/`position_3d` filled in where the
            underlying pixels were valid enough (see
            `_extract_object_depth`).
        """

        depth_map = self._get_depth_map(image, scene)

        scene.depth_image = depth_map
        scene.metadata[SceneMetadata.DEPTH_SOURCE] = self.source_name

        if depth_map is None:
            return scene

        for detection in scene.detections:

            depth_value, valid_ratio = self._extract_object_depth(depth_map, detection)

            detection.attributes["depth_valid_pixel_ratio"] = valid_ratio

            if depth_value is None:
                continue

            detection.depth = depth_value

            if self.intrinsics is not None:

                center = bbox_center(detection.bbox)

                if center is not None:
                    u, v = center
                    detection.position_3d = pixel_depth_to_camera_point(
                        u, v, depth_value, self.intrinsics
                    )

        return scene

    def _extract_object_depth(
        self, depth_map: np.ndarray, detection
    ) -> Tuple[Optional[float], float]:
        """Robust object-level depth: median over valid pixels.

        Uses `detection.mask.binary` when a segmenter has already run
        (pixel-accurate), otherwise falls back to the detection's bbox
        region -- see module docstring for why a single bbox-center
        pixel is never used.

        Returns:
            `(depth_meters, valid_pixel_ratio)`. `depth_meters` is
            `None` (an explicit "missing/invalid depth" state, not `0`
            or a guess) when `valid_pixel_ratio` is below
            `self.config.min_valid_pixel_ratio`, when the sampled region
            is empty, or when the detection's mask/bbox falls outside
            `depth_map`'s bounds.
        """

        if detection.mask is not None:
            region_mask = detection.mask.binary
        else:
            region_mask = self._bbox_region_mask(depth_map.shape, detection.bbox)

        if region_mask is None or not region_mask.any():
            return None, 0.0

        region_depths = depth_map[region_mask]

        valid = (
            np.isfinite(region_depths)
            & (region_depths > 0)
            & (region_depths <= self.config.max_plausible_depth_meters)
        )

        valid_ratio = float(valid.sum()) / float(region_depths.size)

        if valid_ratio < self.config.min_valid_pixel_ratio:
            return None, valid_ratio

        return float(np.median(region_depths[valid])), valid_ratio

    @staticmethod
    def _bbox_region_mask(
        depth_map_shape: Tuple[int, ...], bbox
    ) -> Optional[np.ndarray]:
        """Boolean `(H, W)` mask selecting the bbox interior, clipped to
        `depth_map_shape` -- the fallback sampling region when no
        segmentation mask is available yet."""

        height, width = depth_map_shape[0], depth_map_shape[1]

        x1, y1, x2, y2 = bbox

        x1_i = max(0, int(round(x1)))
        y1_i = max(0, int(round(y1)))
        x2_i = min(width, int(round(x2)))
        y2_i = min(height, int(round(y2)))

        if x2_i <= x1_i or y2_i <= y1_i:
            return None

        region = np.zeros((height, width), dtype=bool)
        region[y1_i:y2_i, x1_i:x2_i] = True

        return region
