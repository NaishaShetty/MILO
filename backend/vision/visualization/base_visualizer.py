"""
base_visualizer.py

Purpose
-------
Defines the common interface every scene visualizer must implement.

Responsibilities
-----------------
- Declare the `process(image, scene)` contract: given an RGB frame and
  the `Scene` produced for it, return a new rendered image with that
  scene drawn on top.
- Nothing else. This file has zero knowledge of any specific drawing
  library, color scheme, or which fields of `Scene` get drawn.

Why this abstraction exists
-----------------------------
Every other perception stage (`BaseDetector`, `BaseSegmenter`) enriches
a `Scene` by mutating it in place. A visualizer is fundamentally
different: it is a *consumer* of a finished `Scene`, not a producer.
Coding this as its own interface -- rather than reusing
`BaseDetector`/`BaseSegmenter` -- makes that distinction explicit and
lets `VisionAgent` and callers reason about visualizers as a separate,
optional, side-effect-free final step.

IMPORTANT -- visualizers never modify Scene
---------------------------------------------
A visualizer's `process(image, scene)` must treat both arguments as
read-only. It reads `scene.detections` (labels, confidences, boxes,
masks) to decide what to draw, but it must never assign to `scene`,
mutate any `Detection`, or write back into `image`. The only new data
a visualizer produces is a brand-new rendered image it returns; the
`Scene` handed in is exactly the `Scene` a caller still has after the
call returns. This is what lets a visualizer safely run after the
perception pipeline has finished, be called multiple times on the same
scene (e.g. once for a debug window, once for a saved file), or be run
in a context where the scene is still needed for planning afterward.

Visualizers also never perform AI inference. They do not load models,
run a forward pass, or produce new detections/masks -- they only
render what a `Scene` already contains. This keeps rendering fully
decoupled from perception: the same visualizer works whether the
`Scene` came from Grounding DINO + SAM2 today, or from a depth
estimator, tracker, or scene-graph module added later.

Who is allowed to depend on this file
-----------------------------------------
`BaseVisualizer` is not part of the Phase 2 API freeze -- unlike
`BaseDetector`/`BaseSegmenter`/`BaseSceneGraph`, it is not a
`PerceptionPipeline` stage, since rendering happens after perception
finishes (see the module docstring above). It is documented and
Google-style-docstringed to the same standard as the frozen interfaces
for consistency, and its `process(image, scene)` shape follows the
same contract by convention, but callers depending on rendering
specifically should use `SceneVisualizer.render()` (or `process()`,
its `BaseVisualizer`-required alias) directly rather than treating it
as a `PerceptionPipeline`-composable stage.
"""

from abc import ABC, abstractmethod


class BaseVisualizer(ABC):
    """Interface every scene visualizer must implement.

    A read-only consumer of a finished `Scene`: renders it onto its
    source image and returns a new image, without performing
    inference or mutating either argument. See the module docstring
    for the full read-only contract.
    """

    @abstractmethod
    def process(self, image, scene):
        """Renders `scene` on top of `image` and returns the result.

        Follows the same `process(image, scene)` shape every
        perception stage uses, by convention (see the module
        docstring for why this is not a `PerceptionPipeline` stage).

        Args:
            image: RGB `numpy.ndarray` -- the frame `scene` was
                produced from. Must not be modified in place.
            scene: The `Scene` to render (detections, masks, ...).
                Must not be modified.

        Returns:
            A new RGB `numpy.ndarray` with `scene` drawn on top of
            `image`.
        """
        pass
