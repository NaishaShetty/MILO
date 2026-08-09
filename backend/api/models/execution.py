"""
execution.py (backend/api/models)

Purpose
-------
Request envelope for the Phase 5 Execution API (`api/routes/execution.py`).
Matches `api/models/planner.py`'s established pattern: reuse the real
backend model wherever one already exists
(`planner.models.Plan`, `execution.models.ExecutionRecord`,
`execution.models.ExecutionEvent`, `execution.models.StepExecutionRecord`)
so FastAPI's OpenAPI schema and the actual JSON this API returns are
always the authoritative Phase 5 model, never a hand-maintained copy
that can drift from it. This file only adds the one request-side
envelope that has no existing model.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from planner.models import Plan


class StartExecutionRequest(BaseModel):
    """Request body for `POST /api/v1/execution/start`."""

    model_config = ConfigDict(extra="forbid")

    plan: Plan = Field(
        description="A validated Plan (typically PlanningResult.plan from "
        "POST /api/v1/planner/plan) to execute step by step."
    )
    max_step_retries: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Bounded number of retries for a transient-looking step "
        "failure (SIMULATOR_ERROR, NAVIGATION_FAILED, OBJECT_NOT_REACHABLE, "
        "ACTION_TIMEOUT). 0 (default) disables retries entirely. Never "
        "unbounded -- see execution.controller's module docstring.",
    )
    step_timeout_s: Optional[float] = Field(
        default=None,
        gt=0,
        description="Per-action timeout in seconds. None (default) applies "
        "no timeout -- set this when running against a real simulator that "
        "might hang.",
    )
