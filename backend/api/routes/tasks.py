"""
tasks.py (backend/api/routes)

Purpose
-------
HTTP interface around the Phase 7 agent architecture
(`backend/agents/`, `backend/orchestration/orchestrator.py`).
Implements:

- `POST /api/v1/tasks`                  -- parse a text instruction and
                                            run it through the Orchestrator
                                            on a background thread.
- `GET  /api/v1/tasks`                  -- every task this process has run,
                                            newest first.
- `GET  /api/v1/tasks/{task_id}`        -- the current TaskState.
- `GET  /api/v1/tasks/{task_id}/state`  -- same as above (explicit alias
                                            -- see docstring below).
- `GET  /api/v1/tasks/{task_id}/plan`   -- the task's current Plan.
- `GET  /api/v1/tasks/{task_id}/memory` -- memories retrieved/created.
- `GET  /api/v1/tasks/{task_id}/events` -- the structured event log.
- `POST /api/v1/tasks/{task_id}/cancel` -- request cancellation.

Contains no orchestration logic of its own -- every route function's
body is "validate the request shape, delegate to `LanguageAgent`/
`Orchestrator`, translate the result to an HTTP response," mirroring
`routes/execution.py`/`routes/planner.py`'s own scope boundary.

Why `POST /tasks` backgrounds the run (202, not a synchronous 201)
------------------------------------------------------------------------
Real cancellation (`POST /{id}/cancel`) needs a background thread to
reach: if this route blocked the request thread until the task
finished, no concurrent cancel request could ever arrive in time to
matter. Mirrors `routes/execution.py::start_execution`'s identical
"return the initial state immediately, background the slow part"
pattern -- `Orchestrator.run()`'s new `on_created` callback (see that
module's docstring) hands `_TaskStore` a reference to the *same*
mutable `TaskState` object `run()` continues to mutate in place, so a
concurrent `GET /tasks/{id}` sees live progress, exactly like
`execute_plan()`'s `record` parameter already lets `routes/
execution.py` do.

`GET /{task_id}` vs. `GET /{task_id}/state`
------------------------------------------------
Both return the identical `TaskState.to_dict()` payload -- see the
original rationale (unchanged): section 7.19's route sketch lists both
without distinguishing their payloads, so this module keeps them as
two thin aliases over one `_require_task_state()` helper rather than
fabricating a second, narrower response shape for one of them.

Only one task runs at a time
----------------------------------
Exactly like `routes/execution.py::_ExecutionStore`, this router is
backed by a single shared `Simulator` -- `_TaskStore.start()` rejects
a second `POST /tasks` while one is already running with `409
task_in_progress`, the same explicit safety boundary
`_ExecutionInProgressError` already establishes one layer down.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from agents.execution_agent import ExecutionAgentWrapper
from agents.memory_agent import MemoryAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.registry import AgentRegistry
from agents.task_state import InputSource, TaskState
from agents.vision_agent import VisionAgentWrapper
from api.models.tasks import CreateTaskRequest
from language.agent import LanguageAgent
from language.exceptions import LanguageRuntimeError
from orchestration.orchestrator import Orchestrator
from planner.factory import PlannerType, create_planner
from schemas.task import MultiTask, SingleTask
from simulator.simulator import Simulator

logger = logging.getLogger(__name__)

router = APIRouter()


class _TaskAlreadyRunningError(Exception):
    def __init__(self, task_id: str) -> None:
        super().__init__(task_id)
        self.task_id = task_id


class _TaskStore:
    """
    Process-local, in-memory registry of every task this API has run --
    same rationale as `routes/execution.py::_ExecutionStore`: `TaskState`
    is storage-agnostic (a future Memory-backed persistence layer is
    section 7.18's concern, not this route's).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: Dict[str, TaskState] = {}
        self._orchestrator: Optional[Orchestrator] = None
        self._active_task_id: Optional[str] = None

    def set_orchestrator(self, orchestrator: Orchestrator) -> None:
        self._orchestrator = orchestrator

    def registry(self) -> Optional[AgentRegistry]:
        return self._orchestrator.registry if self._orchestrator is not None else None

    def start(self, task: SingleTask, input_source: InputSource) -> TaskState:
        if self._orchestrator is None:
            raise RuntimeError("_TaskStore.set_orchestrator() was never called")

        with self._lock:
            if self._active_task_id is not None:
                raise _TaskAlreadyRunningError(self._active_task_id)
            self._active_task_id = task.task_id

        created = threading.Event()
        holder: Dict[str, TaskState] = {}

        def _on_created(task_state: TaskState) -> None:
            with self._lock:
                self._states[task_state.task_id] = task_state
            holder["state"] = task_state
            created.set()

        def _run() -> None:
            try:
                self._orchestrator.run(  # type: ignore[union-attr]
                    task, input_source=input_source, on_created=_on_created
                )
            except Exception:
                logger.exception(
                    "tasks_api.background_run_failed", extra={"task_id": task.task_id}
                )
            finally:
                with self._lock:
                    if self._active_task_id == task.task_id:
                        self._active_task_id = None

        thread = threading.Thread(target=_run, daemon=True, name=f"task-{task.task_id}")
        thread.start()
        # Bounded wait for `on_created` -- fires as soon as the
        # `TaskState` object exists, before any memory/planner/
        # simulator I/O, so this is expected to return in well under
        # the timeout; the timeout exists only so a genuine bug in
        # `Orchestrator.run()` can't hang this request forever.
        created.wait(timeout=5.0)
        state = holder.get("state")
        if state is None:
            raise RuntimeError(f"Task {task.task_id!r} did not start in time.")
        return state

    def get(self, task_id: str) -> Optional[TaskState]:
        with self._lock:
            return self._states.get(task_id)

    def list_all(self) -> List[TaskState]:
        # `dict` preserves insertion order (Python 3.7+), and
        # `_on_created` is this store's only writer, so reversing that
        # order is newest-first without needing a separate timestamp
        # field on `TaskState`.
        with self._lock:
            return list(reversed(list(self._states.values())))

    def get_events(self, task_id: str) -> list:
        if self._orchestrator is None:
            return []
        return self._orchestrator.events.get_events(task_id)

    def cancel(self, task_id: str) -> TaskState:
        task_state = self.get(task_id)
        if task_state is None:
            raise KeyError(task_id)
        with self._lock:
            is_active = self._active_task_id == task_id
        if is_active and self._orchestrator is not None:
            self._orchestrator.cancel()
        return task_state


