"""
base_tracker.py

Purpose
-------
Defines the common interface every object tracker must implement. This
is the "Object Tracking" subsystem (Phase 3.x.4) -- temporal association
of detections across frames, nothing more.

Scope boundary (read before adding anything here)
-------------------------------------------------------
Per the project spec, a tracker is responsible ONLY for temporal object
association -- assigning `Detection.tracking_id` so the same physical
object keeps the same ID across frames. It must NOT perform language
understanding, LLM reasoning, planning, memory, execution, or scene-
graph reasoning. `BaseTracker` enforces this by shape: `process(image,
scene)` takes and returns a `Scene`, the same as every other perception
stage, and nothing about this interface invites a tracker to reach
outside that.

Why this abstraction exists
-----------------------------
Mirrors `vision/detectors/base_detector.py`/`vision/segmenters
/base_segmenter.py`: `VisionAgent`/`PerceptionPipeline` should depend on
"a tracker," not specifically on IoU matching, so a future tracker
(appearance-feature re-ID, a learned tracker) can be substituted by
implementing `BaseTracker` and swapping the concrete class constructed.

Statefulness note
-------------------
Unlike a detector or segmenter, a tracker is inherently stateful across
calls -- it must remember previous frames' tracks to link them to the
current frame's detections. `PerceptionPipeline` still calls
`process(image, scene)` on the same tracker instance every time (it
holds one instance per stage for the pipeline's lifetime -- see
`perception_pipeline.py`), so a concrete tracker keeps its state on
`self` between calls; nothing about that requires changing the frozen
`PerceptionPipeline`/`process(image, scene)` contract.
"""

from abc import ABC, abstractmethod

from scene.scene import Scene


class BaseTracker(ABC):
    """Interface every object tracker must implement.

    A `PerceptionPipeline` stage that assigns `Detection.tracking_id`
    to link detections across frames. See module docstring for the
    strict scope boundary (temporal association only).
    """

    @abstractmethod
    def process(self, image, scene: Scene) -> Scene:
        """Associates `scene`'s detections with tracks from prior frames.

        Part of the frozen `process(image, scene)` contract shared by
        every perception stage (see
        `docs/architecture/api_contracts.md`).

        Args:
            image: RGB `numpy.ndarray` for the current frame. Most
                tracking strategies (IoU, 3D-proximity) don't need the
                pixels themselves, but the parameter is kept for
                interface uniformity and to leave room for a future
                appearance-feature tracker that does.
            scene: The `Scene` being built for this frame, with
                `detections` already populated by earlier stages.

        Returns:
            The same `Scene`, with `tracking_id` set on every detection
            that was matched to (or started) a track.
        """
        raise NotImplementedError
