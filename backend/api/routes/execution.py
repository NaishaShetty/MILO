"""
execution.py (backend/api/routes)

Purpose
-------
HTTP interface around the Phase 5 Execution subsystem (`backend/execution/`).
Implements section 15's endpoints:

- `POST /api/v1/execution/start`           -- begin executing a validated
                                               Plan (typically
                                               `PlanningResult.plan` from
                                               `POST /api/v1/planner/plan`).
- `GET  /api/v1/execution/{execution_id}`         -- current ExecutionRecord.
- `POST /api/v1/execution/{execution_id}/cancel`  -- request cancellation.
- `GET  /api/v1/execution/{execution_id}/steps`   -- per-step results.
- `GET  /api/v1/execution/{execution_id}/events`  -- the structured event log.

Contains no execution logic of its own -- every route function's body
is "validate the request shape, delegate to `execution.controller.
ExecutionController`, translate the result to an HTTP response,"
mirroring `routes/planner.py`'s own scope boundary.

Why `start` runs the plan on a background thread
------------------------------------------------------
`ExecutionController.execute_plan()` is a blocking, potentially
multi-second-to-multi-minute call (it drives real AI2-THOR actions one
at a time). Running it synchronously inside the request handler would
make `POST /start` itself hang for the whole plan and make `POST
/{id}/cancel` unreachable until the plan had already finished -- section
10's "a plan must be cancellable" would be unsatisfiable. Instead,
`start_execution()` calls `ExecutionController.load_plan()` synchronously
(fast, no simulator I/O) to obtain an `execution_id` immediately, stores
the resulting `ExecutionRecord` in this module's in-memory store, and
runs `execute_plan()` on a daemon `threading.Thread` against that exact
same record object -- a concurrent `GET /{execution_id}` therefore
always sees live progress, and `POST /{execution_id}/cancel` reaches the
running `ExecutionController.cancel()` while it is still executing.
This mirrors the same "don't introduce unsafe asynchronous complexity
unless the architecture requires it" principle the Phase 5 spec calls
out -- a single `threading.Thread`, no new async framework, no task
queue.

Why only one execution runs at a time
------------------------------------------
`Simulator` owns exactly one AI2-THOR/Unity subprocess (see
`simulator/simulator.py`); two concurrent `ExecutionController`s driving
it at once would race on the same controller and produce undefined
behavior. `_ExecutionStore.start()` below rejects a second `start`
while one is already `RUNNING`/`PENDING` with `409 execution_in_progress`
-- a small, explicit safety boundary rather than a silent race.

Why this reuses `routes/vision.py`'s simulator-availability pattern
------------------------------------------------------------------------
Exactly like the Vision API, this router requires
`app.state.simulator` to be a running `Simulator` (set only when
`VISION_ENABLE_SIMULATOR=true` -- see `api/app.py`'s docstring) and
returns a clean `503 execution_unavailable`, never a crash, when it is
not. Execution has no code path that fabricates progress against a
simulator that is not actually running.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from api.models.execution import StartExecutionRequest
from execution.controller import ExecutionController
from execution.exceptions import PlanNotExecutableError
from execution.models import ExecutionEvent, ExecutionRecord, StepExecutionRecord
from planner.models import Plan
from planner.state import WorldState
from simulator.simulator import Simulator

logger = logging.getLogger(__name__)

router = APIRouter()


class _ExecutionStore:
    """
    Process-local, in-memory registry of every execution this API has
    started -- deliberately not backed by a database (see
    `execution/__init__.py`'s docstring on `ExecutionRecord` being
    storage-agnostic; a future Phase 6 Memory Agent owns persistence).
    Guards `start()` with a lock so at most one execution can be
    `RUNNING`/`PENDING` against the single shared `Simulator` at a time.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, ExecutionRecord] = {}
        self._controllers: Dict[str, ExecutionController] = {}
        self._active_execution_id: Optional[str] = None

    def start(
        self, simulator: Simulator, body: StartExecutionRequest
    ) -> ExecutionRecord:
        with self._lock:
            if self._active_execution_id is not None:
                raise _ExecutionInProgressError(self._active_execution_id)

            controller = ExecutionController(
                simulator,
                max_step_retries=body.max_step_retries,
                step_timeout_s=body.step_timeout_s,
            )
            record = controller.load_plan(body.plan)
            self._records[record.execution_id] = record
            self._controllers[record.execution_id] = controller
            self._active_execution_id = record.execution_id

        thread = threading.Thread(
            target=self._run,
            args=(controller, body.plan, record),
            daemon=True,
            name=f"execution-{record.execution_id}",
        )
        thread.start()
        return record

    def _run(
        self, controller: ExecutionController, plan: Plan, record: ExecutionRecord
    ) -> None:
        try:
            controller.execute_plan(plan, WorldState.initial(), record=record)
        except Exception:
            logger.exception(
                "execution_api.background_run_failed",
                extra={"execution_id": record.execution_id},
            )
        finally:
            with self._lock:
                if self._active_execution_id == record.execution_id:
                    self._active_execution_id = None

    def get(self, execution_id: str) -> Optional[ExecutionRecord]:
        return self._records.get(execution_id)

    def get_controller(self, execution_id: str) -> Optional[ExecutionController]:
        return self._controllers.get(execution_id)


