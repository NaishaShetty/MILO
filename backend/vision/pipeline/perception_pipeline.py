"""
perception_pipeline.py

Purpose
-------
Owns the sequencing of perception stages that together turn one RGB
frame into a fully enriched `Scene`.

Pipeline

VisionAgent

      |

      v

PerceptionPipeline

      |

      +-- Detector

      +-- Segmenter

      +-- Depth

      +-- Tracker

      +-- SceneGraph

      v

Scene

Responsibilities
-----------------
- Hold an ordered list of perception stages (detector, segmenter,
  depth, tracker, scene graph, ...), each optional.
- Run every configured stage against the same `(image, scene)` pair,
  in a fixed order, each stage enriching the `Scene` the previous one
  produced.
- Nothing else. `PerceptionPipeline` does not acquire images (that is
  `VisionAgent`'s job), does not know how any stage is implemented
  (Grounding DINO vs. a future detector, SAM2 vs. a future segmenter),
  and does not render or persist anything.

Why this abstraction exists
-----------------------------
Before this pipeline existed, `VisionAgent.perceive()` hardcoded the
stage sequence directly:

    scene = self.detector.process(image, scene)
    if self.segmenter is not None:
        scene = self.segmenter.process(image, scene)

That was fine for two stages, but every future stage (depth
estimation, tracking, scene-graph generation) would mean editing
`VisionAgent` again, growing a method that is meant to answer "how do
I get an image" into one that also answers "what order do 5+ models
run in and which ones are configured." Those are two different
concerns with two different rates of change: image acquisition is
stable, the perception stage list grows with every new capability this
project adds.

`PerceptionPipeline` isolates that second concern. `VisionAgent` now
only needs to know "I hand a pipeline an (image, scene) and get a
Scene back" -- adding depth/tracking/scene-graph later means
constructing `PerceptionPipeline` with one more keyword argument, not
touching `VisionAgent` or any existing stage.

Why stages keep the `process(image, scene)` contract
---------------------------------------------------------
Every stage -- `BaseDetector`, `BaseSegmenter`, and (by convention,
see `base_detector.py`'s location note) future `BaseDepthEstimator`,
`BaseTracker`, `BaseSceneGraphBuilder` -- implements
`process(image, scene) -> Scene`. That uniform shape is what lets
`PerceptionPipeline` treat every stage identically: iterate the
configured stages in order and call `stage.process(image, scene)` on
each, without a special case per stage type. Adding a new stage to the
pipeline never requires new orchestration logic here, only a new
constructor argument.

Why the planner never sees this
-----------------------------------
The planner (and every other downstream consumer) depends on `Scene`,
not on `PerceptionPipeline` or any individual stage. Perception can be
re-ordered, a stage swapped for a different model, or a new stage
inserted, and nothing outside `vision/` has to change.

Who is allowed to depend on this file
-----------------------------------------
As of the Phase 2 API freeze (see
`docs/architecture/api_contracts.md`), `PerceptionPipeline.process()`
is a frozen public interface -- primarily for `VisionAgent`, which
constructs and calls it, and for tests/tooling that need to exercise a
specific stage combination without a full `VisionAgent`. Language,
Planner, Memory, Execution, and Frontend modules should go through
`VisionAgent.perceive()` rather than constructing a
`PerceptionPipeline` directly; `self.stages` is internal state and
must never be read or mutated from outside this class.
"""


class PerceptionPipeline:
    """Runs a configured sequence of perception stages.

    Holds an ordered, optional list of perception stages (detector,
    segmenter, depth, tracker, scene graph) and runs each configured
    stage's `process(image, scene)` in order against the same
    `(image, scene)` pair, passing the `Scene` returned by one stage
    into the next.

    Attributes:
        stages: Internal ordered list of configured stages (`None` for
            any stage not supplied). Implementation detail -- not part
            of the public API; do not read or mutate from outside this
            class.
    """

    # ----------------------------------------------------------------
    # Constructor
    # ----------------------------------------------------------------

    def __init__(
        self,
        detector=None,
        segmenter=None,
        depth=None,
        tracker=None,
        scene_graph=None,
    ):
        """Configures the pipeline's stage sequence.

        Args:
            detector: Optional `BaseDetector` implementation, run
                first.
            segmenter: Optional `BaseSegmenter` implementation, run
                after the detector.
            depth: Optional depth-estimation stage (reserved; no
                implementation exists yet).
            tracker: Optional tracking stage (reserved; no
                implementation exists yet).
            scene_graph: Optional `BaseSceneGraph` implementation, run
                last.
        """

        # Order matters: each stage consumes what the previous ones
        # already added to the Scene (a segmenter needs the detector's
        # boxes, a tracker needs identities to link across frames,
        # scene-graph generation needs the fully perceived objects).
        # `None` entries are stages not yet configured/implemented and
        # are skipped in `process`, so `PerceptionPipeline(detector=...)`
        # alone remains valid, exactly as `VisionAgent` did before this
        # existed.
        self.stages = [
            detector,
            segmenter,
            depth,
            tracker,
            scene_graph,
        ]

    # --------------------------------------------------------------------
    # Public API (Frozen after Phase 2)
    #
    # Language
    # Planner
    # Memory
    # Execution
    # Frontend
    #
    # depend on this interface (indirectly, via VisionAgent.perceive()).
    #
    # Avoid breaking changes unless absolutely necessary.
    # --------------------------------------------------------------------

    def process(self, image, scene):
        """Runs every configured stage, in order, against one frame.

        Args:
            image: RGB `numpy.ndarray` for the current frame.
            scene: The `Scene` being built for this frame.

        Returns:
            The same `Scene`, enriched by every configured stage.
            Stages configured as `None` are skipped.
        """

        for stage in self.stages:

            if stage is not None:

                scene = stage.process(image, scene)

        return scene
