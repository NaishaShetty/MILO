"""
actions.py (backend/planner)

Purpose
-------
The action model: a registry (`ACTION_REGISTRY`) mapping every abstract
planning action name (`"locate"`, `"navigate"`, `"pickup"`, `"open"`,
`"close"`, `"place"`, `"put_down"`) to an `ActionSpec` describing its
required parameters, its `Precondition`s (checked against a
`state.WorldState` before the action may run), and its effect (how it
mutates a `WorldState` once it does run).

This is the single source of truth every other module in this package
reads from: `rule_based.py` and `behavior_tree.py` build `PlanStep`s by
looking up an `ActionSpec` (never inventing preconditions/postconditions
themselves), `validator.py` replays a plan by looking up the same
`ActionSpec`s, and `react.py` validates an LLM's proposed action name
against `ACTION_REGISTRY` before ever trusting it. Centralizing this
means a new action is added in exactly one place and every planner and
the validator pick it up automatically -- no planner-specific
duplication of "what does `open` require".

Why abstract actions, not simulator actions
--------------------------------------------
Every action name here is a planning-level abstraction
(`"navigate"`, not `"MoveAhead"`/`"RotateRight"`) -- see
`backend/planner/__init__.py` and `models.py` for the architectural
rule this enforces. Translating `"navigate"` into a sequence of
AI2-THOR primitives (a path of `MoveAhead`/`RotateLeft` calls) is
explicitly Phase 5's job.

Design notes
------------
- `Precondition.check` and `ActionSpec.apply_effect` take
  `(state, target, parameters)` and either return `bool` or mutate
  `state` in place -- no exceptions for an ordinary "precondition not
  met", by convention; validators/planners are expected to call
  `check()` and branch on the boolean, not catch an exception. This
  keeps `validator.py` a simple, side-effect-visible loop instead of a
  try/except cascade.
- `REQUIRES_OBJECT_PARAM`, kept per `ActionSpec` as `required_parameters`,
  documents which `PlanStep.parameters` keys must be present (e.g.
  `place` requires `parameters["container"]`) -- `validator.py` and
  `rule_based.py` both read this instead of hardcoding which action
  needs what.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from planner.state import WorldState

LOCATE = "locate"
NAVIGATE = "navigate"
PICKUP = "pickup"
PLACE = "place"
OPEN = "open"
CLOSE = "close"
PUT_DOWN = "put_down"
GENERIC_ACT = "act"

CheckFn = Callable[[WorldState, Optional[str], Dict[str, Any]], bool]
EffectFn = Callable[[WorldState, Optional[str], Dict[str, Any]], None]


@dataclass(frozen=True)
class Precondition:
    """One named, human-describable condition an ActionSpec requires."""

    code: str
    description: str
    check: CheckFn


@dataclass(frozen=True)
class ActionSpec:
    """
    Full specification of one abstract planning action: what it needs
    to run (`required_parameters`, `preconditions`), what it guarantees
    once it has (`postcondition_descriptions`, `apply_effect`), and a
    human label used to build `PlanStep.description`.
    """

    name: str
    description_template: str
    required_parameters: List[str] = field(default_factory=list)
    requires_target: bool = True
    preconditions: List[Precondition] = field(default_factory=list)
    postcondition_descriptions: List[str] = field(default_factory=list)
    apply_effect: EffectFn = field(default=lambda state, target, params: None)

    def describe(self, target: Optional[str]) -> str:
        return self.description_template.format(target=target or "")

    def check_preconditions(
        self, state: WorldState, target: Optional[str], parameters: Dict[str, Any]
    ) -> List[Precondition]:
        """Returns the subset of preconditions that are NOT satisfied."""
        return [p for p in self.preconditions if not p.check(state, target, parameters)]


def _require_target_located(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> bool:
    if target is None:
        return False
    return state.object(target).is_located


def _require_target_near(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> bool:
    if target is None:
        return False
    return state.object(target).is_near_robot


def _require_hand_empty(
    state: WorldState, _target: Optional[str], _params: Dict[str, Any]
) -> bool:
    return state.robot_holding is None


def _require_not_already_held(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> bool:
    if target is None:
        return False
    return not state.object(target).is_held


def _require_not_open(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> bool:
    if target is None:
        return False
    return state.object(target).is_open is not True


def _require_open(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> bool:
    if target is None:
        return False
    return state.object(target).is_open is True


def _require_holding_target(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> bool:
    if target is None:
        return False
    return state.robot_holding == target.strip().lower()


def _require_container_ready(
    state: WorldState, _target: Optional[str], params: Dict[str, Any]
) -> bool:
    """
    `place`'s destination container must exist and, if it has ever been
    opened/closed (i.e. `is_open is not None`), must currently be open.
    A container never referenced by an `open` step (e.g. a bare
    tabletop) has `is_open is None` and is treated as always ready --
    not every placement target is an openable container.
    """
    container = params.get("container")
    if not container:
        return False
    return state.object(container).is_open is not False


def _effect_locate(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> None:
    if target:
        state.object(target).is_located = True


def _effect_navigate(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> None:
    if target:
        state.object(target).is_near_robot = True
        state.robot_location = target.strip().lower()


def _effect_pickup(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> None:
    if target:
        obj = state.object(target)
        obj.is_held = True
        obj.location = "robot"
        state.robot_holding = target.strip().lower()


def _effect_open(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> None:
    if target:
        state.object(target).is_open = True


def _effect_close(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> None:
    if target:
        state.object(target).is_open = False


def _effect_place(
    state: WorldState, target: Optional[str], params: Dict[str, Any]
) -> None:
    container = params.get("container")
    if target:
        obj = state.object(target)
        obj.is_held = False
        obj.location = container
    state.robot_holding = None


def _effect_put_down(
    state: WorldState, target: Optional[str], _params: Dict[str, Any]
) -> None:
    if target:
        obj = state.object(target)
        obj.is_held = False
        obj.location = state.robot_location
    state.robot_holding = None


def _effect_generic_act(
    _state: WorldState, _target: Optional[str], _params: Dict[str, Any]
) -> None:
    # A control/state-change action this package has no dedicated
    # symbolic effect for yet (e.g. "turn_on", "clean", "wait"). It has
    # no preconditions and no modeled effect -- see rule_based.py's
    # generic-fallback template for why this is a deliberate, narrow
    # escape hatch rather than a way to bypass validation for the
    # actions this package *does* model.
    return None


ACTION_REGISTRY: Dict[str, ActionSpec] = {
    LOCATE: ActionSpec(
        name=LOCATE,
        description_template="Locate {target}",
        preconditions=[],
        postcondition_descriptions=["{target} is perceived/known"],
        apply_effect=_effect_locate,
    ),
    NAVIGATE: ActionSpec(
        name=NAVIGATE,
        description_template="Navigate to {target}",
        preconditions=[
            Precondition(
                "target_located",
                "target must be located before navigating to it",
                _require_target_located,
            )
        ],
        postcondition_descriptions=["robot is near {target}"],
        apply_effect=_effect_navigate,
    ),
    PICKUP: ActionSpec(
        name=PICKUP,
        description_template="Pick up {target}",
        preconditions=[
            Precondition(
                "target_near",
                "robot must be near target to pick it up",
                _require_target_near,
            ),
            Precondition(
                "hand_empty", "robot's hand must be empty", _require_hand_empty
            ),
            Precondition(
                "not_already_held",
                "target must not already be held",
                _require_not_already_held,
            ),
        ],
        postcondition_descriptions=["robot is holding {target}"],
        apply_effect=_effect_pickup,
    ),
    OPEN: ActionSpec(
        name=OPEN,
        description_template="Open {target}",
        preconditions=[
            Precondition(
                "target_near",
                "robot must be near target to open it",
                _require_target_near,
            ),
            Precondition(
                "not_open", "target must not already be open", _require_not_open
            ),
        ],
        postcondition_descriptions=["{target} is open"],
        apply_effect=_effect_open,
    ),
    CLOSE: ActionSpec(
        name=CLOSE,
        description_template="Close {target}",
        preconditions=[
            Precondition(
                "target_near",
                "robot must be near target to close it",
                _require_target_near,
            ),
            Precondition("is_open", "target must currently be open", _require_open),
        ],
        postcondition_descriptions=["{target} is closed"],
        apply_effect=_effect_close,
    ),
    PLACE: ActionSpec(
        name=PLACE,
        description_template="Place {target} inside destination",
        required_parameters=["container"],
        preconditions=[
            Precondition(
                "holding_target",
                "robot must be holding target",
                _require_holding_target,
            ),
            Precondition(
                "container_ready",
                "destination container must exist and be open if openable",
                _require_container_ready,
            ),
        ],
        postcondition_descriptions=[
            "{target} is inside destination",
            "robot's hand is empty",
        ],
        apply_effect=_effect_place,
    ),
    PUT_DOWN: ActionSpec(
        name=PUT_DOWN,
        description_template="Put down {target}",
        preconditions=[
            Precondition(
                "holding_target",
                "robot must be holding target",
                _require_holding_target,
            )
        ],
        postcondition_descriptions=["{target} is placed down", "robot's hand is empty"],
        apply_effect=_effect_put_down,
    ),
    GENERIC_ACT: ActionSpec(
        name=GENERIC_ACT,
        description_template="Perform action on {target}",
        requires_target=False,
        preconditions=[],
        postcondition_descriptions=[],
        apply_effect=_effect_generic_act,
    ),
}


def get_action_spec(name: str) -> Optional[ActionSpec]:
    """Looks up an ActionSpec by name, or None if `name` is unregistered."""
    return ACTION_REGISTRY.get(name)
