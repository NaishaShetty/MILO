"""
lab.py (backend/api/models)

Purpose
-------
Request/response envelopes for `api/routes/lab.py` (Phase 8.2's "MILO
Lab" experimentation API). Matches `api/models/planner.py`'s pattern:
reuse real backend models wherever one exists (`schemas.task.
SingleTask`, `planner.models.PlanningResult`, `schemas.task.
ParsedInstruction`); only add the small envelope shapes that have no
existing model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from planner.models import PlanningResult
from schemas.task import ParsedInstruction


class ExperimentSummary(BaseModel):
    """One persisted experiment run, real data read from `results/<type>/
    benchmark_runs/<run_id>/summary.json` -- see `routes/lab.py::
    list_experiments`. Never a fabricated/mocked entry."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    experiment_type: str
    timestamp: str
    result: Dict[str, Any]


class ExperimentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiments: List[ExperimentSummary]


class SandboxRequest(BaseModel):
    """Body for `POST /api/v1/lab/sandbox` -- free-text instruction,
    parsed and planned in one round trip without touching the
    simulator (a dry run)."""

    model_config = ConfigDict(extra="forbid")

    instruction: str
    planner_type: str = "rule_based"


class SandboxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parsed: ParsedInstruction
    #: `None` when `parsed` is a MultiTask -- the registered planners
    #: only plan a single SingleTask (see `routes/tasks.py`'s identical
    #: MultiTask restriction); the sandbox reports that honestly rather
    #: than guessing which sub-task to plan.
    plan: Optional[PlanningResult] = None
    unsupported_reason: Optional[str] = None


class LabStatsResponse(BaseModel):
    """Real aggregate counts -- see `routes/lab.py::get_lab_stats` for
    exactly what each is computed from. No fabricated statistics."""

    model_config = ConfigDict(extra="forbid")

    experiments_run: int
    task_success_rate: Optional[float]
    total_actions: int
    memories_created: int
    tasks_run: int
