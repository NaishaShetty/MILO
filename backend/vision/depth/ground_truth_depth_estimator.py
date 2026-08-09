"""
ground_truth_depth_estimator.py

Purpose
-------
`BaseDepthEstimator` implementation backed by AI2-THOR's ground-truth
depth rendering. This is the "GROUND-TRUTH DEPTH" side of the ground-
truth-vs-predicted distinction the project spec requires: an oracle
depth signal from the simulator, used as a reference for experiments and
as the default depth source for tracking/scene-graph work that doesn't
want a learned model's noise in the loop.

Why a `depth_provider` callable, not a `Simulator` reference
------------------------------------------------------------------
Passing a whole `Simulator` in would let this class reach for
`simulator.move_ahead()` or anything else on that interface, when all it
actually needs is "get me the current depth frame." A single bound
method (`simulator.get_depth`) is the minimal capability this class
needs, keeps it trivially unit-testable with a plain lambda/stub (see
`backend/tests/test_vision_depth.py`), and means `VisionAgent.perceive()`
-- a frozen method -- never needs to change to support this: the
`Simulator` is only ever touched by whoever *constructs* the pipeline
(`vision/factory.py`), not by `VisionAgent` itself.

Depth units
-----------
AI2-THOR's `depth_frame` is already per-pixel distance in meters (see
`simulator/ai2thor_env.py::get_depth`'s docstring) -- no conversion is
performed here. This is the single source of truth for "what a meter
means" in this project; `DepthAnythingEstimator`'s docstring documents
why its output cannot be compared to this one without a scale-alignment
step.
"""

from typing import Callable, Optional

import numpy as np

from scene.scene import Scene
from vision.depth.base_depth_estimator import BaseDepthEstimator


class GroundTruthDepthEstimator(BaseDepthEstimator):
    """Depth source backed by AI2-THOR's ground-truth depth rendering."""

    def __init__(
        self,
        depth_provider: Callable[[], Optional[np.ndarray]],
        config=None,
        intrinsics=None,
    ):
        """
        Args:
            depth_provider: Zero-argument callable returning the current
                frame's ground-truth depth map (meters), or `None` if
                unavailable. Typically `simulator.get_depth` -- requires
                the simulator to have been constructed with
                `render_depth=True` (see `simulator/simulator.py`).
            config: See `BaseDepthEstimator.__init__`.
            intrinsics: See `BaseDepthEstimator.__init__`.
        """

        super().__init__(config=config, intrinsics=intrinsics)

        self._depth_provider = depth_provider

    @property
    def source_name(self) -> str:
        return "ground_truth"

    def _get_depth_map(self, image, scene: Scene):
        """Returns the simulator's current ground-truth depth frame.

        Ignores `image`/`scene` -- the depth frame is read directly from
        the simulator via `self._depth_provider`, which is expected to
        reflect the same simulation step `image` was captured from
        (both `VisionAgent.get_rgb_image()` and `simulator.get_depth()`
        read `controller.last_event`, so they are consistent as long as
        no `controller.step()` happens in between -- true for
        `VisionAgent.perceive()`, which reads RGB before this stage
        runs).
        """

        return self._depth_provider()
