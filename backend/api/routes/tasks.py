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

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from agents.execution_agent import ExecutionAgentWrapper
from agents.memory_agent import MemoryAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.registry import AgentRegistry
from agents.task_state import InputSource, TaskState
from agents.vision_agent import VisionAgentWrapper
from api.models.tasks import CreateTaskRequest
from language.agent import LanguageAgent
from language.exceptions import LanguageRuntimeError
from language.interpreter import InstructionInterpreter
from language.llm_client import LLMClient
from learning.config import learning_kwargs
from memory.habits import usual_place_of
from memory.models import MemoryType
from orchestration.answerer import QuestionAnswerer
from orchestration.orchestrator import Orchestrator
from planner.factory import PlannerType, create_planner
from planner.task_library import library_as_dicts
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

    def start(
        self,
        task: Union[SingleTask, MultiTask],
        input_source: InputSource,
        planner_type: Optional[str] = None,
    ) -> TaskState:
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
                    task,
                    input_source=input_source,
                    on_created=_on_created,
                    planner_type=planner_type,
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
                "message": "MILO's practice room (the simulator) isn't running, "
                "so I can't do jobs right now. Start the server with "
                "VISION_ENABLE_SIMULATOR=true and try again.",
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
                "message": "I don't have a job with that id. It may be from "
                "before I last restarted.",
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
    request: Request,
    response: Response,
    body: CreateTaskRequest,
    language_agent: LanguageAgent = Depends(get_language_agent),
    simulator: Simulator = Depends(get_simulator),
) -> dict:
    memory_agent = getattr(request.app.state, "memory_agent", None)

    def _memories():
        if memory_agent is None:
            return []
        return memory_agent.list_memories(
            memory_type=MemoryType.USER
        ) + memory_agent.list_memories(memory_type=MemoryType.SEMANTIC)

    def _usual_place(name: str):
        return usual_place_of(_memories(), name)

    def _parse_with_model(text: str):
        try:
            return language_agent.parse(text)
        except LanguageRuntimeError as exc:
            logger.warning(
                "tasks_api.parse_failed", extra={"exception_type": type(exc).__name__}
            )
            return None

    from learning.parser.serving import build_learned_parser

    interpreter = InstructionInterpreter(
        fallback=_parse_with_model,
        usual_place=_usual_place,
        learned=build_learned_parser(),
    )
    interpretation = interpreter.interpret(body.instruction)

    if interpretation.kind == "task":
        assert interpretation.task is not None
        try:
            task_state = _store.start(
                interpretation.task, InputSource(body.input_source), body.planner
            )
        except _TaskAlreadyRunningError:
            raise HTTPException(
                status_code=409,
                detail={
                    "category": "task_in_progress",
                    "message": "I'm still working on another job. Stop it or wait "
                    "for it to finish, then ask me again.",
                },
            ) from None
        return {
            **task_state.to_dict(),
            "kind": "task",
            "understood_as": interpretation.understood_as,
        }

    # Everything below is a reply, not a started job: 200, not 202.
    response.status_code = 200

    if interpretation.kind == "question":
        assert interpretation.question is not None

        def _recall(name: str):
            return _usual_place(name)

        answer = QuestionAnswerer(simulator.get_metadata, _recall).answer(
            interpretation.question
        )
        return {
            "kind": "answer",
            "answer": answer,
            "understood_as": interpretation.understood_as,
        }

    if interpretation.kind == "preference":
        assert interpretation.preference is not None
        pref = interpretation.preference
        remembered = False
        if memory_agent is not None:
            remembered = (
                memory_agent.remember_preference(pref.object, pref.relation, pref.place)
                is not None
            )
        message = interpretation.message
        if not remembered:
            message = (
                "I understood, but my memory isn't available right now, so I "
                "can't keep that. Try again once memory is on."
            )
        return {
            "kind": "remembered" if remembered else "not_remembered",
            "message": message,
            "understood_as": interpretation.understood_as,
        }

    if interpretation.kind == "help":
        return {
            "kind": "answer",
            "answer": interpretation.message,
            "library": library_as_dicts(),
        }

    # "clarify" / "unsupported": a plain question or reason, shown as-is.
    return {
        "kind": interpretation.kind,
        "message": interpretation.message,
        "details": interpretation.details,
    }


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


