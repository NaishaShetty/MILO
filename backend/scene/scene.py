"""
scene.py

Purpose
-------
Represents everything the robot currently perceives at one moment in
time -- not just the detected objects, but the frame they came from,
when they were captured, and (eventually) the robot's pose and any
inferred relationships between objects.

Responsibilities
-----------------
- Hold one frame's worth of perception output as a single object that
  the planner, memory system, and navigation can all consume, instead
  of each module receiving a different ad-hoc bundle of arrays.
- Stay a plain, lightweight data container. `Scene` does not run
  inference, compute relationships, or touch the simulator -- it is
  filled in by callers (detectors, future segmenters/depth/tracking
  modules, the vision agent) and only stores what it's given.

Why this abstraction exists
-----------------------------
Every perception module should output a `Scene` object rather than
returning its own raw structure (a list of boxes here, a depth map
there). A single shared shape is what lets the planner reason over
"what does the robot currently perceive" without knowing which models
produced which piece of it.

Field design
------------
`detections` is the only field with a strong default of an empty list
(a scene reasonably has zero detections but still needs the list to
exist for `add_detection`/`labels` to work). `relationships` also
defaults to an empty list for the same reason, now that a scene-graph
stage (`vision/scene_graph/`) populates it with `Relationship`
objects. Every other field is `Optional` and defaults to `None`/an
empty container, because most producers of a `Scene` today
(`GroundingDINODetector`) only populate `detections` -- `rgb_image`,
`depth_image`, and `robot_state` remain placeholders for perception
modules that don't exist yet (depth estimation and simulator pose
tracking respectively). Adding a real implementation for any of those
later is filling in an existing field, not a breaking schema change.

`robot_state` is typed `Any` rather than a dedicated `RobotState`
dataclass because that type does not exist yet -- per this refactor's
scope, only a placeholder is prepared here, not the robot state model
itself.

Who is allowed to depend on this file
-----------------------------------------
As of the Phase 2 API freeze (see
`docs/architecture/api_contracts.md`), `Scene` (its field schema and
its `add_detection`/`labels`/`__len__` methods) is a frozen public
interface. Every perception stage reads and writes it; every future
module -- Language, Planner, Memory, Execution, Frontend -- is
expected to consume perception results as a `Scene` obtained from
`VisionAgent.perceive()`, not as some other shape.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from scene.detection import Detection
from scene.relationship import Relationship


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
@dataclass
class Scene:
    """Complete representation of the robot's current view.

    The single data structure every perception stage enriches and
    every downstream consumer reads. See the module docstring for the
    rationale behind each field's type and default.

    Attributes:
        detections: Objects detected in this frame. Populated by a
            detector; enriched in place by later stages (segmenter,
            scene graph, ...).
        timestamp: Optional capture time for this frame.
        frame_id: Optional frame index/identifier.
        robot_state: Placeholder for the robot's pose at capture time.
            Not yet populated by any stage.
        rgb_image: Optional reference to the source RGB frame.
        depth_image: Placeholder for a future depth map. Not yet
            populated by any stage.
        relationships: Inferred relationships between `detections`,
            populated by a `BaseSceneGraph` stage (e.g.
            `HeuristicSceneGraph`).
        metadata: Open-ended context bag (e.g. the detection prompt).
            Well-known keys are centralized in
            `scene.metadata_keys.SceneMetadata`.
    """

    detections: List[Detection] = field(default_factory=list)

    timestamp: Optional[float] = None
    frame_id: Optional[int] = None

    robot_state: Optional[Any] = None

    rgb_image: Optional[Any] = None
    depth_image: Optional[Any] = None

    relationships: List[Relationship] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_detection(self, detection: Detection):
        """Appends a detection to this scene.

        Args:
            detection: The `Detection` to add.
        """

        self.detections.append(detection)

    def __len__(self):
        """Returns the number of detections in this scene.

        Returns:
            The length of `self.detections`.
        """

        return len(self.detections)

    def labels(self):
        """Returns every detection's label, in detection order.

        Returns:
            A list of `str` labels, one per entry in
            `self.detections`.
        """

        return [d.label for d in self.detections]
