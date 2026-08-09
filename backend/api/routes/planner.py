"""
planner.py (backend/api/routes)

Purpose
-------
HTTP interface around the Phase 4 Task Planning subsystem
(`backend/planner/`). Implements three endpoints:

- `POST /api/v1/planner/plan`     -- generate a Plan for a task with a
                                      chosen strategy.
- `POST /api/v1/planner/validate` -- validate a caller-supplied Plan
                                      against a task, independent of
                                      how it was generated.
- `POST /api/v1/planner/evaluate` -- compare every (or a chosen subset
                                      of) planning strategy on the same
                                      task, returning real, freshly
                                      measured metrics (never
                                      fabricated numbers -- see
                                      `planner/evaluation.py`'s
                                      docstring).

Contains no planning logic, no validation logic, and no state
simulation of its own -- every one of those already has exactly one
owner inside `backend/planner/` (`factory.create_planner`,
`validator.PlanValidator`, `evaluation.PlannerEvaluator`). This module
only translates HTTP requests into calls against that package and
translates its results (or a `ValueError` from an unknown planner
type) into HTTP responses, mirroring `api/routes/language.py`'s own
scope boundary.

Why this router never raises for an ordinary "plan is invalid" result
-------------------------------------------------------------------------
`Planner.plan()` and `PlanValidator.validate()` both return a result
object even when the plan they describe is invalid or unachievable
-- see `planner/exceptions.py`'s docstring on why that is normal
output, not an error. This router returns those results as an
ordinary 200 response; a client checks `success`/`valid` on the body,
exactly as it already checks `ParseResponse.status` for the Language
API's "clarification_required" case. The only case this router maps to
a non-2xx status is a request-shape problem this API layer itself can
detect before ever calling into `backend/planner/`: an unrecognized
`planner_type` string (422).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.models.planner import (
    EvaluateRequest,
    EvaluateResponse,
    PlannerMetricsResponse,
    PlanRequest,
    ValidateRequest,
)
from planner.evaluation import PlannerEvaluator
from planner.factory import available_planner_types, create_planner
from planner.models import PlanningResult, ValidationResult
from planner.state import WorldState
from planner.validator import PlanValidator

logger = logging.getLogger(__name__)

router = APIRouter()

_validator = PlanValidator()
_evaluator = PlannerEvaluator()


@router.post(
    "/plan",
    response_model=PlanningResult,
    summary="Generate a validated plan for a task",
    description=(
        "Expands a SingleTask into an ordered sequence of abstract "
        "PlanSteps using the requested planning strategy, then "
        "validates the result. Never calls AI2-THOR or produces a "
        "simulator-specific action -- see backend/planner/__init__.py."
    ),
    responses={422: {"description": "Unrecognized planner_type."}},
)
def plan_task(body: PlanRequest) -> PlanningResult:
    try:
        planner = create_planner(body.planner_type)
    except ValueError as exc:
        logger.warning(
            "planner_api.plan.invalid_planner_type",
            extra={"planner_type": body.planner_type},
        )
        raise HTTPException(
            status_code=422,
            detail={"category": "invalid_planner_type", "message": str(exc)},
        ) from None

    return planner.plan(body.task, WorldState.initial())


@router.post(
    "/validate",
    response_model=ValidationResult,
    summary="Validate a plan against a task",
    description=(
        "Replays a caller-supplied Plan against a fresh symbolic "
        "WorldState and reports structured validation issues -- "
        "independent of which strategy produced the plan."
    ),
)
def validate_plan(body: ValidateRequest) -> ValidationResult:
    return _validator.validate(body.plan, body.task, WorldState.initial())


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    summary="Compare planning strategies on one task",
    description=(
        "Runs every requested planning strategy (default: all "
        "registered strategies) against the same task and returns "
        "measured success/validity/latency/step-count metrics for "
        "each. Metrics are always freshly measured, never fabricated."
    ),
    responses={422: {"description": "An unrecognized planner_type was requested."}},
)
def evaluate_planners(body: EvaluateRequest) -> EvaluateResponse:
    requested = body.planner_types or available_planner_types()
    try:
        planners = {name: create_planner(name) for name in requested}
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"category": "invalid_planner_type", "message": str(exc)},
        ) from None

    metrics = _evaluator.compare(planners, body.task, WorldState.initial())
    return EvaluateResponse(
        task_id=body.task.task_id or "",
        results=[
            PlannerMetricsResponse(
                planner_type=m.planner_type,
                success=m.success,
                valid=m.valid,
                goal_satisfied=m.goal_satisfied,
                latency_ms=m.latency_ms,
                step_count=m.step_count,
                invalid_action_count=m.invalid_action_count,
                redundant_step_count=m.redundant_step_count,
                error=m.error,
            )
            for m in metrics
        ],
    )
