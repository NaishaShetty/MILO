"""
depth_anything_estimator.py

Purpose
-------
`BaseDepthEstimator` implementation backed by Depth Anything V2 (Small),
run through this project's existing `ModelManager` model-loading
convention (same pattern as `GroundingDINODetector`/`SAM2Segmenter`).
This is the "PREDICTED DEPTH" side of the ground-truth-vs-predicted
distinction: a learned monocular estimate, usable on real camera frames
where no simulator oracle exists, and for `Experiment 1` in the spec
(ground truth vs. predicted depth) once both are wired up identically
behind `BaseDepthEstimator`.

Why this specific checkpoint
---------------------------------
`config/model_config.py::DEPTH_ANYTHING` already points at
`depth-anything/Depth-Anything-V2-Small-hf` -- it was pre-registered
before this phase started. This is the smallest model in the family,
consistent with the project's stated preference for "the simplest
technically appropriate implementation" over a heavier depth model.

CRITICAL: this checkpoint's output is RELATIVE, not metric
------------------------------------------------------------------
Depth-Anything-V2-Small (the non-metric variant) predicts *relative*
inverse depth -- a per-pixel value that is larger for closer surfaces,
with no fixed physical scale. It is NOT interchangeable with
`GroundTruthDepthEstimator`'s meters, and code must never format its
output with a "m" unit or feed it into anything that assumes metric
depth without an explicit scale-alignment step.

This class converts the model's raw relative output into a positive
"pseudo-depth" (`1 / (raw_relative + epsilon)`, so smaller values are
closer -- the same *ordering* convention as ground-truth meters) purely
so it can flow through `BaseDepthEstimator`'s shared object-depth
extraction and be drawn on the same depth-colormap visualizer.
`scene.metadata[SceneMetadata.DEPTH_SOURCE] == "depth_anything"` is the
signal every consumer must check before treating a number as physical
meters (only `"ground_truth"` is). The benchmark
(`backend/vision_evaluation/`) performs an explicit median-ratio scale
alignment against ground truth before computing any error metric --
raw/unaligned comparison would be meaningless.

Sandbox note: this class downloads and runs a real model and cannot be
exercised in this project's CI or in the environment this code was
written in (no GPU, network model download would be required) -- see
`docs/architecture/spatial_perception.md`'s limitations section. Its
logic that doesn't require the real model (relative-to-pseudo-depth
conversion) is unit-tested with a synthetic `predicted_depth` tensor in
`backend/tests/test_vision_depth.py`.
"""

import numpy as np
import torch
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

from config.model_config import DEPTH_ANYTHING, get_device
from config.model_manager import ModelManager
from scene.scene import Scene
from vision.depth.base_depth_estimator import BaseDepthEstimator

# Avoids a division blowup where the model predicts exactly zero relative
# depth (a degenerate/background pixel) -- keeps the reciprocal finite
# instead of producing `inf`, which would otherwise poison the
# max-plausible-depth filter in `BaseDepthEstimator._extract_object_depth`.
_RELATIVE_DEPTH_EPSILON = 1e-6


def relative_to_pseudo_depth(relative_depth: np.ndarray) -> np.ndarray:
    """Converts Depth Anything's raw relative (larger-is-closer) output
    into a positive pseudo-depth map (smaller-is-closer, matching
    ground-truth depth's ordering) -- pulled out as a standalone function
    so it's testable with a synthetic array, without constructing
    `DepthAnythingEstimator` (which loads a real model). See module
    docstring for why this is still NOT metric depth."""

    return 1.0 / (relative_depth + _RELATIVE_DEPTH_EPSILON)


class DepthAnythingEstimator(BaseDepthEstimator):
    """Depth source backed by Depth Anything V2 (Small), a monocular
    relative-depth model. See module docstring for the relative-depth
    caveat before using this class's output as if it were metric."""

    def __init__(self, config=None, intrinsics=None):

        super().__init__(config=config, intrinsics=intrinsics)

        self.device = get_device()

        print("Loading Depth Anything V2 (Small)...")
        print("Using device:", self.device)

        manager = ModelManager(DEPTH_ANYTHING)
        self.processor, self.model = manager.load(
            AutoImageProcessor,
            AutoModelForDepthEstimation,
            device=self.device,
        )

        print("Depth Anything loaded successfully.")

    @property
    def source_name(self) -> str:
        return "depth_anything"

    def _get_depth_map(self, image, scene: Scene):
        """Runs Depth Anything on `image`, returns a positive
        pseudo-depth map at `image`'s resolution (see module docstring
        for the relative -> pseudo-depth conversion and why it is not
        metric)."""

        inputs = self.processor(images=image, return_tensors="pt").to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs)

        # `post_process_depth_estimation` resizes the model's native
        # (smaller) output resolution back up to the input frame's
        # resolution, so every detection's bbox/mask (both in original
        # image coordinates) can index directly into the returned map.
        processed = self.processor.post_process_depth_estimation(
            outputs, target_sizes=[image.shape[:2]]
        )[0]

        relative_depth = processed["predicted_depth"].cpu().numpy()

        return relative_to_pseudo_depth(relative_depth)
