"""
validator.py (backend/planner)

Purpose
-------
Implements `PlanValidator`, the dedicated plan-validation component
section 8 requires: given a `models.Plan` and the `SingleTask` it was
built for, replay every step against a `state.WorldState` and report a
structured `models.ValidationResult` -- never a bare `True`/`False`.

What it checks (in order)
--------------------------
1. Action recognition -- every `PlanStep.action` resolves against
   `actions.ACTION_REGISTRY`.
2. Required parameters -- every `ActionSpec.required_parameters` key is
   present on the step, and `target` is present when the action
   requires one.
3. Preconditions -- replaying steps in order against a cloned
   `WorldState`, each step's `ActionSpec.check_preconditions` must pass
   given the state as of *that* point in the plan. This is what catches
   "Place apple" before "Pickup apple", or "Close refrigerator" before
   it was ever opened -- the ordering/dependency check falls directly
   out of state simulation rather than being a separate ad hoc rule.
4. Redundant steps -- an identical (action, target, parameters) step
   immediately following another is flagged as a warning (not an
   error): usually harmless, but worth surfacing per section 8's
   "duplicate/unnecessary steps" requirement.
5. Goal completion -- once every step has been simulated, `GOAL_CHECKS`
   (keyed by the task's `goal`) inspects the final `WorldState` to
   confirm the task's own success condition actually holds. A goal with
   no registered check yields `goal_satisfied=None` (unverifiable, not
   failed) -- see `models.ValidationResult`'s docstring for why that
   distinction matters.

A plan is `valid` iff it has zero `severity="error"` issues. An
unverifiable goal does not, by itself, make a plan invalid -- it is
reported so a caller can decide how much to trust the result, but it is
not treated as an error for goals this validator's vocabulary does not
yet cover (matching this project's "open, not closed, goal vocabulary"
precedent from `parser_prompt.txt`).
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from planner.actions import get_action_spec
from planner.models import Plan, PlanStatus, ValidationIssue, ValidationResult
from planner.state import WorldState
from schemas.task import SingleTask

GoalCheck = Callable[[SingleTask, WorldState], bool]


def _norm(value: Optional[str]) -> Optional[str]:
    return value.strip().lower() if value else None


def _goal_store(task: SingleTask, state: WorldState) -> bool:
    obj, target = _norm(task.object), _norm(task.target)
    if not obj or not target:
        return False
    o = state.object(obj)
    return (not o.is_held) and o.location == target


def _goal_pickup(task: SingleTask, state: WorldState) -> bool:
    obj = _norm(task.object)
    if obj is None:
        return False
    return state.robot_holding == obj


def _goal_open(task: SingleTask, state: WorldState) -> bool:
    ref = _norm(task.object) or _norm(task.target)
    if ref is None:
        return False
    return state.object(ref).is_open is True


def _goal_close(task: SingleTask, state: WorldState) -> bool:
    ref = _norm(task.object) or _norm(task.target)
    if ref is None:
        return False
    return state.object(ref).is_open is False


def _goal_locate(task: SingleTask, state: WorldState) -> bool:
    ref = _norm(task.object) or _norm(task.target)
    if ref is None:
        return False
    return state.object(ref).is_located


def _goal_navigate(task: SingleTask, state: WorldState) -> bool:
    ref = _norm(task.object) or _norm(task.target) or _norm(task.target_location)
    if ref is None:
        return False
    return state.robot_location == ref


# Registered per canonical goal name (see parser_prompt.txt's "SUPPORTED
# GOALS" catalog). Goals not listed here yield `goal_satisfied=None`
# rather than False -- see this module's docstring.
GOAL_CHECKS: Dict[str, GoalCheck] = {
    "store": _goal_store,
    "put_away": _goal_store,
    "pick_and_place": _goal_store,
    "place": _goal_store,
    "pick_up": _goal_pickup,
    "fetch": _goal_pickup,
    "deliver": _goal_pickup,
    "open": _goal_open,
    "close": _goal_close,
    "find": _goal_locate,
    "search_for": _goal_locate,
    "locate": _goal_locate,
    "inspect": _goal_locate,
    "count": _goal_locate,
    "navigate_to": _goal_navigate,
    "follow": _goal_navigate,
    "return_to": _goal_navigate,
}


class PlanValidator:
    """
    Stateless validator: `validate()` takes the plan/task/initial state
    it needs as arguments rather than holding any of them as instance
    state, so one `PlanValidator` instance can be shared (and is,
    intentionally, by `planner.Planner`'s shared `_finalize` helper)
    across every planning strategy and every request.
    """

    def validate(
        self, plan: Plan, task: SingleTask, initial_state: WorldState
    ) -> ValidationResult:
        issues = []
        state = initial_state.clone()
        previous_signature: Optional[tuple] = None

        for step in plan.steps:
            spec = get_action_spec(step.action)
            if spec is None:
                issues.append(
                    ValidationIssue(
                        step_id=step.step_id,
                        code="unknown_action",
                        message=f"Action '{step.action}' is not a recognized planning action.",
                        severity="error",
                    )
                )
                previous_signature = None
                continue

            if spec.requires_target and not step.target:
                issues.append(
                    ValidationIssue(
                        step_id=step.step_id,
                        code="missing_target",
                        message=f"Action '{step.action}' requires a target.",
                        severity="error",
                    )
                )
            missing_params = [
                p for p in spec.required_parameters if p not in step.parameters
            ]
            if missing_params:
                issues.append(
                    ValidationIssue(
                        step_id=step.step_id,
                        code="missing_parameter",
                        message=f"Action '{step.action}' is missing required "
                        f"parameter(s): {', '.join(missing_params)}.",
                        severity="error",
                    )
                )

            failed = spec.check_preconditions(state, step.target, step.parameters)
            for precondition in failed:
                issues.append(
                    ValidationIssue(
                        step_id=step.step_id,
                        code="precondition_failed",
                        message=f"Step {step.step_id} ({step.description}): "
                        f"precondition '{precondition.code}' not satisfied -- "
                        f"{precondition.description}.",
                        severity="error",
                    )
                )

            signature = (
                step.action,
                step.target,
                tuple(sorted(step.parameters.items())),
            )
            if signature == previous_signature:
                issues.append(
                    ValidationIssue(
                        step_id=step.step_id,
                        code="duplicate_step",
                        message=f"Step {step.step_id} repeats the immediately "
                        "preceding step and may be redundant.",
                        severity="warning",
                    )
                )
            previous_signature = signature

            if (
                not missing_params
                and not failed
                and (step.target or not spec.requires_target)
            ):
                spec.apply_effect(state, step.target, step.parameters)

        goal_check = GOAL_CHECKS.get((task.goal or "").strip().lower())
        goal_satisfied = goal_check(task, state) if goal_check else None
        if goal_check is not None and not goal_satisfied:
            issues.append(
                ValidationIssue(
                    step_id=None,
                    code="goal_not_satisfied",
                    message=f"The plan's final state does not satisfy goal "
                    f"'{task.goal}'.",
                    severity="error",
                )
            )

        result = ValidationResult(
            valid=all(issue.severity != "error" for issue in issues),
            issues=issues,
            goal_satisfied=goal_satisfied,
        )
        plan.status = PlanStatus.VALID if result.valid else PlanStatus.INVALID
        return result
