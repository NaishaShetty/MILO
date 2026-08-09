"""
preconditions.py (backend/execution)

Purpose
-------
`PreconditionChecker` is section 6's precondition validation layer:
the executor must never blindly dispatch an action. It runs in two
layers, deliberately kept distinct:

1. **Symbolic** -- reuses `planner.actions.ACTION_REGISTRY` and
   `planner.state.WorldState` directly (the exact objects
   `planner.validator.PlanValidator` already uses to validate a plan
   *before* execution). This package never re-derives "what does
   `pickup` require" -- see `__init__.py`'s module docstring. This
   layer catches ordering/dependency mistakes (place before pickup,
   close before open) exactly like Phase 4's validator does, replayed
   against the *live* execution-time state rather than a hypothetical
   one.
2. **Grounded** -- checks this package can make that Phase 4's purely
   symbolic `WorldState` cannot, because they depend on the actual
   simulator scene: does a live AI2-THOR object matching this step's
   target/container actually exist right now (`resolver.ObjectResolver`
   already tried and failed), i.e. sections 6's "object exists" /
   "target exists" checks. This layer is intentionally narrow: it
   checks *existence*, not fine-grained interactability/grasp
   feasibility -- AI2-THOR's own `lastActionSuccess` on dispatch is
   still the authoritative interactability check (see `validator.py`),
   and this module never fabricates a "yes, reachable" answer it
   cannot actually verify (per the Phase 5 spec's explicit "if a
   precondition cannot be verified with the current architecture,
   model that limitation rather than pretending it was verified" rule).
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from execution.errors import ExecutionErrorCode
from planner.actions import get_action_spec
from planner.models import PlanStep
from planner.state import WorldState

# Actions that translate to a real simulator call requiring a resolved
# AI2-THOR objectId for their primary target. `locate` is deliberately
# excluded -- it has no simulator-side effect (see `dispatcher.py`) and
# so has nothing to resolve.
_REQUIRES_RESOLVED_TARGET = {"navigate", "pickup", "open", "close"}


class PreconditionCheckResult(BaseModel):
    """Outcome of one `PreconditionChecker.check()` call."""

    model_config = ConfigDict(extra="forbid")

    satisfied: bool
    unmet: List[str] = []
    error_code: Optional[ExecutionErrorCode] = None
    message: Optional[str] = None


class PreconditionChecker:
    """Stateless -- every check takes the state/resolution it needs as arguments."""

    def check(
        self,
        step: PlanStep,
        state: WorldState,
        *,
        resolved_object_id: Optional[str],
        resolved_container_id: Optional[str] = None,
    ) -> PreconditionCheckResult:
        spec = get_action_spec(step.action)
        if spec is None:
            return PreconditionCheckResult(
                satisfied=False,
                error_code=ExecutionErrorCode.INVALID_ACTION,
                message=f"Unknown action {step.action!r} -- no ActionSpec registered.",
            )

        missing_params = [
            name for name in spec.required_parameters if name not in step.parameters
        ]
        if missing_params:
            return PreconditionCheckResult(
                satisfied=False,
                error_code=ExecutionErrorCode.INVALID_PARAMETER,
                message=f"Missing required parameter(s) {missing_params} for "
                f"action {step.action!r}.",
            )

        # Grounded existence checks -- run before the symbolic check so
        # a step that can never be dispatched (nothing to act on) is
        # reported as OBJECT_NOT_FOUND/TARGET_NOT_FOUND, the more
        # specific and actionable failure, rather than a generic
        # precondition-failed message.
        if step.action in _REQUIRES_RESOLVED_TARGET and resolved_object_id is None:
            return PreconditionCheckResult(
                satisfied=False,
                error_code=ExecutionErrorCode.OBJECT_NOT_FOUND,
                message=f"No live object matching target {step.target!r} was "
                "found in the current scene.",
            )
        if step.action == "place" and resolved_container_id is None:
            container_name = step.parameters.get("container")
            return PreconditionCheckResult(
                satisfied=False,
                error_code=ExecutionErrorCode.TARGET_NOT_FOUND,
                message=f"No live object matching container {container_name!r} "
                "was found in the current scene.",
            )

        unmet = spec.check_preconditions(state, step.target, step.parameters)
        if unmet:
            return PreconditionCheckResult(
                satisfied=False,
                unmet=[p.description for p in unmet],
                error_code=ExecutionErrorCode.PRECONDITION_FAILED,
                message=f"Unmet precondition(s) for {step.action!r} on "
                f"{step.target!r}: " + "; ".join(p.description for p in unmet),
            )

        return PreconditionCheckResult(satisfied=True)
