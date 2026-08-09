"""
factory.py

Purpose
-------
Single place that assembles a fully-wired `VisionAgent` -- detector,
segmenter, depth, tracker, and scene graph all configured and passed
into `VisionAgent`'s existing (frozen) constructor keywords. This is the
"Full Vision Integration" (Phase 3.x.8) glue: everything upstream of
this file (detectors, segmenters, depth estimators, trackers, scene
graph) is a modular, independently-testable piece; this file is the one
place that knows how they fit together for a real deployment.

Why this exists as its own module (not inlined into `api/routes/vision.py`)
--------------------------------------------------------------------------------
Two different callers need "a real, fully-configured `VisionAgent`":
the FastAPI vision route (`api/routes/vision.py`) and, later, a
benchmark script or the Phase 4 planner. Duplicating this wiring in each
caller would mean a config change (e.g. switching the default depth
source) has to be made in multiple places and could drift. Centralizing
it here means every caller constructs perception the same way, and this
is the only file that needs to change when a new perception stage
becomes part of the default pipeline.

What this file deliberately does NOT do
--------------------------------------------
It does not implement any perception logic itself -- it only imports and
constructs existing classes. It does not start the `Simulator` (the
caller owns that lifecycle, e.g. `api/app.py`'s lifespan, so it can
handle startup failure -- no Unity binary available -- without this
module needing to know about HTTP error handling). It does not touch the
frozen `PerceptionPipeline`/`VisionAgent` signatures; it only supplies
values for their existing optional keyword arguments.
"""

from dataclasses import dataclass
from typing import Optional

from simulator.simulator import Simulator
from vision.depth.base_depth_estimator import BaseDepthEstimator
from vision.depth.depth_anything_estimator import DepthAnythingEstimator
from vision.depth.ground_truth_depth_estimator import GroundTruthDepthEstimator
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.scene_graph.heuristic_scene_graph import HeuristicSceneGraph
from vision.segmenters.sam2_segmenter import SAM2Segmenter
from vision.spatial.camera_intrinsics import CameraIntrinsics
from vision.temporal.temporal_scene import TemporalScene
from vision.tracking.iou_tracker import IoUTracker
from vision.vision_agent import VisionAgent

# Depth source selector values accepted by `build_default_vision_agent`
# and `VISION_DEPTH_SOURCE` (see `docs/architecture/spatial_perception.md`).
DEPTH_SOURCE_GROUND_TRUTH = "ground_truth"
DEPTH_SOURCE_DEPTH_ANYTHING = "depth_anything"


def build_depth_estimator(
    depth_source: str, simulator: Simulator, intrinsics: Optional[CameraIntrinsics]
) -> BaseDepthEstimator:
    """Constructs the configured depth source.

    Args:
        depth_source: `DEPTH_SOURCE_GROUND_TRUTH` or
            `DEPTH_SOURCE_DEPTH_ANYTHING`.
        simulator: Used to bind `GroundTruthDepthEstimator`'s
            `depth_provider` to `simulator.get_depth` -- requires the
            simulator to have been started with `render_depth=True`
            (see `simulator/simulator.py`); this function does not
            start the simulator itself.
        intrinsics: Passed through so the estimator also fills
            `Detection.position_3d` (see `base_depth_estimator.py`).

    Returns:
        A `BaseDepthEstimator`.

    Raises:
        ValueError: If `depth_source` is not a recognized value.
    """

    if depth_source == DEPTH_SOURCE_GROUND_TRUTH:
        return GroundTruthDepthEstimator(
            depth_provider=simulator.get_depth, intrinsics=intrinsics
        )

    if depth_source == DEPTH_SOURCE_DEPTH_ANYTHING:
        return DepthAnythingEstimator(intrinsics=intrinsics)

    raise ValueError(
        f"Unknown depth_source {depth_source!r}; expected "
        f"{DEPTH_SOURCE_GROUND_TRUTH!r} or {DEPTH_SOURCE_DEPTH_ANYTHING!r}."
    )


