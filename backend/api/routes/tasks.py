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
from typing import Any, Dict, Iterator, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.execution_agent import ExecutionAgentWrapper
from agents.memory_agent import MemoryAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.registry import AgentRegistry
from agents.task_state import InputSource, TaskState
from agents.vision_agent import VisionAgentWrapper
from api.models.tasks import CreateTaskRequest
from language.agent import LanguageAgent
from language.exceptions import LanguageRuntimeError
from language.interpreter import InstructionInterpreter, Interpretation
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
            active = self._active_task_id
            # A task whose state is already final is done even if its thread is
            # still writing its trace: don't turn the next request away.
            done = (
                active is not None
                and self._states.get(active) is not None
                and (
                    self._states[active].status.value
                    in ("succeeded", "failed", "cancelled")
                )
            )
            if active is not None and not done:
                raise _TaskAlreadyRunningError(active)
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
    planner_name: str = body.planner
    if _is_novel(interpretation, body.instruction, _safe_metadata(simulator)):
        # Something MILO has no recipe for: work it out (novel/), instead of
        # "I don't know how to X yet".
        interpretation = Interpretation(
            kind="task",
            task=SingleTask(goal="novel", estimated_goal=body.instruction.strip()),
            understood_as="I don't know this yet, let me work it out",
            source="novel",
        )
        planner_name = "novel"

    metadata = _safe_metadata(simulator)
    if interpretation.kind == "task" and isinstance(interpretation.task, SingleTask):
        from oversight.ambiguity import which_one

        if body.object_id:
            known = {o.get("objectId") for o in (metadata or {}).get("objects") or []}
            if metadata is not None and body.object_id not in known:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "category": "unknown_object",
                        "message": "I can't see that one any more. Ask me again?",
                    },
                )
            interpretation.task.object = body.object_id
        elif interpretation.task.goal != "novel":
            question = which_one(interpretation.task, body.instruction, metadata)
            if question is not None:
                response.status_code = 200
                return question

    if interpretation.kind == "task":
        assert interpretation.task is not None
        try:
            task_state = _store.start(
                interpretation.task, InputSource(body.input_source), planner_name
            )
            task_state.instruction = body.instruction.strip()
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

    # "clarify" / "unsupported": a plain question or reason, shown as-is --
    # with tappable answers when MILO can list them ("where should it go?").
    reply: Dict[str, Any] = {
        "kind": interpretation.kind,
        "message": interpretation.message,
        "details": interpretation.details,
    }
    details = interpretation.details or {}
    if interpretation.kind == "clarify" and details.get("slot") == "target":
        from oversight.ambiguity import where_to

        obj = details.get("object")
        if obj:
            reply["choices"] = where_to(str(obj), metadata)
    return reply


def _safe_metadata(simulator: Any) -> Any:
    try:
        return simulator.get_metadata()
    except Exception:
        return None


def _skill_matches(instruction: str, metadata: Any) -> bool:
    """True when the instruction has the wording of a saved (not disabled) skill."""
    from novel.factory import shared_library

    names = [
        str(o.get("objectType", "")).lower()
        for o in (metadata or {}).get("objects") or []
    ]
    try:
        return shared_library().find(instruction, names) is not None
    except Exception:
        return False


def _is_novel(interpretation: Any, instruction: str = "", metadata: Any = None) -> bool:
    """An unknown verb, or a model-parsed goal no planner has a recipe for -- and a
    language model is available to work it out (offline, the plain "I can't do that
    yet" reply stays, since a novel run could only fail)."""
    from novel.factory import enabled
    from novel.providers import OfflineProvider, build_provider
    from planner.rule_based import GOAL_HANDLERS
    from planner.task_library import COMPOSITE_GOALS

    if not enabled():
        return False
    if instruction and _skill_matches(instruction, metadata):
        return True  # something the user taught MILO (works without a model)
    task = interpretation.task if interpretation.kind == "task" else None
    unknown_goal = isinstance(task, SingleTask) and (task.goal or "") not in (
        set(GOAL_HANDLERS) | set(COMPOSITE_GOALS)
    )
    if interpretation.kind != "unsupported" and not unknown_goal:
        return False
    return not isinstance(build_provider(), OfflineProvider)


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


class _Decide(BaseModel):
    choice: Literal["approve", "skip", "cancel"]
    steps: Optional[List[Dict[str, Any]]] = None


@router.post("/{task_id}/decision", summary="Answer what MILO is waiting for")
def decide(task_id: str, body: _Decide) -> dict:
    from oversight.gate import Decision

    state = _require_task_state(task_id)
    gate = getattr(_store._orchestrator, "_gate", None)
    if gate is None or not gate.decide(task_id, Decision(body.choice, body.steps)):
        raise HTTPException(
            status_code=409,
            detail={
                "category": "not_waiting",
                "message": "I'm not waiting for an answer on that one.",
            },
        )
    return state.to_dict()


def _undo_plan(state: TaskState):
    from oversight.undo import inverse_plan

    return inverse_plan(state.undo_log)


@router.get("/{task_id}/undo", summary="What undoing this mission would do")
def undo_preview(task_id: str) -> dict:
    state = _require_task_state(task_id)
    steps, cannot, _ = _undo_plan(state)
    return {"steps": steps, "cannot_undo": cannot, "possible": bool(steps)}