_TERMINAL = ("succeeded", "failed", "cancelled")
#: How often a stream re-checks the task. This is the *server* watching
#: in-process state (cheap); the browser just receives pushes.
_STREAM_TICK_S = 0.2
_STREAM_KEEPALIVE_S = 15.0


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _task_summary(task_state: TaskState) -> dict:
    return {
        "task_id": task_state.task_id,
        "user_request": task_state.user_request,
        "goal": task_state.goal,
        "status": task_state.status.value,
        "planner": task_state.planner,
        "current_step": task_state.current_step,
        "answer": task_state.answer,
        "cancel_requested": task_state.cancel_requested,
        "success": task_state.metrics()["success"],
        "created_at": task_state.created_at,
        "steps": len(task_state.current_plan.steps) if task_state.current_plan else 0,
        "completed_steps": len(task_state.completed_steps),
        "memories_used": len(task_state.retrieved_memories),
        "replans": task_state.metrics()["replans"],
        "total_ms": task_state.latencies_ms.get("total_ms"),
    }


@router.get(
    "/stream",
    summary="Live feed of every task (server-sent events)",
    description=(
        "A `text/event-stream`. Sends a `snapshot` event (a newest-first "
        "list of task summaries) immediately and again whenever any task "
        "changes. Powers the Play page's recent missions and helper "
        "status without polling. Clients should fall back to "
        "`GET /api/v1/tasks` if the stream fails. `?once=true` sends one "
        "snapshot and closes (handy for a quick check)."
    ),
)
def stream_all_tasks(once: bool = False) -> StreamingResponse:
    def generate() -> Iterator[str]:
        yield "retry: 3000\n\n"
        last: Optional[str] = None
        quiet = 0.0
        while True:
            snapshot = [_task_summary(s) for s in _store.list_all()]
            payload = json.dumps(snapshot, default=str)
            if payload != last:
                last = payload
                quiet = 0.0
                yield _sse("snapshot", snapshot)
                if once:
                    return
            elif quiet >= _STREAM_KEEPALIVE_S:
                quiet = 0.0
                yield ": keepalive\n\n"
            time.sleep(_STREAM_TICK_S)
            quiet += _STREAM_TICK_S

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Tell nginx-style proxies not to buffer the stream.
    "X-Accel-Buffering": "no",
}


@router.get(
    "/library",
    summary="Everything MILO knows how to do",
    description=(
        "The task library: one entry per kind of job (fetch, deliver, put, "
        "open/close, turn on/off, find, clear a table, tidy up, answer a "
        "question), each with a plain-language title, summary and example "
        'phrasings. Drives the UI\'s "What can MILO do?" list.'
    ),
)
def get_task_library() -> List[dict]:
    return library_as_dicts()


@router.get(
    "/{task_id}",
    summary="Get the current TaskState for a task",
)
def get_task(task_id: str) -> dict:
    return _require_task_state(task_id).to_dict()


