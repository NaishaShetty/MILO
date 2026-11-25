"""
progress.py (backend/planner)

Purpose
-------
`prune_satisfied_steps()` makes planning *resumable*: given the steps a
planner template produced and the `WorldState` the plan will start from,
it drops every step the state already satisfies, so a replan after
partial progress (or a plan for a goal that is already half-true) never
re-emits work that is already done.

Why this exists
---------------
`Orchestrator` reuses one `WorldState` across attempts, and
`ExecutionController` applies each succeeded step's effect to it. After
a partially successful run the state therefore says "robot_holding =
apple" -- but the planners' goal templates are pure functions of the
*task*, not the state, so a replan used to re-emit `locate`/`navigate`/
`pickup` for the apple. `pickup`'s `hand_empty` precondition then
rejected the replanned plan outright, turning "one step failed" into
"the whole task failed". Every planner (`RuleBasedPlanner`,
`HTNPlanner`, `BehaviorTreePlanner`, and `ReActPlanner`'s fallback)
now runs its steps through this one function, so the behaviour is
identical across strategies.

What counts as "already satisfied"
-----------------------------------
Only *effects* with an unambiguous symbolic signature are pruned:

- `pickup X`  -- the robot is already holding X. The whole acquire
  prefix for X (`locate X`/`navigate X`, plus any memory-hint
  `locate`/`navigate` pair in front of it) goes with it.
- `open X`    -- X is already open.
- `close X`   -- X is already known to be closed.
- `place X in C` -- X is already in C and not held. The deposit
  bracket (`locate C`/`navigate C`/`open C` before it, `close C` after
  it) goes with it.

`locate`/`navigate` on their own are never pruned: perceiving or
approaching something is cheap, and a stale "is_located" is a worse
failure than one redundant look.

The function never mutates its input steps' content; it only returns a
(possibly shorter) list, renumbered `1..n`. Skipped work is returned
as human-readable strings so a planner/UI can say *why* the plan is
shorter ("already holding the apple").
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from planner.actions import (
    CLOSE,
    LOCATE,
    NAVIGATE,
    OPEN,
    PICKUP,
    PLACE,
    TURN_OFF,
    TURN_ON,
    get_action_spec,
)
from planner.models import PlanStep
from planner.state import WorldState


def _norm(value: Optional[str]) -> Optional[str]:
    return value.strip().lower().replace("_", " ") if value else None


def _same(a: Optional[str], b: Optional[str]) -> bool:
    return _norm(a) is not None and _norm(a) == _norm(b)


def _satisfied_reason(step: PlanStep, state: WorldState) -> Optional[str]:
    """Why `step` is already done in `state`, or None if it is not."""
    target = step.target
    if not target:
        return None
    obj = state.object(target)
    if step.action == PICKUP:
        if _same(state.robot_holding, target) or obj.is_held:
            return f"already holding the {target}"
    elif step.action == OPEN:
        if obj.is_open is True:
            return f"the {target} is already open"
    elif step.action == CLOSE:
        if obj.is_open is False:
            return f"the {target} is already closed"
    elif step.action == TURN_ON:
        if obj.is_on is True:
            return f"the {target} is already on"
    elif step.action == TURN_OFF:
        if obj.is_on is False:
            return f"the {target} is already off"
    elif step.action == PLACE:
        container = step.parameters.get("container")
        if (
            container
            and not obj.is_held
            and not _same(state.robot_holding, target)
            and _same(obj.location, container)
        ):
            return f"the {target} is already in the {container}"
    return None


def prune_satisfied_steps(
    steps: List[PlanStep], state: WorldState
) -> Tuple[List[PlanStep], List[str]]:
    """
    Returns `(kept_steps, skipped_reasons)`. `kept_steps` is renumbered
    `1..n`; `skipped_reasons` has one human-readable entry per *satisfied
    step* that triggered pruning (not per dropped bracket step).
    """
    if not steps:
        return steps, []

    drop = [False] * len(steps)
    reasons: List[str] = []
    # A `place` already true in the *starting* state makes the whole
    # fetch-and-deposit segment around it pointless: the object is
    # already where the task wants it, so do not go and pick it up.
    for index, step in enumerate(steps):
        if step.action != PLACE:
            continue
        reason = _satisfied_reason(step, state)
        if reason is None:
            continue
        reasons.append(reason)
        drop[index] = True
        _drop_deposit_bracket(steps, drop, index)
        for k in range(index - 1, -1, -1):
            if steps[k].action == PICKUP and _same(steps[k].target, step.target):
                drop[k] = True
                _drop_acquire_prefix(steps, drop, k)
                break

    # Simulated as we walk, so a step is judged against the state *at
    # that point in the plan*, not only the starting state.
    working = state.clone()

    for index, step in enumerate(steps):
        if drop[index]:
            continue
        reason = _satisfied_reason(step, working)
        if reason is None:
            spec = get_action_spec(step.action)
            if spec is not None and (step.target or not spec.requires_target):
                spec.apply_effect(working, step.target, step.parameters)
            continue

        reasons.append(reason)
        drop[index] = True
        if step.action == PICKUP:
            _drop_acquire_prefix(steps, drop, index)
        elif step.action == PLACE:
            _drop_deposit_bracket(steps, drop, index)
        elif step.action in (OPEN, CLOSE, TURN_ON, TURN_OFF):
            _drop_approach_if_unused(steps, drop, index)

    kept = [s for i, s in enumerate(steps) if not drop[i]]
    for new_id, step in enumerate(kept, start=1):
        step.step_id = new_id
    return kept, reasons


def _drop_acquire_prefix(steps: List[PlanStep], drop: List[bool], pickup: int) -> None:
    target = steps[pickup].target
    j = pickup - 1
    while j >= 0 and steps[j].action in (LOCATE, NAVIGATE):
        from_memory = steps[j].parameters.get("source") == "memory"
        if not (_same(steps[j].target, target) or from_memory):
            break
        drop[j] = True
        j -= 1


def _drop_deposit_bracket(steps: List[PlanStep], drop: List[bool], place: int) -> None:
    container = steps[place].parameters.get("container")
    j = place - 1
    while j >= 0 and steps[j].action in (LOCATE, NAVIGATE, OPEN):
        if not _same(steps[j].target, container):
            break
        drop[j] = True
        j -= 1
    after = place + 1
    if after < len(steps) and steps[after].action == CLOSE:
        if _same(steps[after].target, container):
            drop[after] = True


def _drop_approach_if_unused(
    steps: List[PlanStep], drop: List[bool], index: int
) -> None:
    """
    A pruned `open`/`close` leaves its `locate`/`navigate` approach
    behind. Drop that approach too -- unless a later step still needs
    the robot at (or aware of) the same object, as in a deposit
    `[locate C, navigate C, open C, place X in C]` where `place` is
    still to come.
    """
    target = steps[index].target
    for later in steps[index + 1 :]:
        if _same(later.target, target) or _same(
            later.parameters.get("container"), target
        ):
            return
    j = index - 1
    while j >= 0 and steps[j].action in (LOCATE, NAVIGATE):
        from_memory = steps[j].parameters.get("source") == "memory"
        if not (_same(steps[j].target, target) or from_memory):
            break
        drop[j] = True
        j -= 1