@dataclass
class VisionSystem:
    """Bundle of everything a long-lived caller (the API layer) needs
    beyond `VisionAgent.perceive()` alone.

    `VisionAgent`/`PerceptionPipeline` deliberately do not expose the
    concrete `tracker` instance they were built with (`pipeline.stages`
    is documented internal state -- see `perception_pipeline.py`), so a
    caller that also wants `TemporalScene`'s OCCLUDED->REMOVED upgrade
    (which needs the *same* tracker instance's `.tracks`, see
    `temporal_scene.py`) has nowhere to get it from `agent` alone. This
    bundle is that: the one place both are held together, still without
    reaching into `PerceptionPipeline` internals to get there (the
    tracker is captured at construction time, in `build_vision_system`,
    before it's handed to `VisionAgent`).

    Attributes:
        agent: The fully-wired `VisionAgent` -- call `.perceive(prompt)`
            on this for one frame's `Scene`.
        tracker: The same `IoUTracker` instance `agent` was configured
            with. Pass to `temporal_scene.update(scene, tracker=...)`.
        temporal_scene: A fresh `TemporalScene` for this system --
            holds short-term current/previous/history state across
            repeated `agent.perceive()` calls. One `VisionSystem` should
            correspond to one logical camera/session; a new session
            should get a new `VisionSystem` (and thus a fresh
            `TemporalScene`), not reuse an old one across unrelated
            episodes.
    """

    agent: VisionAgent
    tracker: IoUTracker
    temporal_scene: TemporalScene


def build_vision_system(
    simulator: Simulator,
    depth_source: str = DEPTH_SOURCE_GROUND_TRUTH,
) -> VisionSystem:
    """Builds a fully-wired `VisionAgent` (detector, segmenter, depth,
    tracker, scene graph) plus the tracker/`TemporalScene` handles the
    API layer needs alongside it. See `VisionSystem`'s docstring for why
    those travel together.

    Args:
        simulator: The already-constructed `Simulator` this agent reads
            frames from. If `depth_source ==
            DEPTH_SOURCE_GROUND_TRUTH`, the caller must have started it
            with `Simulator(render_depth=True)` for depth to actually be
            available (a missing depth frame degrades gracefully to "no
            depth this frame" rather than raising -- see
            `base_depth_estimator.py`).
        depth_source: Which depth subsystem to use -- ground-truth
            (AI2-THOR, metric, the default) or Depth Anything (learned,
            relative -- see that module's docstring on why it's not
            interchangeable with ground truth). This function takes an
            explicit argument rather than reading the environment
            itself, so it stays a pure function of its inputs -- easy to
            call identically from a benchmark script or a test with a
            different value than whatever `VISION_DEPTH_SOURCE` happens
            to be set to in the process environment; callers that want
            the env var read it themselves and pass the result in (see
            `api/app.py`).

    Returns:
        A `VisionSystem` ready for `.agent.perceive(prompt)`.
    """

    intrinsics = CameraIntrinsics.from_ai2thor_fov(
        width=simulator.env.width, height=simulator.env.height
    )

    detector = GroundingDINODetector()
    segmenter = SAM2Segmenter()
    depth = build_depth_estimator(depth_source, simulator, intrinsics)
    tracker = IoUTracker()
    scene_graph = HeuristicSceneGraph()

    agent = VisionAgent(
        simulator,
        detector=detector,
        segmenter=segmenter,
        depth=depth,
        tracker=tracker,
        scene_graph=scene_graph,
    )

    return VisionSystem(agent=agent, tracker=tracker, temporal_scene=TemporalScene())


def build_default_vision_agent(
    simulator: Simulator,
    depth_source: str = DEPTH_SOURCE_GROUND_TRUTH,
) -> VisionAgent:
    """Convenience wrapper around `build_vision_system` for callers that
    only need the `VisionAgent` itself (e.g. a script that just wants
    `.perceive(prompt)` and has no use for tracker/temporal-scene
    handles). See `build_vision_system` for the full return value."""

    return build_vision_system(simulator, depth_source=depth_source).agent
