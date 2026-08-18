"""
rule_based.py (backend/planner)

Purpose
-------
Implements `RuleBasedPlanner`, the deterministic baseline planning
strategy: a fixed, table-driven expansion from a `SingleTask`'s
`goal`/`object`/`target` into an ordered list of `models.PlanStep`s,
with zero LLM calls and zero randomness. Two identical tasks *with the
same memory context* always produce byte-identical plans -- see
"Memory-conditioned search hints" below for the one deliberate,
still-fully-deterministic exception to "same task -> same plan
regardless of anything else." This is what section 6 asks for -- "a
reliable baseline, a debugging reference, a non-LLM comparison point,
and a source of deterministic expected plans for testing" -- and it is
the planner every other strategy in this package is compared against
(`evaluation.py`) or falls back to (`react.ReActPlanner`).

Reusable primitives, not per-goal hardcoding
----------------------------------------------
Every goal template below is assembled from a handful of primitive
step builders (`_locate`, `_navigate`, `_pickup`, `_open`, `_close`,
`_place`, `_generic`) that each construct exactly one `PlanStep` by
looking up its `actions.ActionSpec` -- the primitive itself never
invents a precondition/postcondition, it copies them from the
registry (see `actions.py`). Adding a new goal template is composing
these primitives in a new order, never writing new precondition logic;
this is what section 6's "do not create arbitrary hard-coded behavior
... use reusable planning primitives" is asking for.

Goal coverage
-------------
`GOAL_HANDLERS` covers every canonical goal in `parser_prompt.txt`'s
"SUPPORTED GOALS" catalog:
- Manipulation: `pick_up`, `place`, `pick_and_place`, `put_away`,
  `store`, `deliver`, `fetch`, `open`, `close`.
- Perception: `find`, `search_for`, `inspect`, `locate`, `count`.
- Navigation: `navigate_to`, `follow`, `return_to`.
- Everything else recognized by the parser but with no rich physical
  template here (`turn_on`, `turn_off`, `clean`, `charge`, `push`,
  `pull`, `wait`, `stop`, `pause`, `resume`, `patrol`) falls back to
  `generic_goal`: perceive+approach the object if one was given, then
  a single abstract `act` step -- this keeps the planner from refusing
  a goal the Language layer's *open* vocabulary might still produce
  (see `parser_prompt.txt`'s own "this catalog is a preference list,
  not a validation gate"), while still producing a symbolically
  inert, safely-validatable step rather than inventing physics this
  package does not model.  A goal this planner truly cannot make any
  sense of at all (no goal string, or no object/target of any kind)
  raises `InvalidTaskError`/`UnsupportedGoalError` rather than
  guessing.

Memory-conditioned search hints (Phase 6.3)
--------------------------------------------------
When a goal needs to locate an object this planner has no explicit
location for (`_acquire`'s LOCATE/NAVIGATE prefix, `_goal_perceive`,
`_goal_navigate`), and a `memory.agent.PlannerMemoryContext` was
supplied, `_apply_memory_hint()` looks for the highest-ranked
`SEMANTIC`/`USER` memory whose triple's `subject` matches the object
and whose `predicate` is one of a small, fixed, relation-agnostic
whitelist meaning "located at" (`located_on`, `located_in`,
`typically_stored_in`, `stored_in`, `observed_on`, `observed_in`) --
never a hardcoded object/location pair (section 23: "do not hard-code
'red mug' -> 'dining table' into the planner"). If found, it inserts a
`locate` + `navigate` pair for that *location* immediately before the
object's own `locate`/`navigate` steps, tagged
`parameters={"source": "memory", "memory_id": ..., "confidence": ...}`
so the resulting `Plan` is self-explanatory about *why* that extra
step exists (never a silent behavior change). This is a genuinely
different, inspectable plan (extra steps, a different first
`navigate` target) -- not a different final action -- preserving
planner autonomy (section 8): the plan still ends with `locate`/
`navigate` on the object itself, so if the memory hint is wrong (the
object was moved), the plan still finds it, just after visiting one
extra, plausible location first.

Current perception overrides stale memory
------------------------------------------------
`_apply_memory_hint()` is skipped entirely when `state.object(obj).
is_located` is already `True` -- i.e. the current `WorldState` (Vision-
grounded perception, once wired in; a caller-supplied non-default
`WorldState` today) already knows where the object is. Section 8's
requirement ("current perception should be capable of overriding stale
memory") falls out of the *existing* `WorldState` mechanism this
package already had -- no new state, no new precedence rule to invent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from planner.actions import CLOSE, GENERIC_ACT, LOCATE, NAVIGATE, OPEN, PICKUP, PLACE
from planner.exceptions import InvalidTaskError, UnsupportedGoalError
from planner.models import PlanStep
from planner.planner import Planner
from planner.state import WorldState
from schemas.task import SingleTask

if TYPE_CHECKING:  # pragma: no cover
    from memory.agent import PlannerMemoryContext
    from memory.retrieval import MemoryResult

GoalHandler = Callable[
    [SingleTask, WorldState, "Optional[PlannerMemoryContext]"], List[PlanStep]
]

#: Semantic/user-memory predicates this planner treats as "names a
#: location for the subject" -- a fixed, generic relation vocabulary,
#: never a specific subject/object pair. See this module's docstring.
_LOCATION_PREDICATES = {
    "located_on",
    "located_in",
    "typically_stored_in",
    "stored_in",
    "observed_on",
    "observed_in",
}

#: Minimum `Memory.confidence` a location-hint memory must have before
#: this planner will act on it -- a low-confidence memory (e.g. a
#: single stale/inferred observation) should not steer search order.
_MEMORY_HINT_MIN_CONFIDENCE = 0.4


def _normalize(text: str) -> str:
    return text.strip().lower().replace("_", " ")


def _find_location_hint(
    memory_context: "Optional[PlannerMemoryContext]", obj: str
) -> "Optional[Tuple[str, MemoryResult]]":
    """
    Returns `(location, result)` for the highest-ranked memory
    suggesting where `obj` is, or `None`. See this module's docstring
    for the exact matching rule.
    """
    if memory_context is None:
        return None

    from memory.models import MemoryType
    from memory.semantics import SemanticTriple

    target_subject = _normalize(obj)
    for result in memory_context.results:
        memory = result.memory
        if memory.memory_type not in (MemoryType.SEMANTIC, MemoryType.USER):
            continue
        if memory.confidence < _MEMORY_HINT_MIN_CONFIDENCE:
            continue
        try:
            triple = SemanticTriple.from_metadata(memory.metadata)
        except (KeyError, TypeError):
            continue
        if _normalize(triple.subject) != target_subject:
            continue
        if triple.predicate not in _LOCATION_PREDICATES:
            continue
        return triple.object, result
    return None


class _StepBuilder:
    """
    Assigns sequential `step_id`s and copies each action's registered
    pre/postconditions onto the `PlanStep`s it builds -- shared by
    every primitive below so no primitive has to manage numbering.
    """

    def __init__(self) -> None:
        self._next_id = 1
        self.steps: List[PlanStep] = []

    def add(
        self,
        action: str,
        target: Optional[str],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> PlanStep:
        from planner.actions import (
            get_action_spec,
        )  # local import avoids a cycle at module load

        spec = get_action_spec(action)
        if (
            spec is None
        ):  # pragma: no cover - defensive, every call site uses a real action
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


def _apply_memory_hint(
    builder: _StepBuilder,
    obj: str,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> None:
    """
    Inserts a `locate` + `navigate` pair for a memory-suggested
    location of `obj`, immediately before `_acquire`'s/`_goal_perceive`'s
    own `locate(obj)`/`navigate(obj)` steps -- see this module's
    docstring. No-op if `obj` is already located in `state` (current
    perception overrides stale memory) or no qualifying memory exists.
    """
    if state.object(obj).is_located:
        return
    hint = _find_location_hint(memory_context, obj)
    if hint is None:
        return
    location, result = hint
    builder.add(
        LOCATE,
        location,
        {
            "source": "memory",
            "memory_id": result.memory.memory_id,
            "confidence": result.memory.confidence,
        },
    )
    builder.add(
        NAVIGATE,
        location,
        {
            "source": "memory",
            "memory_id": result.memory.memory_id,
            "confidence": result.memory.confidence,
        },
    )


def _primary_reference(task: SingleTask) -> Optional[str]:
    return task.object or task.target or task.target_location or task.source_location


def _require(value: Optional[str], goal: str, field_name: str) -> str:
    if not value:
        raise InvalidTaskError(
            f"Goal '{goal}' requires a '{field_name}' but none was given."
        )
    return value


def _acquire(
    builder: _StepBuilder,
    obj: str,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]" = None,
) -> None:
    """locate + navigate + pickup -- the shared prefix of every manipulation goal."""
    _apply_memory_hint(builder, obj, state, memory_context)
    builder.add(LOCATE, obj)
    builder.add(NAVIGATE, obj)
    builder.add(PICKUP, obj)


def _deposit(
    builder: _StepBuilder,
    obj: str,
    target: str,
    state: WorldState,
    *,
    use_container: bool,
) -> None:
    """
    locate + navigate + (open) + place + (close) -- the shared suffix
    for placing an object.

    Whether `open`/`close` are inserted is state-aware, not just
    `use_container`: `use_container` (the "store"/"put_away" goals)
    still opens a target with unknown open/closed state (`is_open is
    None`) the way it always has, but a target `state` already knows is
    closed (`is_open is False`) -- e.g. a "place" goal targeting a
    closed drawer -- also gets an `open` inserted, since `place`'s
    `container_ready` precondition (see `actions._require_container_ready`)
    would otherwise fail outright. Conversely, a target `state` already
    knows is open (`is_open is True`) never gets a redundant `open` (which
    would itself fail `open`'s own `not_open` precondition) or a
    same-plan `close`.

    A target `state` knows for certain is NOT openable at all
    (`is_openable is False` -- e.g. a shelf, confirmed via live AI2-THOR
    metadata) never gets an `open`/`close` inserted, regardless of
    `use_container`/`is_open` -- a real AI2-THOR bug this project
    shipped and caught via its own floor-plan generalization sweep (see
    `docs/roadmap.md`): `store`ing onto a non-container receptacle
    should just place the object directly, the same as `place` already
    does for a target with no open/closed state at all. `is_openable`
    unknown (`None`, the common case when no live metadata was seeded)
    preserves the exact prior behavior -- this is strictly an added
    "we know for sure it can't be opened" carve-out, never a new
    default.
    """
    builder.add(LOCATE, target)
    builder.add(NAVIGATE, target)
    target_state = state.object(target)
    is_open = target_state.is_open
    needs_open = (
        target_state.is_openable is not False
        and is_open is not True
        and (use_container or is_open is False)
    )
    if needs_open:
        builder.add(OPEN, target)
    builder.add(PLACE, obj, {"container": target})
    if needs_open:
        builder.add(CLOSE, target)


def _goal_store(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> List[PlanStep]:
    obj = _require(task.object, task.goal or "store", "object")
    target = _require(
        task.target or task.target_location, task.goal or "store", "target"
    )
    builder = _StepBuilder()
    _acquire(builder, obj, state, memory_context)
    _deposit(builder, obj, target, state, use_container=True)
    return builder.steps


def _goal_place(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> List[PlanStep]:
    obj = _require(task.object, task.goal or "place", "object")
    target = _require(
        task.target or task.target_location, task.goal or "place", "target"
    )
    builder = _StepBuilder()
    _acquire(builder, obj, state, memory_context)
    _deposit(builder, obj, target, state, use_container=False)
    return builder.steps


def _goal_pick_up(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> List[PlanStep]:
    obj = _require(task.object, task.goal or "pick_up", "object")
    builder = _StepBuilder()
    _acquire(builder, obj, state, memory_context)
    return builder.steps


def _goal_fetch(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> List[PlanStep]:
    obj = _require(task.object, task.goal or "fetch", "object")
    builder = _StepBuilder()
    _acquire(builder, obj, state, memory_context)
    destination = task.target or task.target_location
    if destination:
        builder.add(LOCATE, destination)
        builder.add(NAVIGATE, destination)
    return builder.steps


def _goal_deliver(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> List[PlanStep]:
    obj = _require(task.object, task.goal or "deliver", "object")
    destination = _require(
        task.target or task.target_location, task.goal or "deliver", "target"
    )
    builder = _StepBuilder()
    _acquire(builder, obj, state, memory_context)
    builder.add(LOCATE, destination)
    builder.add(NAVIGATE, destination)
    return builder.steps


def _goal_open(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> List[PlanStep]:
    obj = _require(_primary_reference(task), task.goal or "open", "object or target")
    builder = _StepBuilder()
    _apply_memory_hint(builder, obj, state, memory_context)
    builder.add(LOCATE, obj)
    builder.add(NAVIGATE, obj)
    builder.add(OPEN, obj)
    return builder.steps


def _goal_close(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> List[PlanStep]:
    obj = _require(_primary_reference(task), task.goal or "close", "object or target")
    builder = _StepBuilder()
    _apply_memory_hint(builder, obj, state, memory_context)
    builder.add(LOCATE, obj)
    builder.add(NAVIGATE, obj)
    builder.add(CLOSE, obj)
    return builder.steps


def _goal_perceive(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> List[PlanStep]:
    obj = _require(_primary_reference(task), task.goal or "find", "object or target")
    builder = _StepBuilder()
    _apply_memory_hint(builder, obj, state, memory_context)
    builder.add(LOCATE, obj)
    builder.add(NAVIGATE, obj)
    return builder.steps


def _goal_navigate(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]",
) -> List[PlanStep]:
    ref = _require(
        _primary_reference(task), task.goal or "navigate_to", "object or target"
    )
    builder = _StepBuilder()
    _apply_memory_hint(builder, ref, state, memory_context)
    builder.add(LOCATE, ref)
    builder.add(NAVIGATE, ref)
    return builder.steps


def generic_goal(
    task: SingleTask,
    state: WorldState,
    memory_context: "Optional[PlannerMemoryContext]" = None,
) -> List[PlanStep]:
    """
    Fallback for a recognized-but-not-richly-modeled goal (see this
    module's docstring). Requires at least a goal name; an object is
    optional (e.g. "pause" needs neither an object nor a location).
    """
    if not task.goal:
        raise InvalidTaskError("Task has no goal; cannot plan.")
    builder = _StepBuilder()
    ref = _primary_reference(task)
    if ref:
        _apply_memory_hint(builder, ref, state, memory_context)
        builder.add(LOCATE, ref)
        builder.add(NAVIGATE, ref)
        builder.add(GENERIC_ACT, ref, {"action": task.goal})
    else:
        builder.add(GENERIC_ACT, None, {"action": task.goal})
    return builder.steps


GOAL_HANDLERS: Dict[str, GoalHandler] = {
    "store": _goal_store,
    "put_away": _goal_store,
    "place": _goal_place,
    "pick_and_place": _goal_place,
    "pick_up": _goal_pick_up,
    "fetch": _goal_fetch,
    "deliver": _goal_deliver,
    "open": _goal_open,
    "close": _goal_close,
    "find": _goal_perceive,
    "search_for": _goal_perceive,
    "locate": _goal_perceive,
    "inspect": _goal_perceive,
    "count": _goal_perceive,
    "navigate_to": _goal_navigate,
    "follow": _goal_navigate,
    "return_to": _goal_navigate,
}

# Goals the Language layer's open vocabulary may still emit
# (`parser_prompt.txt`'s "State change"/"Control" families, plus
# `patrol`/`push`/`pull`) that this planner handles via the generic
# fallback rather than a dedicated physical template.
_GENERIC_GOALS = {
    "turn_on",
    "turn_off",
    "clean",
    "charge",
    "push",
    "pull",
    "wait",
    "stop",
    "pause",
    "resume",
    "patrol",
}


class RuleBasedPlanner(Planner):
    """
    The deterministic baseline strategy. See this module's docstring
    for the full goal-coverage table and design rationale.
    """

    planner_type = "rule_based"

    def _generate_steps(
        self,
        task: SingleTask,
        state: WorldState,
        memory_context: "Optional[PlannerMemoryContext]" = None,
    ) -> List[PlanStep]:
        goal = (task.goal or "").strip().lower()
        if not goal:
            raise InvalidTaskError(
                "Task has no goal; RuleBasedPlanner cannot plan for it."
            )

        handler = GOAL_HANDLERS.get(goal)
        if handler is not None:
            return handler(task, state, memory_context)
        # Either one of `_GENERIC_GOALS` or an entirely novel goal the
        # Language layer's open vocabulary produced (see
        # parser_prompt.txt's "EXTENSION GUIDANCE") -- both fall back
        # to the generic template rather than refusing to plan.
        return generic_goal(task, state, memory_context)
