"""
htn.py (backend/planner)

Purpose
-------
Implements `HTNPlanner`, a real Hierarchical Task Network planning
strategy over the same primitive vocabulary
(`actions.LOCATE/NAVIGATE/PICKUP/PLACE/OPEN/CLOSE`) and `WorldState`
every other strategy in this package already uses. See
`docs/architecture/planning.md`'s "HTN planner" section for the full
design writeup (task types, method library, worked `DepositObject`
example) -- this module is the implementation of that design, kept in
sync with it.

Scope (slice 1) -- read before extending
-------------------------------------------
Covers exactly the `tier1_locate`/`tier2_pickup`/`tier3_store` goal
shapes (`find`/`search_for`/`locate`/`inspect`/`count`, `pick_up`,
`store`/`put_away`), plus `place`/`pick_and_place`/`open`/`close` for
free (same decomposition machinery). Deliberately does NOT cover
`fetch`/`deliver`/`navigate_to`/`follow`/`return_to`/the generic-goal
fallback, or memory-conditioned search hints (Phase 6.3) -- see the
design doc's "explicitly out of scope" notes. An unrecognized goal
raises `UnsupportedGoalError`, the same as `RuleBasedPlanner` would.

Why a real task network, not `RuleBasedPlanner` wrapped in a new shape
--------------------------------------------------------------------------
`BehaviorTreePlanner` (see that module's own docstring) deliberately
reuses `rule_based.GOAL_HANDLERS` directly -- a different
*representation* of the same imperative logic. This module does not:
`_decompose()` below is a genuine recursive task-network expansion
(compound task -> method selection -> subtasks, recursively, until
only primitives remain), independent of `rule_based.py`'s control
flow, even though it is expected to produce equivalent plans for the
shared domain this slice covers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from planner.actions import CLOSE, LOCATE, NAVIGATE, OPEN, PICKUP, PLACE
from planner.exceptions import InvalidTaskError, UnsupportedGoalError
from planner.models import PlanStep
from planner.planner import Planner
from planner.state import WorldState
from schemas.task import SingleTask

if TYPE_CHECKING:  # pragma: no cover
    from memory.agent import PlannerMemoryContext


# ---------------------------------------------------------------------
# Task types
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class PrimitiveTask:
    """One directly-executable action -- maps 1:1 onto an
    `actions.ACTION_REGISTRY` entry. Never invents a new primitive."""

    action: str
    target: Optional[str]
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompoundTask:
    """A task that still needs decomposing via `METHOD_LIBRARY[name]`."""

    name: str
    args: Dict[str, Any] = field(default_factory=dict)


Task = Union[PrimitiveTask, CompoundTask]

MethodPrecondition = Callable[[WorldState, Dict[str, Any]], bool]
MethodDecompose = Callable[[Dict[str, Any]], List[Task]]


@dataclass(frozen=True)
class Method:
    """One candidate decomposition for a compound task. `precondition`
    is checked against the live `WorldState` + the task's `args` --
    real HTN method applicability, not a plan-time simulation. The
    engine commits to the first method (in `METHOD_LIBRARY[name]`
    order) whose precondition holds."""

    name: str
    precondition: MethodPrecondition
    decompose: MethodDecompose


def _always(_state: WorldState, _args: Dict[str, Any]) -> bool:
    return True


# ---------------------------------------------------------------------
# Method library -- see docs/architecture/planning.md for the full
# table and the DepositObject worked example this mirrors from
# rule_based._deposit()'s state-aware needs_open branching.
# ---------------------------------------------------------------------


def _locate_object_method(args: Dict[str, Any]) -> List[Task]:
    obj = args["obj"]
    return [PrimitiveTask(LOCATE, obj), PrimitiveTask(NAVIGATE, obj)]


def _acquire_object_method(args: Dict[str, Any]) -> List[Task]:
    obj = args["obj"]
    return [
        CompoundTask("LocateObject", {"obj": obj}),
        PrimitiveTask(PICKUP, obj),
    ]


def _deposit_not_openable_or_already_open_precondition(
    state: WorldState, args: Dict[str, Any]
) -> bool:
    target_state = state.object(args["target"])
    return target_state.is_openable is False or target_state.is_open is True


def _deposit_not_openable_or_already_open_method(args: Dict[str, Any]) -> List[Task]:
    obj, target = args["obj"], args["target"]
    return [
        CompoundTask("LocateObject", {"obj": target}),
        PrimitiveTask(PLACE, obj, {"container": target}),
    ]


def _deposit_needs_open_precondition(state: WorldState, args: Dict[str, Any]) -> bool:
    target_state = state.object(args["target"])
    return bool(args.get("use_container")) or target_state.is_open is False


def _deposit_needs_open_method(args: Dict[str, Any]) -> List[Task]:
    obj, target = args["obj"], args["target"]
    return [
        CompoundTask("LocateObject", {"obj": target}),
        PrimitiveTask(OPEN, target),
        PrimitiveTask(PLACE, obj, {"container": target}),
        PrimitiveTask(CLOSE, target),
    ]


def _deposit_default_method(args: Dict[str, Any]) -> List[Task]:
    obj, target = args["obj"], args["target"]
    return [
        CompoundTask("LocateObject", {"obj": target}),
        PrimitiveTask(PLACE, obj, {"container": target}),
    ]


def _store_object_method(args: Dict[str, Any]) -> List[Task]:
    obj, target = args["obj"], args["target"]
    return [
        CompoundTask("AcquireObject", {"obj": obj}),
        CompoundTask(
            "DepositObject", {"obj": obj, "target": target, "use_container": True}
        ),
    ]


def _place_object_method(args: Dict[str, Any]) -> List[Task]:
    obj, target = args["obj"], args["target"]
    return [
        CompoundTask("AcquireObject", {"obj": obj}),
        CompoundTask(
            "DepositObject", {"obj": obj, "target": target, "use_container": False}
        ),
    ]


def _open_object_method(args: Dict[str, Any]) -> List[Task]:
    obj = args["obj"]
    return [CompoundTask("LocateObject", {"obj": obj}), PrimitiveTask(OPEN, obj)]


def _close_object_method(args: Dict[str, Any]) -> List[Task]:
    obj = args["obj"]
    return [CompoundTask("LocateObject", {"obj": obj}), PrimitiveTask(CLOSE, obj)]


METHOD_LIBRARY: Dict[str, List[Method]] = {
    "LocateObject": [Method("locate_object", _always, _locate_object_method)],
    "AcquireObject": [Method("acquire_object", _always, _acquire_object_method)],
    "DepositObject": [
        Method(
            "deposit_not_openable_or_already_open",
            _deposit_not_openable_or_already_open_precondition,
            _deposit_not_openable_or_already_open_method,
        ),
        Method(
            "deposit_needs_open",
            _deposit_needs_open_precondition,
            _deposit_needs_open_method,
        ),
        Method("deposit_default", _always, _deposit_default_method),
    ],
    "StoreObject": [Method("store_object", _always, _store_object_method)],
    "PlaceObject": [Method("place_object", _always, _place_object_method)],
    "OpenObject": [Method("open_object", _always, _open_object_method)],
    "CloseObject": [Method("close_object", _always, _close_object_method)],
}


# ---------------------------------------------------------------------
# Top-level goal -> compound task mapping (the HTN analogue of
# rule_based.GOAL_HANDLERS, scoped to this slice's coverage).
# ---------------------------------------------------------------------


def _require(value: Optional[str], goal: str, field_name: str) -> str:
    if not value:
        raise InvalidTaskError(
            f"Goal '{goal}' requires a '{field_name}' but none was given."
        )
    return value


def _primary_reference(task: SingleTask) -> Optional[str]:
    """Matches `rule_based._primary_reference()`'s fallback chain --
    kept as its own copy (not imported) for the same reason
    `_StepBuilder` is: this module's decomposition engine owns its own
    goal-to-task mapping independently of `rule_based.py`."""
    return task.object or task.target or task.target_location or task.source_location


def _root_locate(task: SingleTask) -> Task:
    obj = _require(_primary_reference(task), task.goal or "find", "object or target")
    return CompoundTask("LocateObject", {"obj": obj})


def _root_pick_up(task: SingleTask) -> Task:
    obj = _require(task.object, task.goal or "pick_up", "object")
    return CompoundTask("AcquireObject", {"obj": obj})


def _root_store(task: SingleTask) -> Task:
    obj = _require(task.object, task.goal or "store", "object")
    target = _require(
        task.target or task.target_location, task.goal or "store", "target"
    )
    return CompoundTask("StoreObject", {"obj": obj, "target": target})


def _root_place(task: SingleTask) -> Task:
    obj = _require(task.object, task.goal or "place", "object")
    target = _require(
        task.target or task.target_location, task.goal or "place", "target"
    )
    return CompoundTask("PlaceObject", {"obj": obj, "target": target})


def _root_open(task: SingleTask) -> Task:
    obj = _require(_primary_reference(task), task.goal or "open", "object or target")
    return CompoundTask("OpenObject", {"obj": obj})


def _root_close(task: SingleTask) -> Task:
    obj = _require(_primary_reference(task), task.goal or "close", "object or target")
    return CompoundTask("CloseObject", {"obj": obj})


HTN_GOAL_TASKS: Dict[str, Callable[[SingleTask], Task]] = {
    "find": _root_locate,
    "search_for": _root_locate,
    "locate": _root_locate,
    "inspect": _root_locate,
    "count": _root_locate,
    "pick_up": _root_pick_up,
    "store": _root_store,
    "put_away": _root_store,
    "place": _root_place,
    "pick_and_place": _root_place,
    "open": _root_open,
    "close": _root_close,
}


# ---------------------------------------------------------------------
# Decomposition engine
# ---------------------------------------------------------------------


class _StepBuilder:
    """Assigns sequential `step_id`s and copies each primitive's
    registered pre/postconditions onto the `PlanStep`s it builds --
    same shape as `rule_based._StepBuilder`, kept as its own copy here
    (not imported) since HTN's decomposition engine, not
    `rule_based.py`, owns when/how primitives get emitted."""

    def __init__(self) -> None:
        self._next_id = 1
        self.steps: List[PlanStep] = []

    def add(
        self,
        action: str,
        target: Optional[str],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> PlanStep:
        from planner.actions import get_action_spec

        spec = get_action_spec(action)
        if (
            spec is None
        ):  # pragma: no cover - defensive, every call site is a real action
            raise UnsupportedGoalError(f"Unknown primitive action '{action}'.")
        step = PlanStep(
            step_id=self._next_id,
            action=action,
            target=target,
            parameters=parameters or {},
            description=spec.describe(target),
            preconditions=[p.description for p in spec.preconditions],
            postconditions=[
                d.format(target=target or "") for d in spec.postcondition_descriptions
            ],
        )
        self._next_id += 1
        self.steps.append(step)
        return step


def _decompose(task: Task, state: WorldState, builder: _StepBuilder) -> None:
    """Recursive task-network expansion: a primitive is emitted
    directly; a compound task selects its first applicable method (in
    `METHOD_LIBRARY[task.name]` order) and recurses into that method's
    subtasks. Raises `UnsupportedGoalError` if no method's
    precondition holds -- see this module's docstring for why this
    domain never needs backtracking across method choices."""
    if isinstance(task, PrimitiveTask):
        builder.add(task.action, task.target, task.parameters)
        return

    methods = METHOD_LIBRARY.get(task.name)
    if not methods:
        raise UnsupportedGoalError(
            f"HTNPlanner has no method library entry for compound task {task.name!r}."
        )
    for method in methods:
        if method.precondition(state, task.args):
            for subtask in method.decompose(task.args):
                _decompose(subtask, state, builder)
            return
    raise UnsupportedGoalError(
        f"No applicable method for compound task {task.name!r} given current state."
    )


class HTNPlanner(Planner):
    """Hierarchical Task Network planning strategy -- slice 1. See
    `docs/architecture/planning.md`'s "HTN planner" section for the
    full design and this module's docstring for scope."""

    planner_type = "htn"

    def _generate_steps(
        self,
        task: SingleTask,
        state: WorldState,
        memory_context: "Optional[PlannerMemoryContext]" = None,
    ) -> List[PlanStep]:
        # memory_context accepted, not consumed -- see this module's
        # docstring ("Memory hints: explicitly out of scope for this
        # slice") and planner.py's interface-conformance rationale.
        goal = (task.goal or "").strip().lower()
        if not goal:
            raise InvalidTaskError("Task has no goal; HTNPlanner cannot plan for it.")

        root_builder = HTN_GOAL_TASKS.get(goal)
        if root_builder is None:
            raise UnsupportedGoalError(
                f"HTNPlanner (slice 1) has no coverage for goal '{goal}'. "
                "Supported goals: " + ", ".join(sorted(HTN_GOAL_TASKS))
            )

        root_task = root_builder(task)
        builder = _StepBuilder()
        _decompose(root_task, state, builder)
        return builder.steps