_store = _TaskStore()


def get_language_agent(request: Request) -> LanguageAgent:
    return request.app.state.language_agent


def get_simulator(request: Request) -> Simulator:
    """Same 503 contract as `routes/execution.py::get_simulator` -- see
    that function's docstring."""
    simulator = request.app.state.simulator
    if simulator is None:
        raise HTTPException(
            status_code=503,
            detail={
                "category": "execution_unavailable",
                "message": "No simulator is running. Start the API with "
                "VISION_ENABLE_SIMULATOR=true and a reachable AI2-THOR "
                "binary to run tasks.",
            },
        )
    return simulator


def _require_task_state(task_id: str) -> TaskState:
    task_state = _store.get(task_id)
    if task_state is None:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "task_not_found",
                "message": f"No task with id {task_id!r}.",
            },
        )
    return task_state


@router.post(
    "",
    status_code=202,
    summary="Parse a text instruction and run it through the Orchestrator",
    description=(
        "Converts a natural language instruction into a SingleTask via "
        "the existing LanguageAgent, then runs Orchestrator.run() on a "
        "background thread -- retrieve memory, plan, observe, execute, "
        "reflect, replan as needed, remember the outcome. Returns "
        "immediately with the task's initial state; poll "
        "GET /tasks/{id} for progress. MultiTask instructions are not "
        "yet supported by this route."
    ),
    responses={
        409: {"description": "Another task is already running."},
        422: {"description": "Invalid instruction, or it parsed to a MultiTask."},
        503: {"description": "No simulator is running."},
    },
)
def create_task(
    body: CreateTaskRequest,
    language_agent: LanguageAgent = Depends(get_language_agent),
    simulator: Simulator = Depends(get_simulator),
) -> dict:
    try:
        parsed = language_agent.parse(body.instruction)
    except LanguageRuntimeError as exc:
        logger.warning(
            "tasks_api.parse_failed", extra={"exception_type": type(exc).__name__}
        )
        raise HTTPException(
            status_code=502,
            detail={"category": "language_runtime_error", "message": str(exc)},
        ) from None

    if isinstance(parsed, MultiTask):
        raise HTTPException(
            status_code=422,
            detail={
                "category": "multi_task_not_supported",
                "message": "Orchestrator does not yet support MultiTask "
                "instructions -- this instruction requires multiple "
                "subtasks.",
            },
        )

    try:
        task_state = _store.start(parsed, InputSource(body.input_source))
    except _TaskAlreadyRunningError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "category": "task_in_progress",
                "message": f"Task {exc.task_id!r} is already running. Cancel it "
                "or wait for it to finish before starting another.",
            },
        ) from None
    return task_state.to_dict()


