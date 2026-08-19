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

Scope: existence + location + open/held-state grounding
------------------------------------------------------------
A `Scene`'s `Detection`s and `Relationship`s carry far more than a
`WorldState` models (masks, bounding boxes, per-pixel geometry) --
translating all of it would be full state fusion, which is still not
this module's job. `ground_world_state()` answers four planner
questions from live perception: "has the robot seen this object"
(`ObjectState.is_located`), "what does it appear to be inside"
(`ObjectState.location`, derived from `RelationshipType.INSIDE`
edges), a depth-proxied "is it close enough to interact with"
(`ObjectState.is_near_robot`, since `Detection.depth` is the only
distance signal a single `Scene` carries), "does it currently look
open or closed" (`ObjectState.is_open`, from
`Detection.attributes["is_open"]` -- see
`vision.state.open_state_classifier`), and "what is the robot
currently holding" (`WorldState.robot_holding`, from a depth-proxied
held-object heuristic -- see `_ground_held_object()` below). Full
appearance-model-grade state fusion (reliable open/closed and
held/not-held for every object, not just a depth/phrase heuristic) is
still future work -- see `docs/roadmap.md`.

### `is_open`: vision vs. symbolic metadata -- vision wins, documented

A caller may already have a symbolic `is_open` on `state` (e.g. from
`memory_evaluation.experiment_real._seed_initial_state_from_live_metadata`,
which reads AI2-THOR's own `isOpen` field). When a detection in *this*
scene carries a real vision `is_open` signal
(`detection.attributes["is_open"]` is not `None`), that signal
**overwrites** whatever `state` already had for that object -- the
same "current perception is stronger evidence than a stale prior
belief" rule this module already applies to `is_located`/`location`
(see "Why detections update in place" below). A detection with
`attributes["is_open"] is None` (classifier ran but was not confident,
or never ran at all) leaves `is_open` exactly as `state` already had
it -- absence of a confident vision signal is never treated as
evidence of anything, and never overwrites a known symbolic value with
"unknown."

### `robot_holding`: positive vision evidence only, never clears

`_ground_held_object()` sets `WorldState.robot_holding` only when this
scene's detections give *positive* evidence of a held object (see that
function's docstring for the heuristic). If no detection looks held
this frame, `robot_holding` is left exactly as it already was --
mirroring `is_located`'s "unseen this frame is not evidence of
absence" rule. This is deliberate: the one gap this heuristic was
built to help investigate (`docs/roadmap.md`'s `tier4_multi_step`
`WorldState`-reseeding entry) is a case where the *correct* answer is
"still holding something," so a heuristic that could clear
`robot_holding` to `None` on a merely-inconclusive frame would risk
making that exact failure mode worse, not better.

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

#: Depth threshold (meters) below which a detection is treated as
#: "possibly held" rather than merely "near" -- notably closer than
#: `NEAR_ROBOT_DEPTH_METERS`. AI2-THOR renders a held object right in
#: front of the agent's camera, much closer than anything merely
#: approached-but-not-picked-up; this is a real, metric depth signal
#: (`Detection.depth`, the same field `is_near_robot` already uses),
#: but still a heuristic proxy for "held," not a grasp-truth signal --
#: see `_ground_held_object()`'s docstring for what could fool it.
HELD_OBJECT_MAX_DEPTH_M = 0.5


def ground_world_state(
    scene: Scene,
    state: Optional[WorldState] = None,
    *,
    near_robot_depth_m: float = NEAR_ROBOT_DEPTH_METERS,
    held_object_max_depth_m: float = HELD_OBJECT_MAX_DEPTH_M,
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
        held_object_max_depth_m: Depth threshold (meters) below which
            a detection is considered a held-object candidate. See
            `HELD_OBJECT_MAX_DEPTH_M` and `_ground_held_object()`.

    Returns:
        `state`, mutated: every detected object's `is_located` is set
        `True` (and `is_near_robot` when close enough), any
        `RelationshipType.INSIDE` edge sets the contained object's
        `location` to its container's label, any confident
        `detection.attributes["is_open"]` overwrites that object's
        `is_open`, and `state.robot_holding` is set when this scene
        gives positive evidence of a held object (see module
        docstring for the reconciliation/never-clears policies).
    """
    state = state if state is not None else WorldState.initial()

    for detection in scene.detections:
        obj = state.object(detection.label)
        obj.is_located = True
        if detection.depth is not None and detection.depth <= near_robot_depth_m:
            obj.is_near_robot = True

        vision_is_open = detection.attributes.get("is_open")
        if vision_is_open is not None:
            obj.is_open = vision_is_open

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

    _ground_held_object(scene, state, held_object_max_depth_m)

    return state


def _ground_held_object(scene: Scene, state: WorldState, max_depth_m: float) -> None:
    """Sets `state.robot_holding` from a depth-proxied held-object
    heuristic, if this scene gives positive evidence of one.

    Heuristic: among this scene's detections with a known depth at or
    below `max_depth_m`, the closest one is treated as held. Only ever
    *sets* `state.robot_holding` (see module docstring's "positive
    evidence only, never clears" policy) -- never clears it to `None`
    when no candidate is found this frame.

    What could fool this heuristic (read before trusting it blindly)
    ------------------------------------------------------------------
    This is a depth-only proxy, not a real grasp/appearance signal
    (nothing in a `Scene` observes whether an object is physically
    attached to the robot's gripper -- see module docstring's scope
    note): a detection this close could also be the camera very near a
    countertop/wall, or an object the agent is standing directly next
    to but not holding. It has not been measured against real
    held/not-held ground truth yet (see `docs/roadmap.md`) -- treat a
    `True` result as a real, useful signal for the specific gap it was
    built to investigate (`tier4_multi_step`'s `WorldState`-reseeding
    entry), not a certified grasp detector.
    """
    candidates = [
        (d.depth, d)
        for d in scene.detections
        if d.depth is not None and d.depth <= max_depth_m
    ]
    if not candidates:
        return
    _, closest = min(candidates, key=lambda pair: pair[0])
    state.robot_holding = closest.label.strip().lower()