class _ExecutionInProgressError(Exception):
    def __init__(self, execution_id: str) -> None:
        super().__init__(execution_id)
        self.execution_id = execution_id


_store = _ExecutionStore()


def get_simulator(request: Request) -> Simulator:
    """FastAPI dependency returning the `Simulator` constructed at
    application startup (`api/app.py`'s `_lifespan`, the same instance
    `routes/vision.py::get_vision_system` is built from). Raises 503 if
    no simulator is running. A dependency function (rather than reading
    `request.app.state` inline) keeps this route testable via
    `app.dependency_overrides`, exactly like
    `routes/vision.py::get_vision_system`."""
    simulator = request.app.state.simulator
    if simulator is None:
        raise HTTPException(
            status_code=503,
            detail={
                "category": "execution_unavailable",
                "message": "No simulator is running. Start the API with "
                "VISION_ENABLE_SIMULATOR=true and a reachable AI2-THOR "
                "binary to execute plans.",
            },
        )
    return simulator


def _require_record(execution_id: str) -> ExecutionRecord:
    record = _store.get(execution_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "execution_not_found",
                "message": f"No execution with id {execution_id!r}.",
            },
        )
    return record


@router.post(
    "/start",
    response_model=ExecutionRecord,
    status_code=202,
    summary="Begin executing a validated Plan",
    description=(
        "Starts executing plan.steps sequentially against the running "
        "simulator on a background thread and returns immediately with "
        "the initial (PENDING/RUNNING) ExecutionRecord -- poll "
        "GET /{execution_id} for progress. Never calls AI2-THOR directly; "
        "delegates entirely to execution.controller.ExecutionController."
    ),
    responses={
        503: {"description": "No simulator is running."},
        409: {"description": "Another execution is already in progress."},
        422: {"description": "The plan is INVALID or has no steps."},
    },
)
def start_execution(
    body: StartExecutionRequest, simulator: Simulator = Depends(get_simulator)
) -> ExecutionRecord:
    try:
        return _store.start(simulator, body)
    except _ExecutionInProgressError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "category": "execution_in_progress",
                "message": f"Execution {exc.execution_id!r} is already running. "
                "Cancel it or wait for it to finish before starting another.",
            },
        ) from None
    except PlanNotExecutableError as exc:
        raise HTTPException(
            status_code=422,
            detail={"category": "plan_not_executable", "message": str(exc)},
        ) from None


@router.get(
    "/{execution_id}",
    response_model=ExecutionRecord,
    summary="Get the current state of an execution",
)
def get_execution(execution_id: str) -> ExecutionRecord:
    return _require_record(execution_id)


@router.post(
    "/{execution_id}/cancel",
    response_model=ExecutionRecord,
    summary="Request cancellation of a running execution",
    description=(
        "Sets the cancellation flag; takes effect at the next step "
        "boundary (an in-flight simulator call is not interrupted "
        "mid-call). Safe to call on an execution that has already "
        "finished -- it is then a no-op."
    ),
)
def cancel_execution(execution_id: str) -> ExecutionRecord:
    record = _require_record(execution_id)
    controller = _store.get_controller(execution_id)
    if controller is not None:
        controller.cancel()
    return record


@router.get(
    "/{execution_id}/steps",
    response_model=List[StepExecutionRecord],
    summary="Get per-step results for an execution",
)
def get_execution_steps(execution_id: str) -> List[StepExecutionRecord]:
    return _require_record(execution_id).step_results


@router.get(
    "/{execution_id}/events",
    response_model=List[ExecutionEvent],
    summary="Get the structured execution event log",
)
def get_execution_events(execution_id: str) -> List[ExecutionEvent]:
    return _require_record(execution_id).events
