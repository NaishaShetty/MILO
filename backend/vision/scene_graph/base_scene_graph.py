"""
base_scene_graph.py

Purpose
-------
Defines the common interface every scene-graph generator must
implement.

Why it exists
-------------
`PerceptionPipeline` treats every perception stage identically -- it
iterates a list of configured stages and calls `process(image, scene)`
on each, with no special case per stage type (see
`vision/pipeline/perception_pipeline.py`). For a scene-graph stage to
participate in that pipeline the same way `BaseDetector` and
`BaseSegmenter` implementations already do, it needs to expose the
exact same `process(image, scene) -> Scene` shape. This file declares
that contract for scene-graph generators specifically, mirroring
`vision/detectors/base_detector.py` and
`vision/segmenters/base_segmenter.py`.

Where it fits in the overall architecture
-------------------------------------------
Sits alongside `BaseDetector` and `BaseSegmenter` as one more
perception-stage interface. Like a segmenter, a scene-graph generator
never creates new detections -- it only reads detections (and their
masks, if present) already in `scene` and adds `Relationship` objects
describing how they relate. The `Scene` is enriched, never replaced:
implementations append to `scene.relationships` and return the same
`scene` object handed in.

Which future modules will depend on this
--------------------------------------------
- `heuristic_scene_graph.HeuristicSceneGraph` implements this
  interface today, using bounding-box/mask geometry.
- Any future learned scene-graph model (e.g. a GNN or VLM-based
  relationship classifier) implements this same interface, so it can
  be substituted for `HeuristicSceneGraph` in `PerceptionPipeline`
  without changing `VisionAgent`, `PerceptionPipeline`, or any other
  stage.

Who is allowed to depend on this file
-----------------------------------------
`process(image, scene)` is one of the interfaces frozen by the Phase 2
API freeze (see `docs/architecture/api_contracts.md`) -- every
perception stage's `process` method keeps this exact two-argument
shape. `BaseSceneGraph` itself is an internal perception interface:
`PerceptionPipeline` and concrete scene-graph implementations depend
on it, but Language/Planner/Memory/Execution/Frontend modules should
never import it directly -- they consume its output via
`VisionAgent.perceive()` and `Scene.relationships`.
"""

from abc import ABC, abstractmethod

from scene.scene import Scene


class BaseSceneGraph(ABC):
    """Interface for a scene-graph generation perception stage.

    Infers relationships between a `Scene`'s existing detections and
    appends `Relationship` objects to `scene.relationships`, without
    creating or modifying detections.
    """

    @abstractmethod
    def process(self, image, scene: Scene) -> Scene:
        """Infers relationships and appends them to `scene`.

        Part of the frozen `process(image, scene)` contract shared by
        every perception stage (see
        `docs/architecture/api_contracts.md`).

        Args:
            image: RGB `numpy.ndarray` -- the same frame the
                detections in `scene` were produced from.
                Implementations that only reason over bounding
                boxes/masks may not need it, but it is part of the
                shared `process(image, scene)` contract every
                perception stage follows, and future implementations
                (e.g. ones that read pixel appearance, such as
                "touching" cues) will need it.
            scene: The `Scene` being built for this frame. Detections
                (`scene.detections`, with `bbox` and, if a segmenter
                ran first, `mask`) are read to infer relationships
                between them.

        Returns:
            The same `Scene`, with `Relationship` objects appended to
            `scene.relationships`.
        """
        pass
