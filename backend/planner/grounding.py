"""
grounding.py (backend/planner)

Purpose
-------
Translates a vision `Scene` (this project's SpatialScene) into the
planner's symbolic `WorldState`, so plans are validated and reasoned
about against what the robot actually currently perceives instead of
only an empty `WorldState.initial()` or a live AI2-THOR metadata scan
by object name (`execution.resolver.ObjectResolver`,
`orchestration.task_runner.TaskRunner._form_observation`) -- see
`docs/roadmap.md`'s "Vision-grounded WorldState" future-work entry and
`docs/architecture/spatial_perception.md`'s "Planner boundary" note,
which this module closes. `orchestration.orchestrator.Orchestrator`
calls this before planning (see its `_observe()`); it is the seam
`task_runner.py`'s `initial_state` docstring names as future work.

Scope: existence + location grounding only
--------------------------------------------
A `Scene`'s `Detection`s and `Relationship`s carry far more than a
`WorldState` models (masks, bounding boxes, per-pixel geometry) --
translating all of it would be full state fusion, which is not this
module's job yet. `ground_world_state()` answers exactly two planner
questions from live perception: "has the robot seen this object"
(`ObjectState.is_located`) and "what does it appear to be inside"
(`ObjectState.location`, derived from `RelationshipType.INSIDE`
edges) -- plus a depth-proxied "is it close enough to interact with"
(`ObjectState.is_near_robot`), since `Detection.depth` is the only
distance signal a single `Scene` carries. `is_held`/`is_open` stay
untouched: nothing in a `Scene` observes whether an object is
currently grasped, and open/closed state needs an appearance model
this project does not have yet -- adding either here would be
speculative, not vision-grounded.

Why detections update in place, not replace
-------------------------------------------
`ground_world_state()` takes an existing `WorldState` (default: a
fresh one) and folds detections into it rather than requiring a caller
to discard prior state -- exactly like `rule_based.py`'s existing
"current perception overrides stale memory" rule
(`_apply_memory_hint`'s `is_located` check): an object this scene
doesn't currently see is left exactly as memory/a previous scene left
it, not marked "not located". Objects this scene DOES see always win,
since a live detection is stronger evidence than a memory hint or a
stale prior scene.

What this does not replace
---------------------------
`execution.resolver.ObjectResolver` still does a live AI2-THOR
metadata scan, and still should: dispatching an action to AI2-THOR
needs a concrete simulator `objectId` string, which `Scene`/`Detection`
never carries (vision has no notion of the simulator's own object
identifiers). That is a different problem -- "which simulator object
does this plan step act on" -- from the one this module solves --
"what does the planner believe about the world before it plans" --
and the roadmap's "metadata scan by name" complaint was about the
latter being used as a `WorldState` substitute, not about the
former's continued existence.
"""

from __future__ import annotations

from typing import Optional

from planner.state import WorldState
from scene.relationship import RelationshipType
from scene.scene import Scene

#: Detections within this many meters of the camera are treated as
#: close enough to interact with. A coarse stand-in for "the robot has
#: navigated next to this object" (`actions._effect_navigate`) until a
#: real robot pose / reachability model exists -- see this module's
#: docstring on scope.
NEAR_ROBOT_DEPTH_METERS = 1.5


def ground_world_state(
    scene: Scene,
    state: Optional[WorldState] = None,
    *,
    near_robot_depth_m: float = NEAR_ROBOT_DEPTH_METERS,
) -> WorldState:
    """Folds `scene`'s detections/relationships into a `WorldState`.

    Args:
        scene: A vision `Scene` from `VisionAgent.perceive()` (or a
            `TemporalScene.current`) -- this project's SpatialScene.
        state: The `WorldState` to update in place and return. Defaults
            to a fresh `WorldState.initial()` when omitted -- pass an
            existing state (e.g. one already mutated by memory or a
            prior scene) to layer this scene's perception on top of it
            rather than starting over.
        near_robot_depth_m: Depth threshold (meters) below which a
            detection is considered `is_near_robot`. See
            `NEAR_ROBOT_DEPTH_METERS`.

    Returns:
        `state`, mutated: every detected object's `is_located` is set
        `True` (and `is_near_robot` when close enough), and any
        `RelationshipType.INSIDE` edge sets the contained object's
        `location` to its container's label.
    """
    state = state if state is not None else WorldState.initial()

    for detection in scene.detections:
        obj = state.object(detection.label)
        obj.is_located = True
        if detection.depth is not None and detection.depth <= near_robot_depth_m:
            obj.is_near_robot = True

    num_detections = len(scene.detections)
    for rel in scene.relationships:
        if rel.predicate != RelationshipType.INSIDE:
            continue
        if not (0 <= rel.subject_id < num_detections):
            continue
        if not (0 <= rel.object_id < num_detections):
            continue
        contained = scene.detections[rel.subject_id]
        container = scene.detections[rel.object_id]
        state.object(contained.label).location = container.label

    return state
