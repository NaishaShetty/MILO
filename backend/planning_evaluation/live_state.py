"""
live_state.py (backend/planning_evaluation)

Purpose
-------
`GOAL_CHECKS` (`planner.validator`) only ever runs against the
planner's own simulated `WorldState` -- it verifies the plan *would*
satisfy the goal if every step ran with no error, never that it
actually did in the real scene (`orchestration.task_runner.
TaskRunResult.succeeded`/`execution.models.ExecutionRecord.status`
only report "did every dispatched step complete without a simulator
error"). This module closes that gap for the benchmark specifically:
`check_goal_live()` re-implements each `GOAL_CHECKS` predicate against
a live `Simulator.get_metadata()` snapshot taken AFTER execution,
using AI2-THOR's own ground-truth object fields (`isPickedUp`,
`parentReceptacles`, `isOpen`) instead of the planner's replayed
symbolic state.

Why this lives here, not in `planner.validator`
--------------------------------------------------
`validator.GOAL_CHECKS`'s contract is deliberately "predicate over a
`WorldState`," used at plan-validation time before anything executes
-- there is no live AI2-THOR metadata available yet at that point.
Re-purposing the same functions to also accept live metadata would
blur two different questions ("would this plan work" vs "did it
actually work") into one dict of callables; this benchmark-only
module keeps them separate while mirroring the exact same goal
semantics, object-for-object, so a result here is directly comparable
to what `validator.py` predicted before execution.

Known simplification: `tier1_locate` (`find`/`locate`/...)
------------------------------------------------------------
There is no physical "has been located" fact to check against live
metadata the way `is_held`/`location`/`is_open` have real analogues
(`isPickedUp`/`parentReceptacles`/`isOpen`) -- "locating" is a
perception event, and `Vision`'s `ground_world_state()` (Phase C) is
not wired into this evaluator (future work -- see `dataset/v1.0/
README.md`'s "Known limitations"). This module's live check for
`tier1_locate` therefore answers a narrower, honest question instead:
does an object of the named type exist anywhere in the live scene?
Every task in `dataset/v1.0/` was authored from a live metadata scan
(see `tasks.json`'s `generated_by` field), so this should always pass
in practice -- it exists to catch a regression, not to measure
locating accuracy.

Addendum -- `check_goal_live_grounded()` (perception-grounded tier1)
----------------------------------------------------------------------
The simplification above is now partially addressed, not removed: this
module keeps `check_goal_live()`'s `tier1_locate` predicate exactly as
described above (existence-only, byte-identical behavior), because it
is still a real, independent signal ("did the task even name a real
object" -- a regression guard, not a perception measurement) and
deleting it would silently merge two different questions into one
number, which is exactly what this project's "two independent success
signals" convention (see this module's earlier docstring, and
`run_benchmark.py`'s "Two independent success signals per episode")
exists to avoid.

`check_goal_live_grounded()` adds a second, stricter signal alongside
it for the `tier1_locate` goal group only: `perceived_by_agent`, backed
by Phase C's `planner.grounding.ground_world_state()` -- run for real
against a `Scene` from `agents.vision_agent.VisionAgentWrapper.
perceive()` (reading the same live RGB frame the running `Simulator`
already provides) -- checking `WorldState.object(task.object).
is_located` after grounding. This is the first time `ground_world_state()`
has been invoked post-hoc (previously only ever called pre-planning,
from `orchestration.orchestrator.Orchestrator._observe()`); it is a
pure, stateless function, so calling it here after execution is safe
and does not affect planning.

Both booleans are returned side by side
(`GroundedTier1Result.exists_in_scene`/`.perceived_by_agent`) -- never
merged into one. `run_benchmark.py` decides, and documents, what
`goal_success` means for `tier1_locate` tasks going forward; this
module does not make that call, it only supplies both raw signals. See
`dataset/v1.0/README.md`'s "Known limitations" section for the real
numbers from the first run this was exercised against, and whether
`perceived_by_agent` ever actually diverged from `exists_in_scene` in
practice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from execution.resolver import ObjectResolver
from schemas.task import SingleTask

_resolver = ObjectResolver()

#: The exact goal vocabulary `check_goal_live()` treats as
#: "tier1_locate" -- shared with `check_goal_live_grounded()` so the
#: two functions can never silently drift on which goals this applies
#: to.
TIER1_LOCATE_GOALS = ("find", "search_for", "locate", "inspect", "count")


@dataclass
class GroundedTier1Result:
    """
    Two independent `tier1_locate` success signals for one episode,
    kept separate on purpose -- see this module's docstring addendum.
    Both are `None` when the episode's goal is not in
    `TIER1_LOCATE_GOALS` (nothing to check).
    """

    #: `check_goal_live()`'s existing existence-only check, unchanged.
    exists_in_scene: Optional[bool]

    #: `ground_world_state()`-backed perception check: did the agent's
    #: vision actually register a detection for this object. `None`
    #: when no vision perception attempt was made or possible for this
    #: episode (e.g. vision stack unavailable) -- distinct from
    #: `False` ("vision ran and did not detect it"), so a caller can
    #: tell "unmeasured" from "measured, and failed" apart.
    perceived_by_agent: Optional[bool]

    #: Set when `perceived_by_agent` could not be measured for a real
    #: reason (e.g. vision stack construction failed, perceive()
    #: raised) -- kept for honest reporting rather than silently
    #: leaving `perceived_by_agent=None` unexplained.
    perception_error: Optional[str] = None


def _by_object_id(metadata: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        obj["objectId"]: obj
        for obj in (metadata.get("objects") or [])
        if isinstance(obj.get("objectId"), str)
    }


def _resolve(name: Optional[str], metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    object_id = _resolver.resolve(name, metadata)
    if object_id is None:
        return None
    return _by_object_id(metadata).get(object_id)


def check_goal_live(task: SingleTask, metadata: Dict[str, Any]) -> Optional[bool]:
    """
    Live-metadata analogue of `planner.validator.GOAL_CHECKS`. Returns
    `None` (unverifiable) for a goal this module has no live check
    for, matching `GOAL_CHECKS`'s own "open, not closed, goal
    vocabulary" convention.
    """
    goal = (task.goal or "").strip().lower()

    if goal in ("pick_up", "fetch", "deliver"):
        obj = _resolve(task.object, metadata)
        if obj is None:
            return False
        return bool(obj.get("isPickedUp"))

    if goal in ("store", "put_away", "pick_and_place", "place"):
        obj = _resolve(task.object, metadata)
        target = _resolve(task.target, metadata)
        if obj is None or target is None:
            return False
        parents = obj.get("parentReceptacles") or []
        return (not obj.get("isPickedUp")) and target.get("objectId") in parents

    if goal == "open":
        ref = _resolve(task.object or task.target, metadata)
        return bool(ref.get("isOpen")) if ref is not None else False

    if goal == "close":
        ref = _resolve(task.object or task.target, metadata)
        return (ref.get("isOpen") is False) if ref is not None else False

    if goal in TIER1_LOCATE_GOALS:
        ref = _resolve(task.object or task.target, metadata)
        return ref is not None

    return None


@dataclass
class MultiGoalResult:
    """
    `check_goal_live()` applied to every sub-goal of a
    `tier4_multi_step` task (see `loader.BenchmarkTask.to_single_tasks()`),
    kept per-subtask so a caller can report exactly which sub-goal(s)
    failed rather than only a collapsed boolean -- the same
    "never hide which part failed" discipline `check_goal_live_grounded()`
    already applies to `tier1_locate`.
    """

    #: `check_goal_live()`'s result for each subtask, in order. A `None`
    #: entry (goal this module has no live check for) counts as failed
    #: in `all_succeeded`, matching how `run_benchmark.py` treats an
    #: unverifiable single-task goal as not a success.
    per_subtask: List[Optional[bool]]

    @property
    def all_succeeded(self) -> bool:
        return len(self.per_subtask) > 0 and all(bool(r) for r in self.per_subtask)


def check_goal_live_multi(
    tasks: List[SingleTask], metadata: Dict[str, Any]
) -> MultiGoalResult:
    """
    `check_goal_live()` for each of `tasks` (a `tier4_multi_step`
    task's independent sub-goals, all evaluated against the *same*
    post-execution `metadata` snapshot -- taken once, after both
    sub-goals have been planned and executed in sequence). A
    `tier4_multi_step` episode's `goal_success` is
    `MultiGoalResult.all_succeeded`: every sub-goal must independently
    hold live, not just the last one attempted.
    """
    return MultiGoalResult(
        per_subtask=[check_goal_live(task, metadata) for task in tasks]
    )


def check_goal_live_grounded(
    task: SingleTask,
    metadata: Dict[str, Any],
    *,
    vision_agent: Optional[Any] = None,
) -> GroundedTier1Result:
    """
    `tier1_locate`-only dual check: `exists_in_scene` (identical to
    `check_goal_live()` for this goal group) alongside
    `perceived_by_agent` (real vision perception, via
    `ground_world_state()`). See this module's docstring addendum.

    Returns a `GroundedTier1Result` with both fields `None` when
    `task.goal` is not in `TIER1_LOCATE_GOALS` -- this function is a
    no-op for every other goal group; callers should keep using
    `check_goal_live()` for those.

    `vision_agent`, when given, must be an
    `agents.vision_agent.VisionAgentWrapper` (typed `Any` here to keep
    this module free of a hard dependency on the vision package --
    `run_benchmark.py` is the only caller that constructs a real one).
    Passing `None` (e.g. vision stack unavailable, or the goal is not
    tier1_locate) skips the perception check and leaves
    `perceived_by_agent=None`, `exists_in_scene` still computed.
    """
    goal = (task.goal or "").strip().lower()
    if goal not in TIER1_LOCATE_GOALS:
        return GroundedTier1Result(exists_in_scene=None, perceived_by_agent=None)

    exists_in_scene = check_goal_live(task, metadata)

    if vision_agent is None:
        return GroundedTier1Result(
            exists_in_scene=exists_in_scene, perceived_by_agent=None
        )

    object_name = task.object or task.target
    if not object_name:
        return GroundedTier1Result(
            exists_in_scene=exists_in_scene,
            perceived_by_agent=None,
            perception_error="task has no object/target name to look for",
        )

    # Local imports: keeps `ground_world_state`/`Scene` (and their own
    # transitive vision-package imports) out of every caller that
    # never exercises this function -- `check_goal_live()` above stays
    # importable with zero vision dependency, matching this module's
    # existing "benchmark-only, minimal dependency footprint" design.
    from planner.grounding import ground_world_state

    try:
        scene = vision_agent.perceive(f"{object_name}.")
        world_state = ground_world_state(scene)
        perceived = bool(world_state.object(object_name).is_located)
        return GroundedTier1Result(
            exists_in_scene=exists_in_scene, perceived_by_agent=perceived
        )
    except Exception as exc:  # noqa: BLE001 -- report, never crash the benchmark
        return GroundedTier1Result(
            exists_in_scene=exists_in_scene,
            perceived_by_agent=None,
            perception_error=f"{type(exc).__name__}: {exc}",
        )