@router.get(
    "",
    summary="List every task this process has run, newest first",
    description=(
        "Returns every TaskState this process has started, most recently "
        "created first. Process-local and in-memory, same as every other "
        "route in this module -- see _TaskStore's docstring. Used by the "
        "frontend to reconstruct cross-task history (recent missions, "
        "activity feed, memory/lab statistics) without a dedicated "
        "aggregate-metrics endpoint."
    ),
)
def list_tasks() -> List[dict]:
    return [task_state.to_dict() for task_state in _store.list_all()]


@router.get(
    "/{task_id}",
    summary="Get the current TaskState for a task",
)
def get_task(task_id: str) -> dict:
    return _require_task_state(task_id).to_dict()


@router.get(
    "/{task_id}/state",
    summary="Get the current TaskState for a task (alias of GET /{task_id})",
)
def get_task_state(task_id: str) -> dict:
    return _require_task_state(task_id).to_dict()


@router.get(
    "/{task_id}/plan",
    summary="Get the current Plan for a task",
)
def get_task_plan(task_id: str) -> Optional[dict]:
    task_state = _require_task_state(task_id)
    if task_state.current_plan is None:
        return None
    return task_state.current_plan.model_dump(mode="json")


@router.get(
    "/{task_id}/memory",
    summary="Get memories retrieved and created for a task",
)
def get_task_memory(task_id: str) -> Dict[str, List[Dict[str, Any]]]:
    task_state = _require_task_state(task_id)
    return {
        "retrieved": task_state.retrieved_memories,
        "created": task_state.created_memories,
    }


@router.get(
    "/{task_id}/events",
    summary="Get the structured event log for a task",
)
def get_task_events(task_id: str) -> List[dict]:
    _require_task_state(task_id)  # 404s for an unknown task_id
    return [event.model_dump(mode="json") for event in _store.get_events(task_id)]


@router.post(
    "/{task_id}/cancel",
    summary="Request cancellation of a running task",
    description=(
        "Requests cancellation; takes effect at the next safe boundary "
        "(an in-flight simulator action is not interrupted mid-call). "
        "Safe to call on a task that has already finished -- a no-op "
        "then. Never writes a memory for the cancelled attempt."
    ),
)
def cancel_task(task_id: str) -> dict:
    try:
        task_state = _store.cancel(task_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "task_not_found",
                "message": f"No task with id {task_id!r}.",
            },
        ) from None
    return task_state.to_dict()


def build_orchestrator(
    simulator: Simulator,
    memory_agent: Optional[MemoryAgentWrapper] = None,
    vision_agent: Optional[VisionAgentWrapper] = None,
) -> Orchestrator:
    """
    Called once from `api/app.py`'s lifespan to wire this route's
    `_TaskStore` to a real `Orchestrator` -- kept as a free function
    (not inlined in `_lifespan`) so `test_api_tasks.py` can call it
    against a `FakeSimulator` directly, exactly like `routes/
    execution.py`'s tests override `get_simulator`. Always constructs
    and passes an `AgentRegistry` (Session 1 accepted one but never
    supplied it -- `GET /agents` needs a real one to read from).
    """
    registry = AgentRegistry()
    orchestrator = Orchestrator(
        PlannerAgentWrapper(create_planner(PlannerType.RULE_BASED)),
        ExecutionAgentWrapper(simulator),
        memory_agent=memory_agent,
        vision_agent=vision_agent,
        registry=registry,
    )
    _store.set_orchestrator(orchestrator)
    return orchestrator
