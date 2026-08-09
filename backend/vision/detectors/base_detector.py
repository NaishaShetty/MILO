"""
base_detector.py

Purpose
-------
Defines the common interface every object detector must implement.

Responsibilities
-----------------
- Declare the `process(image, scene)` contract: given an RGB frame and
  a `Scene` to enrich, add detections to that `Scene` and return it.
- Nothing else. This file has zero knowledge of any specific model,
  framework, or loading mechanism.

Why this abstraction exists
-----------------------------
`VisionAgent` (and, later, the planner) should depend on "a detector"
-- not specifically on Grounding DINO. Coding against this interface
means a future detector (a different zero-shot model, a fine-tuned
closed-vocabulary model, ...) can be substituted by implementing
`BaseDetector` and swapping the concrete class that gets constructed;
no caller has to change.

Why `process(image, scene)` instead of `detect(image, prompt) -> Scene`
-------------------------------------------------------------------------
A perception pipeline is a sequence of stages that each enrich the same
`Scene`: a detector adds detections, a segmenter (future) adds masks to
those detections, a depth estimator (future) adds depth, a tracker
(future) adds tracking IDs. If detectors returned a brand-new `Scene`
while segmenters/depth/trackers needed the *existing* `Scene` (to
attach a mask to an already-detected object, for example), every stage
would have a differently-shaped signature and the pipeline could not
treat stages interchangeably.

`process(image, scene)` makes every stage read the same way: take the
current frame and the scene built so far, mutate the scene in place,
and return it (returned for convenience/chaining, e.g.
`scene = tracker.process(image, segmenter.process(image, detector.process(image, scene)))`
-- not because a new object is created).

A detector still needs a text prompt to know what to look for. Rather
than breaking the two-argument shape for detectors alone, the prompt
travels as part of the scene: callers set `scene.metadata["prompt"]`
before calling `process`. This keeps the *interface* uniform even
though only text-prompted detectors read that particular metadata key.

Location note
-------------
Lives under `vision/detectors/` (not top-level `backend/`) because it
is specifically the interface for the box-level detectors in this
package. `vision/segmenters`, `vision/depth`, and `vision/tracking`
are expected to define their own `process(image, scene)` methods with
their own base interfaces (their construction/config needs differ from
a detector's), matching this one's shape by convention rather than by
sharing this exact ABC.

Who is allowed to depend on this file
-----------------------------------------
`process(image, scene)` is one of the interfaces frozen by the Phase 2
API freeze (see `docs/architecture/api_contracts.md`) -- every
perception stage's `process` method keeps this exact two-argument
shape. `BaseDetector` itself, however, is an internal perception
interface: `PerceptionPipeline` and concrete detector implementations
depend on it, but Language/Planner/Memory/Execution/Frontend modules
should never import it directly -- they consume its output via
`VisionAgent.perceive()` and `Scene`.
"""

from abc import ABC, abstractmethod


class BaseDetector(ABC):
    """Interface every object detector must implement.

    A `PerceptionPipeline` stage that adds `Detection` objects to a
    `Scene`. See the module docstring for why `process(image, scene)`
    is shaped the way it is.
    """

    @abstractmethod
    def process(self, image, scene):
        """Detects objects in an RGB image and adds them to `scene`.

        Part of the frozen `process(image, scene)` contract shared by
        every perception stage (see
        `docs/architecture/api_contracts.md`).

        Args:
            image: RGB `numpy.ndarray`.
            scene: The `Scene` being built for this frame.
                Text-prompted detectors read their prompt from
                `scene.metadata[SceneMetadata.DETECTION_PROMPT]`.

        Returns:
            The same `Scene`, with detections added.
        """
        pass