@router.get(
    "/{task_id}/stream",
    summary="Live feed of one task's state and events (server-sent events)",
    description=(
        "A `text/event-stream` for one task: a `state` event (the full "
        "TaskState) immediately and whenever it changes, a `task_event` "
        "for each new orchestrator event, and a final `end` event once "
        "the task has succeeded, failed or been cancelled. Replaces "
        "polling `GET /tasks/{id}`; clients should fall back to polling "
        "if the stream fails."
    ),
    responses={404: {"description": "No task with that id."}},
)
def stream_task(task_id: str) -> StreamingResponse:
    _require_task_state(task_id)  # 404 before the stream opens

    def generate() -> Iterator[str]:
        yield "retry: 3000\n\n"
        last_state: Optional[str] = None
        sent_events = 0
        quiet = 0.0
        while True:
            task_state = _store.get(task_id)
            if task_state is None:
                yield _sse("end", {"reason": "gone"})
                return
            changed = False
            payload = json.dumps(task_state.to_dict(), default=str)
            if payload != last_state:
                last_state = payload
                changed = True
                yield f"event: state\ndata: {payload}\n\n"
            events = _store.get_events(task_id)
            for event in events[sent_events:]:
                changed = True
                yield _sse("task_event", event.model_dump(mode="json"))
            sent_events = len(events)
            if task_state.status.value in _TERMINAL:
                yield _sse("end", {"status": task_state.status.value})
                return
            quiet = 0.0 if changed else quiet + _STREAM_TICK_S
            if quiet >= _STREAM_KEEPALIVE_S:
                quiet = 0.0
                yield ": keepalive\n\n"
            time.sleep(_STREAM_TICK_S)

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


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
    "/{task_id}/robot",
    summary="Get the current simulator/robot state (position, rotation, held object, visible objects)",
    description=(
        "Curated view of AI2-THOR's raw metadata (Simulator.get_metadata()) "
        "for the shared simulator this task ran/is running on -- agent "
        "position/rotation/camera tilt, the currently held object (if "
        "any), and which known objects are presently visible. Note this "
        "reads the *current* simulator state, not a snapshot from when "
        "this task last acted -- if another task has since moved the "
        "robot, this reflects that. 503s under the same "
        "'no simulator running' contract as POST /tasks."
    ),
    responses={503: {"description": "No simulator is running."}},
)
def get_task_robot_state(
    task_id: str, simulator: Simulator = Depends(get_simulator)
) -> Dict[str, Any]:
    _require_task_state(task_id)  # 404s for an unknown task_id
    metadata = simulator.get_metadata()
    agent = metadata.get("agent") or {}
    objects = metadata.get("objects") or []
    held = next((obj for obj in objects if obj.get("isPickedUp")), None)
    visible = [
        {
            "object_id": obj.get("objectId"),
            "object_type": obj.get("objectType"),
            "position": obj.get("position"),
            "distance": obj.get("distance"),
        }
        for obj in objects
        if obj.get("visible")
    ]
    return {
        "position": agent.get("position"),
        "rotation": agent.get("rotation"),
        "camera_horizon": agent.get("cameraHorizon"),
        "held_object": (
            {
                "object_id": held.get("objectId"),
                "object_type": held.get("objectType"),
            }
            if held is not None
            else None
        ),
        "visible_objects": visible,
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
    summary="Stop a running task",
    description=(
        "Stops the task between steps (an in-flight simulator action is "
        "not interrupted mid-call) and leaves a clean state: whatever the "
        "robot was holding is put down. `cancel_requested` is true on the "
        "task immediately; once it stops, `status` is `cancelled` and "
        "`cancel_summary` says what was tidied up. Safe to call on a task "
        "that has already finished -- a no-op then. Never writes a memory "
        "for the cancelled attempt."
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
                "message": "I don't have a job with that id. It may be from "
                "before I last restarted.",
            },
        ) from None
    return task_state.to_dict()


def _step_timeout_from_env() -> Optional[float]:
    raw = os.environ.get("EXECUTION_STEP_TIMEOUT_S", "").strip()
    try:
        value = float(raw) if raw else 0.0
    except ValueError:
        return None
    return value if value > 0 else None


def current_orchestrator() -> Optional[Orchestrator]:
    """The orchestrator the task routes use (for the Lab's Models panel)."""
    return _store._orchestrator


def build_orchestrator(
    simulator: Simulator,
    memory_agent: Optional[MemoryAgentWrapper] = None,
    vision_agent: Optional[VisionAgentWrapper] = None,
    llm_client: Optional[LLMClient] = None,
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

    def planner_for(name: str) -> PlannerAgentWrapper:
        # `react` uses the configured language model when there is one and
        # falls back to the rule-based planner when there isn't (it says
        # so on the task as `planner_note`).
        return PlannerAgentWrapper(create_planner(name, llm_client=llm_client))

    orchestrator = Orchestrator(
        PlannerAgentWrapper(create_planner(PlannerType.RULE_BASED)),
        ExecutionAgentWrapper(simulator, step_timeout_s=_step_timeout_from_env()),
        memory_agent=memory_agent,
        vision_agent=vision_agent,
        registry=registry,
        planner_factory=planner_for,
        **learning_kwargs(),
    )
    _store.set_orchestrator(orchestrator)
    return orchestrator