@router.post("/{task_id}/undo", status_code=202, summary="Undo a finished mission")
def undo(task_id: str) -> dict:
    state = _require_task_state(task_id)
    if state.status.value not in _TERMINAL:
        raise HTTPException(
            status_code=409,
            detail={
                "category": "still_running",
                "message": "Let me finish (or stop me) first.",
            },
        )
    steps, cannot, success = _undo_plan(state)
    if not steps:
        raise HTTPException(
            status_code=400,
            detail={
                "category": "nothing_to_undo",
                "message": "There's nothing I can undo there.",
            },
        )
    key = f"undo:{task_id}"
    _FIXED.pending[key] = (steps, success)
    try:
        new = _store.start(
            SingleTask(goal="undo", estimated_goal=key), InputSource.TEXT, "fixed"
        )
    except _TaskAlreadyRunningError:
        raise HTTPException(
            status_code=409,
            detail={
                "category": "task_in_progress",
                "message": "I'm busy with another job.",
            },
        ) from None
    new.instruction = f"undo: {state.instruction or state.user_request}"
    return {**new.to_dict(), "cannot_undo": cannot}


class _Correct(BaseModel):
    object_id: Optional[str] = None


@router.post(
    "/{task_id}/correct",
    status_code=202,
    summary='"No, the other one": redo with another object',
)
def correct(
    task_id: str, body: _Correct, simulator: Simulator = Depends(get_simulator)
) -> dict:
    from oversight.ambiguity import same_kind

    state = _require_task_state(task_id)
    if not state.instruction or not state.objects:
        raise HTTPException(
            status_code=400,
            detail={
                "category": "cannot_correct",
                "message": "Tell me again what you'd like instead.",
            },
        )
    meta = _safe_metadata(simulator) or {}
    current = state.objects[0]
    choices = [o.get("objectId") for o in same_kind(current, meta)]
    pinned = current if "|" in current else (choices[0] if choices else None)
    target = body.object_id or next((c for c in choices if c != pinned), None)
    if target is None:
        raise HTTPException(
            status_code=400,
            detail={"category": "no_other", "message": "I can only see one of those."},
        )
    if state.status.value not in _TERMINAL:
        _store.cancel(task_id)
        end = time.time() + 5.0
        while state.status.value not in _TERMINAL and time.time() < end:
            time.sleep(0.02)
    task = SingleTask(goal=state.goal, object=target, target=state.target)
    try:
        new = _store.start(
            task,
            state.input_source,
            (
                state.planner
                if state.planner in ("rule_based", "react", "behavior_tree", "htn")
                else None
            ),
        )
    except _TaskAlreadyRunningError:
        raise HTTPException(
            status_code=409,
            detail={
                "category": "task_in_progress",
                "message": "I'm still stopping the last one.",
            },
        ) from None
    new.instruction = state.instruction
    return new.to_dict()


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


from oversight.undo import FixedPlanner  # noqa: E402

_FIXED = FixedPlanner()


def _build_gate() -> Any:
    """`MILO_APPROVALS=0` turns approvals off; `MILO_APPROVAL_TIMEOUT` (s) is how long
    MILO waits before skipping a risky step / dropping a plan (default 300)."""
    if os.environ.get("MILO_APPROVALS", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return None
    from oversight.gate import ApprovalGate

    try:
        timeout = float(os.environ.get("MILO_APPROVAL_TIMEOUT", "300"))
    except ValueError:
        timeout = 300.0
    return ApprovalGate(timeout_s=timeout)


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

    novel: Dict[str, Any] = {}

    def planner_for(name: str) -> PlannerAgentWrapper:
        if name == "fixed":
            return PlannerAgentWrapper(_FIXED)  # type: ignore[arg-type]
        if name == "novel":
            # "Figure it out": built once, keeps its skill library and budgets.
            if "planner" not in novel:
                from novel.factory import build_novel_planner

                novel["planner"] = build_novel_planner(
                    execution,
                    memory_agent=memory_agent,
                    failure_source=lambda: [
                        f.message
                        for f in (
                            orchestrator._current_state.failures
                            if orchestrator._current_state is not None
                            else []
                        )
                    ][-3:],
                )
            return PlannerAgentWrapper(novel["planner"])  # type: ignore[arg-type]
        # `react` uses the configured language model when there is one and
        # falls back to the rule-based planner when there isn't (it says
        # so on the task as `planner_note`).
        return PlannerAgentWrapper(create_planner(name, llm_client=llm_client))

    from tracelog.recorder import build_recorder

    execution = ExecutionAgentWrapper(
        simulator, step_timeout_s=_step_timeout_from_env()
    )
    orchestrator = Orchestrator(
        PlannerAgentWrapper(create_planner(PlannerType.RULE_BASED)),
        execution,
        memory_agent=memory_agent,
        vision_agent=vision_agent,
        registry=registry,
        planner_factory=planner_for,
        trace_recorder=build_recorder(
            frame_source=execution.get_frame,
            pose_source=lambda: (execution.get_metadata() or {}).get("agent"),
        ),
        approval_gate=_build_gate(),
        **learning_kwargs(),
    )
    _store.set_orchestrator(orchestrator)
    return orchestrator
