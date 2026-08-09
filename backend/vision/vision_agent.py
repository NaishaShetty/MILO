"""
vision_agent.py

Purpose
-------
This file implements the Vision Agent, which serves as the robot's
perception interface.

Why it is needed
----------------
The simulator provides raw RGB images, but the rest of the system
(planner, memory, language modules) should never interact with the
simulator directly.

Instead, they request visual information through the Vision Agent.

Responsibilities
-----------------
- Retrieve raw RGB frames from the Simulator (unchanged from before).
- Orchestrate the perception pipeline: build a `Scene` for the current
  frame, then run it through each configured perception stage in
  order (detector, then segmenter, ...), each stage enriching the same
  `Scene` via its `process(image, scene)` method.

Why orchestration lives in PerceptionPipeline, not here
-----------------------------------------------------------
Each perception module (`GroundingDINODetector`, `SAM2Segmenter`, a
future depth estimator, tracker, scene-graph builder) only knows how
to enrich a `Scene` it's handed -- none of them know what order stages
should run in, or which stages are enabled for a given deployment.
That sequencing used to live directly in `VisionAgent.perceive()`, but
was pulled out into `vision.pipeline.PerceptionPipeline` so this class
stays focused on its one job -- acquiring frames -- while the list of
perception stages can grow (depth, tracking, scene graph) without
`VisionAgent` growing alongside it. See `perception_pipeline.py` for
the full rationale.

`VisionAgent` still accepts `detector`/`segmenter`/`depth`/`tracker`/
`scene_graph` as constructor keywords (all optional) rather than
requiring a pre-built `PerceptionPipeline`, so existing callers
(`VisionAgent(simulator, detector=..., segmenter=...)`) and
`VisionAgent(simulator)` for pure image retrieval (e.g.
`test_vision.py`) keep working unchanged. `VisionAgent` builds the
`PerceptionPipeline` itself from those keywords.

Who is allowed to depend on this file
-----------------------------------------
As of the Phase 2 API freeze (see
`docs/architecture/api_contracts.md`), `VisionAgent.perceive()` is a
frozen public interface. Every future module -- Language, Planner,
Memory, Execution, Frontend -- should acquire perception results by
constructing a `VisionAgent` and calling `perceive()`, not by
importing `PerceptionPipeline`, a detector, a segmenter, or any other
perception internal directly. `get_rgb_image()`/`save_image()` are
also public but are plain image-acquisition utilities, not part of
the perception contract, and carry no freeze guarantee beyond normal
backward-compatibility care.
"""

import cv2

from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from simulator.simulator import Simulator
from vision.pipeline.perception_pipeline import PerceptionPipeline


class VisionAgent:
    """The robot's perception interface.

    Acquires RGB frames from a `Simulator` and, when perception stages
    are configured, runs them through a `PerceptionPipeline` to
    produce a fully enriched `Scene`. This is the single entry point
    every other module (Language, Planner, Memory, Execution,
    Frontend) is expected to use for perception -- see
    `docs/architecture/api_contracts.md`.

    Attributes:
        simulator: The `Simulator` frames are read from.
        detector: The configured detector, or `None` if perception was
            not wired up (image-acquisition-only usage).
        pipeline: The `PerceptionPipeline` built from the stage
            keywords passed to `__init__`. Internal wiring detail --
            downstream code should call `perceive()`, not reach into
            `pipeline` directly.
    """

    # ----------------------------------------------------------------
    # Constructor
    # ----------------------------------------------------------------

    def __init__(
        self,
        simulator: Simulator,
        detector=None,
        segmenter=None,
        depth=None,
        tracker=None,
        scene_graph=None,
    ):
        """Initializes the agent and builds its perception pipeline.

        Args:
            simulator: The `Simulator` to acquire frames from.
            detector: Optional `BaseDetector` implementation. Required
                for `perceive()` to be callable; omit for pure image
                acquisition.
            segmenter: Optional `BaseSegmenter` implementation.
            depth: Optional depth-estimation stage (reserved; no
                implementation exists yet).
            tracker: Optional tracking stage (reserved; no
                implementation exists yet).
            scene_graph: Optional `BaseSceneGraph` implementation.
        """

        self.simulator = simulator
        self.detector = detector

        self.pipeline = PerceptionPipeline(
            detector=detector,
            segmenter=segmenter,
            depth=depth,
            tracker=tracker,
            scene_graph=scene_graph,
        )

    # ----------------------------------------------------------------
    # Public API -- image acquisition utilities
    # (public, but not part of the frozen perception contract)
    # ----------------------------------------------------------------

    def get_rgb_image(self):
        """Returns the current RGB image captured by the robot.

        Returns:
            An RGB `numpy.ndarray` for the simulator's current frame.
        """

        return self.simulator.get_rgb()

    def save_image(self, filename="camera_view.png"):
        """Saves the current RGB image to disk.

        Args:
            filename: Destination path for the saved image. Written
                as BGR (via `cv2.imwrite`) since the source frame is
                RGB.
        """

        image = self.get_rgb_image()

        image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        cv2.imwrite(filename, image_bgr)

        print(f"Image saved as {filename}")

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

    def perceive(self, prompt):
        """Runs the full perception pipeline on the current frame.

        Acquires the simulator's current RGB frame, seeds a fresh
        `Scene` with the given detection prompt, and runs it through
        every perception stage configured at construction time
        (detector, segmenter, depth, tracker, scene graph, in that
        order).

        Args:
            prompt: Text prompt describing which objects to detect,
                e.g. `"chair. table. mug. refrigerator."`. Stored at
                `scene.metadata[SceneMetadata.DETECTION_PROMPT]` for
                the configured detector to read.

        Returns:
            The `Scene` produced for this frame, enriched by every
            configured perception stage.

        Raises:
            ValueError: If no `detector` was configured at
                construction time.
        """

        if self.detector is None:
            raise ValueError(
                "VisionAgent.perceive requires a detector to be "
                "configured (VisionAgent(simulator, detector=...))."
            )

        image = self.get_rgb_image()

        scene = Scene()

        scene.metadata[SceneMetadata.DETECTION_PROMPT] = prompt

        return self.pipeline.process(image, scene)
