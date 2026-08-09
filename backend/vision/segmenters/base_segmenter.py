"""
base_segmenter.py

Purpose
-------
Defines the common interface every image segmentation model must
implement.

Responsibilities
-----------------
- Declare the `process(image, scene)` contract for segmenters
  specifically: given an RGB frame and a `Scene` whose detections
  already exist, attach a pixel-accurate `Mask` to each one and return
  the same `Scene`.
- Nothing else. This file has zero knowledge of any specific model
  (SAM2 or otherwise), framework, or loading mechanism.

Why this abstraction exists
-----------------------------
Mirrors `vision/detectors/base_detector.py`'s reasoning: `VisionAgent`
and `PerceptionPipeline` should depend on "a segmenter," not
specifically on SAM2, so a future segmenter (point-prompted,
automatic-mask-generation, a different model entirely) can be
substituted by implementing `BaseSegmenter` and swapping the concrete
class constructed -- no caller has to change.

A segmenter enriches an existing `Scene` and, unlike a detector, NEVER
creates new objects -- it operates only on detections already present,
attaching pixel-accurate masks to them:

Scene
   |
detections
   |
SAM2 (or a future segmenter)
   |
Detection.mask

Who is allowed to depend on this file
-----------------------------------------
`process(image, scene)` is one of the interfaces frozen by the Phase 2
API freeze (see `docs/architecture/api_contracts.md`) -- every
perception stage's `process` method keeps this exact two-argument
shape. `BaseSegmenter` itself is an internal perception interface:
`PerceptionPipeline` and concrete segmenter implementations depend on
it, but Language/Planner/Memory/Execution/Frontend modules should
never import it directly -- they consume its output via
`VisionAgent.perceive()` and `Scene`.
"""

from abc import ABC, abstractmethod

from scene.scene import Scene


class BaseSegmenter(ABC):
    """Interface every image segmentation model must implement.

    A `PerceptionPipeline` stage that attaches a `Mask` to each
    existing `Detection` in a `Scene`, without creating new
    detections.
    """

    @abstractmethod
    def process(self, image, scene: Scene) -> Scene:
        """Enriches the supplied `Scene` with segmentation masks.

        Part of the frozen `process(image, scene)` contract shared by
        every perception stage (see
        `docs/architecture/api_contracts.md`).

        Args:
            image: RGB `numpy.ndarray` -- the same frame the
                detections in `scene` were produced from.
            scene: The `Scene` being built for this frame. Each
                existing `scene.detections[i].bbox` is expected to be
                used as a segmentation prompt.

        Returns:
            The same `Scene`, with `mask` set on every detection.
        """
        pass
