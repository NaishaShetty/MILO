"""
planner.py (backend/api/models)

Purpose
-------
Request envelopes for the Phase 4 Planning API
(`api/routes/planner.py`). Matches `api/models/language.py`'s
established pattern: reuse the real backend model wherever one already
exists (`schemas.task.SingleTask`, `planner.models.Plan`,
`planner.models.PlanningResult`, `planner.models.ValidationResult`) so
FastAPI's OpenAPI schema and the actual JSON this API returns are
always the authoritative Phase 4 model, never a hand-maintained copy
that can drift from it. This file only adds the small request-side
envelopes (`PlanRequest`, `ValidateRequest`, `EvaluateRequest`) and the
one response shape (`EvaluateResponse`) that has no existing model,
because `evaluation.PlannerMetrics` is a plain dataclass, not a
Pydantic model with its own OpenAPI representation.

Why `state` is not part of any request body yet
--------------------------------------------------
Every endpoint plans against a fresh `state.WorldState.initial()` (no
objects perceived yet) rather than accepting caller-supplied state.
Grounding a `WorldState` from Phase 2's Vision/scene-graph output is
explicitly future work (see `planner/__init__.py`'s roadmap and
`docs/architecture/spatial_perception.md`'s "Planner Boundary"
section) -- this API does not yet fuse Vision and Planning, mirroring
`api/app.py`'s own "Neither combines with the other yet" disclaimer for
Vision and Language. Accepting a `state` field before that integration
exists would invite a client to fabricate world state the backend
cannot actually verify.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from planner.models import Plan
from schemas.task import SingleTask


class PlanRequest(BaseModel):
    """Request body for `POST /api/v1/planner/plan`."""

    model_config = ConfigDict(extra="forbid")

    task: SingleTask = Field(
        description="The SingleTask to plan for -- typically the "
        "result field of a Phase 3 language-parsing response."
    )
    planner_type: str = Field(
        default="rule_based",
        description="Which planning strategy to use: 'rule_based', "
        "'react', or 'behavior_tree'. See planner.factory.PlannerType.",
    )


class ValidateRequest(BaseModel):
    """Request body for `POST /api/v1/planner/validate`."""

    model_config = ConfigDict(extra="forbid")

    task: SingleTask = Field(description="The task the plan was built for.")
    plan: Plan = Field(description="The plan to validate.")


class EvaluateRequest(BaseModel):
    """Request body for `POST /api/v1/planner/evaluate`."""

    model_config = ConfigDict(extra="forbid")

    task: SingleTask = Field(
        description="The task to plan for, once per compared strategy."
    )
    planner_types: Optional[List[str]] = Field(
        default=None,
        description="Which strategies to compare. Defaults to every "
        "registered strategy (planner.factory.available_planner_types()).",
    )


class PlannerMetricsResponse(BaseModel):
    """
    Pydantic mirror of `evaluation.PlannerMetrics` (a plain dataclass)
    for OpenAPI documentation -- see this module's docstring for why a
    dataclass needs this thin wrapper while Pydantic models
    (`Plan`, `PlanningResult`) do not.
    """

    planner_type: str
    success: bool
    valid: bool
    goal_satisfied: Optional[bool]
    latency_ms: float
    step_count: int
    invalid_action_count: int
    redundant_step_count: int
    error: Optional[str] = None


class EvaluateResponse(BaseModel):
    """Response body for `POST /api/v1/planner/evaluate`."""

    task_id: str
    results: List[PlannerMetricsResponse]
