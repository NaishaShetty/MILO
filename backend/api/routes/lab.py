"""
lab.py (backend/api/routes)

Purpose
-------
HTTP interface for Phase 8.2's "MILO Lab" page: real experiment
listing/triggering, a real dry-run sandbox, and real aggregate stats.
Every number this module returns is computed from an existing,
already-real subsystem -- `vision_evaluation`'s benchmark runner,
`planner.evaluation.PlannerEvaluator` (already used by `POST /api/v1/
planner/evaluate`), `language.agent.LanguageAgent`, `planner.factory.
create_planner`, and the same `_TaskStore`/`MemoryAgent` every other
route reads. This module adds no new persistence layer and no new
subsystem -- see the Phase 8.2 plan's Stage 1c for the scoping
rationale (Tune Parameters / Upload Custom Data are intentionally
minimal, not full features, per the spec's own "never fake a working
control" rule).

Why `POST /lab/experiments/planner` is NOT persisted like
`/lab/experiments/perception` is
------------------------------------------------------------------------
`planner/evaluation.py` was deliberately built without a result-store
(see that module's own docstring: "no dataset loader, no benchmark-run
persistence layer... yet"), and `POST /api/v1/planner/evaluate`
already exposes it as a synchronous, ephemeral comparison. Adding a
whole persistence layer here just so a planner comparison could appear
in `GET /lab/experiments` would duplicate `vision_evaluation.
result_store`/`evaluation.result_store`'s machinery for a type that
was explicitly designed without one -- out of proportion with "the
smallest clean addition necessary." This route reuses the existing
comparison logic directly and returns its result the same way
`/planner/evaluate` does: live, not listed as a historical run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request

from agents.task_state import TaskStatus
from api.models.lab import (
    ExperimentListResponse,
    ExperimentSummary,
    LabStatsResponse,
    SandboxRequest,
    SandboxResponse,
)
from api.models.planner import EvaluateRequest, EvaluateResponse
from api.routes.language import _map_language_runtime_error
from api.routes.planner import evaluate_planners
from language.agent import LanguageAgent
from language.exceptions import LanguageRuntimeError
from memory.agent import MemoryAgent
from planner.factory import create_planner
from planner.state import WorldState
from schemas.task import SingleTask

logger = logging.getLogger(__name__)

router = APIRouter()

#: backend/api/routes/lab.py -> repository root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_RESULTS_DIR = _REPO_ROOT / "results"
#: Every `results/<experiment_type>/benchmark_runs/` tree this route
#: knows how to list -- both already exist as real result stores
#: (`vision_evaluation.result_store`, `evaluation.result_store`); a
#: type with no runs on disk yet (e.g. "language", gated behind
#: `RUN_LLM_BENCHMARK=true`) is shown honestly as contributing zero
#: entries, never fabricated.
_EXPERIMENT_TYPES = ("perception", "language")


def get_language_agent(request: Request) -> LanguageAgent:
    return request.app.state.language_agent


def get_memory_agent(request: Request) -> MemoryAgent:
    return request.app.state.memory_agent


def _list_experiment_runs() -> List[ExperimentSummary]:
    runs: List[ExperimentSummary] = []
    for experiment_type in _EXPERIMENT_TYPES:
        run_dir = _RESULTS_DIR / experiment_type / "benchmark_runs"
        if not run_dir.is_dir():
            continue
        for summary_path in sorted(run_dir.glob("*/summary.json")):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning(
                    "lab_api.unreadable_summary", extra={"path": str(summary_path)}
                )
                continue
            runs.append(
                ExperimentSummary(
                    run_id=summary.get("run_id", summary_path.parent.name),
                    experiment_type=experiment_type,
                    timestamp=summary.get("timestamp", ""),
                    result=summary,
                )
            )
    runs.sort(key=lambda r: r.timestamp, reverse=True)
    return runs


@router.get(
    "/experiments",
    summary="List real past experiment runs",
    description=(
        "Reads results/<type>/benchmark_runs/*/summary.json directly "
        "off disk -- the same files vision_evaluation/evaluation's "
        "result stores already write. No database, no fabricated runs."
    ),
)
def list_experiments() -> ExperimentListResponse:
    return ExperimentListResponse(experiments=_list_experiment_runs())


@router.post(
    "/experiments/perception",
    summary="Run the real perception benchmark now",
    description=(
        "Runs vision_evaluation's synthetic depth+tracking benchmark "
        "in-process (deterministic, no network/GPU cost) and persists "
        "the result via PerceptionResultStore -- the same code path "
        "`python -m vision_evaluation.run_benchmark` exercises."
    ),
)
def run_perception_experiment() -> ExperimentSummary:
    from vision_evaluation.run_benchmark import run as run_perception_benchmark

    run_dir = run_perception_benchmark()
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return ExperimentSummary(
        run_id=summary["run_id"],
        experiment_type="perception",
        timestamp=summary["timestamp"],
        result=summary,
    )


@router.post(
    "/experiments/planner",
    response_model=EvaluateResponse,
    summary="Compare planner strategies now (live, not persisted)",
    description=(
        "Thin reuse of POST /api/v1/planner/evaluate's exact logic -- "
        "see this module's docstring for why this result is not added "
        "to GET /lab/experiments."
    ),
)
def run_planner_experiment(body: EvaluateRequest) -> EvaluateResponse:
    return evaluate_planners(body)


@router.post(
    "/sandbox",
    summary="Parse and plan an instruction without touching the simulator",
    description=(
        "Composes the existing LanguageAgent.parse() and "
        "create_planner(...).plan() calls -- both already exist "
        "separately, nothing composes them into one round trip today. "
        "Always plans against WorldState.initial() (a fresh symbolic "
        "state, matching every other planner endpoint) -- this is a "
        "dry run, never dispatched to AI2-THOR."
    ),
    responses={
        422: {"description": "Unrecognized planner_type."},
        502: {"description": "The LLM provider returned an unusable response."},
        503: {"description": "The LLM provider or language service is unavailable."},
        504: {"description": "The LLM provider did not respond in time."},
    },
)
def sandbox(
    body: SandboxRequest,
    language_agent: LanguageAgent = Depends(get_language_agent),
) -> SandboxResponse:
    try:
        parsed = language_agent.parse(body.instruction)
    except LanguageRuntimeError as exc:
        logger.warning(
            "lab_api.sandbox.parse_failed", extra={"exception_type": type(exc).__name__}
        )
        raise _map_language_runtime_error(exc) from None
    if not isinstance(parsed, SingleTask):
        return SandboxResponse(
            parsed=parsed,
            plan=None,
            unsupported_reason=(
                "The sandbox only plans a single task today -- this "
                "instruction parsed as a multi-step task. Try a "
                "simpler instruction, or use it via a real mission "
                "on Mission Control."
            ),
        )
    try:
        planner = create_planner(body.planner_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"category": "invalid_planner_type", "message": str(exc)},
        ) from None
    plan = planner.plan(parsed, WorldState.initial())
    return SandboxResponse(parsed=parsed, plan=plan)


@router.get(
    "/stats",
    summary="Real aggregate Lab statistics",
    description=(
        "Pure aggregation of already-real data: experiment runs on "
        "disk, this process's task history, and stored memory count. "
        "No new storage, nothing estimated."
    ),
)
def get_lab_stats(
    memory_agent: MemoryAgent = Depends(get_memory_agent),
) -> LabStatsResponse:
    from api.routes.tasks import _store

    experiments = _list_experiment_runs()
    tasks = _store.list_all()
    finished = [
        t for t in tasks if t.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED)
    ]
    success_rate = (
        sum(1 for t in finished if t.status == TaskStatus.SUCCEEDED) / len(finished)
        if finished
        else None
    )
    total_actions = sum(t.metrics()["actions"] for t in tasks)
    memories_created = len(memory_agent.list_memories(limit=None))
    return LabStatsResponse(
        experiments_run=len(experiments),
        task_success_rate=success_rate,
        total_actions=total_actions,
        memories_created=memories_created,
        tasks_run=len(tasks),
    )
