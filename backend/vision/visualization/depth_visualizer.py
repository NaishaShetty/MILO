"""
depth_visualizer.py

Purpose
-------
Renders `Scene.depth_image` as a false-color heatmap, so a person can
visually distinguish near/far objects -- the "Depth Visualization" UI
requirement (RGB view vs. depth view). A separate `BaseVisualizer`
implementation from `SceneVisualizer` (which draws detections/masks/
labels onto the *RGB* image) because depth visualization operates on an
entirely different array (`scene.depth_image`, a float depth map, not
`image`) and has a fundamentally different concern: representing a
continuous scalar field with a color scale and a legend, not drawing
discrete per-object annotations.

Legend, not an implicit color scale
----------------------------------------
Per the project spec: "Do not imply that colors correspond to physical
distances unless the scale is defined." This class never just returns a
colored image -- `render()` returns `(image, DepthColormapLegend)`,
where the legend carries the exact min/max meters the color scale was
normalized against, computed fresh from whatever depth values are
actually present in `scene.depth_image` for that call. A caller (the
API layer) is expected to surface `min_depth_m`/`max_depth_m` next to
the image, not just the colors alone.

No depth, no image
-----------------------
If `scene.depth_image` is `None` (no depth stage configured, or depth
was unavailable for this frame -- see `base_depth_estimator.py`),
`render()` returns `(None, None)` rather than fabricating a blank/black
image that could be mistaken for "depth measured as zero everywhere."
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from vision.visualization.base_visualizer import BaseVisualizer

# OpenCV colormap used to render depth. TURBO (added in OpenCV 4.1.2) is
# chosen over the older JET map because it is perceptually more uniform
# and easier to read distance ordering from, while still being a
# familiar "cool = near/warm = far" (or vice versa, see `render`'s
# convention below) style scale.
DEPTH_COLORMAP = cv2.COLORMAP_TURBO


@dataclass(frozen=True)
class DepthColormapLegend:
    """Describes what a depth colormap image's colors actually mean.

    Attributes:
        min_depth_m: Depth value (meters, or Depth Anything's pseudo-
            depth -- see `depth_anything_estimator.py`) mapped to one
            end of the color scale.
        max_depth_m: Depth value mapped to the other end of the color
            scale.
        colormap_name: Human-readable name of the OpenCV colormap used,
            for display alongside the image.
        near_is: Which end of the scale `min_depth_m` renders as --
            `"warm"` or `"cool"` -- so a legend/caption can be built
            without the caller needing to know this class's internals.
    """

    min_depth_m: float
    max_depth_m: float
    colormap_name: str = "TURBO"
    near_is: str = "cool"


class DepthVisualizer(BaseVisualizer):
    """Renders `scene.depth_image` as a false-color heatmap with an
    explicit legend. See module docstring for why a legend is mandatory
    here, not optional."""

    def process(self, image, scene):
        """See `BaseVisualizer.process`. Delegates to `render`, but
        note this class's `render` returns a `(image, legend)` tuple,
        not a bare image -- see module docstring."""

        return self.render(image, scene)

    def render(
        self, image, scene
    ) -> Tuple[Optional[np.ndarray], Optional[DepthColormapLegend]]:
        """Renders `scene.depth_image` as a false-color heatmap.

        Args:
            image: Unused -- kept for the shared `process(image, scene)`
                shape convention (see `base_visualizer.py`); this
                visualizer draws `scene.depth_image`, not `image`.
            scene: The `Scene` whose `depth_image` is rendered.

        Returns:
            `(colormap_image, legend)` -- an RGB `numpy.ndarray` and its
            `DepthColormapLegend`, or `(None, None)` if
            `scene.depth_image` is `None`.
        """

        depth_map = scene.depth_image

        if depth_map is None:
            return None, None

        valid = np.isfinite(depth_map) & (depth_map > 0)

        if not valid.any():
            return None, None

        min_depth = float(depth_map[valid].min())
        max_depth = float(depth_map[valid].max())

        normalized = np.zeros(depth_map.shape, dtype=np.uint8)

        if max_depth > min_depth:
            scaled = (depth_map - min_depth) / (max_depth - min_depth)
            scaled = np.clip(scaled, 0.0, 1.0)
        else:
            # A perfectly flat depth map (every valid pixel equidistant)
            # -- avoid a division by zero; render it as uniformly "near"
            # rather than crashing.
            scaled = np.zeros(depth_map.shape, dtype=float)

        normalized[valid] = (scaled[valid] * 255).astype(np.uint8)

        colored_bgr = cv2.applyColorMap(normalized, DEPTH_COLORMAP)
        colored_bgr[~valid] = (0, 0, 0)  # invalid depth renders as black

        colored_rgb = cv2.cvtColor(colored_bgr, cv2.COLOR_BGR2RGB)

        legend = DepthColormapLegend(min_depth_m=min_depth, max_depth_m=max_depth)

        return colored_rgb, legend
