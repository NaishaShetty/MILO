"""
orchestrator.py (backend/orchestration)

Purpose
-------
`Orchestrator` -- section 7.16's unified orchestration layer: the
`CREATE -> PARSE -> RETRIEVE MEMORY -> PLAN -> OBSERVE -> EXECUTE ->
CHECK -> REFLECT -> SUCCESS|REPLAN` lifecycle, driven over one
`agents.task_state.TaskState`, publishing `agents.events.Event`s at
every transition, and closing the loop this phase's `ReflectionAgent`/
`NavigationAgent` (both new this phase) make possible: dynamic
replanning that preserves whatever a failed attempt already
accomplished, instead of restarting the task from scratch.

Relationship to `orchestration.task_runner.TaskRunner`
------------------------------------------------------------
`TaskRunner` (Phase 6.3) already closes a *single-attempt* loop --
retrieve memory once, plan once, execute once, remember once -- and
stays exactly as it is: every existing caller/test of `TaskRunner`
keeps working unchanged, and this module does not import or modify it.
`Orchestrator` is a new, parallel entry point for a *multi-attempt*
loop: it composes the same kinds of collaborators (`PlannerAgentWrapper`
wrapping a `Planner`, `ExecutionAgentWrapper` wrapping
`ExecutionController`, `MemoryAgentWrapper` wrapping `MemoryAgent`) but
adds the two things `TaskRunner` deliberately does not attempt
(`execution/controller.py`'s own docstring: "never create an infinite
retry loop" is about bounded per-*action* retry only; `execution/
errors.py`: `ExecutionError.recoverable` is "exposed purely as data
for a future consumer to act on" -- this module is that consumer):
`NavigationAgent`/`ReflectionAgent`-driven diagnosis of *why* a plan
failed, and a bounded (`max_replans`) reflect -> replan -> continue
loop that reuses the same mutated `WorldState` across attempts so
whatever effects a partially-successful plan already produced (e.g.
the robot's `robot_location`/`robot_holding`) carry forward into the
next plan, rather than a full restart.

Why `retry` re-executes the same `Plan` but `replan` calls the planner
again
------------------------------------------------------------------------
`ReflectionAgent.reflect()`'s `"retry"` verdict means "this looked
transient -- the same plan might succeed against the same objects a
second time" (e.g. a flaky dispatch); `"replan"` means "the plan
itself needs to change" (e.g. `PATH_BLOCKED` -- the same route will
just fail again). Conflating the two into one "try again" branch would
either re-plan unnecessarily on a transient hiccup, or waste an
attempt re-running a plan reflection already judged unlikely to work
a second time -- see `reflection_agent.py`'s own rule-by-rule
docstring for why each verdict means what it means.

Memory formation policy for this loop
------------------------------------------
Deliberately smaller than `TaskRunner`'s (no observation-forming, no
failure-recovery linking -- both remain available via `TaskRunner`
for direct single-attempt callers that want them): exactly one memory
write per *task* (never per attempt, matching `TaskRunner`'s own
"avoid memory pollution" policy), gated by `ReflectionResult.
store_memory` -- `True` only for the two terminal outcomes
(`continue`/`abort`), never for an intermediate `retry`/`replan`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Callable, List, Optional

from agents.events import Event, EventBus, EventType
from agents.execution_agent import ExecutionAgentWrapper
from agents.failures import AgentFailure
from agents.memory_agent import MemoryAgentWrapper
from agents.navigation_agent import NavigationAgent
from agents.planner_agent import PlannerAgentWrapper
from agents.reflection_agent import ReflectionAgent
from agents.registry import AgentRegistry
from agents.task_state import InputSource, TaskState, TaskStatus
from agents.vision_agent import VisionAgentWrapper
from execution.models import ExecutionRecord, ExecutionStatus, StepStatus
from memory.agent import MemoryQueryContext
from memory.models import Memory
from memory.semantics import EpisodicDetails, FailureDetails
from planner.state import WorldState
from schemas.task import SingleTask

logger = logging.getLogger(__name__)

#: Default bound on how many times `Orchestrator` will replan a task
#: before giving up -- mirrors `ExecutionController`'s own bounded-
#: retry philosophy at the plan level instead of the action level.
DEFAULT_MAX_REPLANS = 2


class Orchestrator:
    """Drives the section 7.16 lifecycle. See module docstring."""

    def __init__(
        self,
        planner_agent: PlannerAgentWrapper,
        execution_agent: ExecutionAgentWrapper,
        *,
        memory_agent: Optional[MemoryAgentWrapper] = None,
        vision_agent: Optional[VisionAgentWrapper] = None,
        navigation_agent: Optional[NavigationAgent] = None,
        reflection_agent: Optional[ReflectionAgent] = None,
        event_bus: Optional[EventBus] = None,
        registry: Optional[AgentRegistry] = None,
    ) -> None:
        self._planner = planner_agent
        self._execution = execution_agent
        self._memory = memory_agent
        self._vision = vision_agent
        self._navigation = navigation_agent or NavigationAgent()
        self._reflection = reflection_agent or ReflectionAgent()
        self._events = event_bus or EventBus()
        self._registry = registry
        # One task runs at a time system-wide (see `agents.execution_
        # agent.ExecutionAgentWrapper`'s own "one controller per
        # execution request" note -- there is only one Simulator) --
        # cleared at the start of every `run()`, checked at each loop
        # boundary, and set by `cancel()` from a *different* thread
        # while `run()` is blocked in another (see `cancel()`'s
        # docstring).
        self._cancel_event = threading.Event()
        if self._registry is not None:
            for agent in (
                self._planner,
                self._execution,
                self._memory,
                self._vision,
                self._navigation,
                self._reflection,
            ):
                if agent is not None:
                    self._registry.register(agent)

    @property
    def events(self) -> EventBus:
        return self._events

    @property
    def registry(self) -> Optional[AgentRegistry]:
        return self._registry

    def cancel(self) -> None:
        """
        Requests cancellation of whatever task is currently running via
        `run()` on another thread -- `POST /tasks/{id}/cancel`'s entry
        point. Sets the shared `threading.Event` `run()`'s loop checks
        at each boundary *and* reaches into the currently-executing
        plan via `execution_agent.cancel_current()` (see that method's
        docstring) so an in-flight `execute_plan()` call is interrupted
        too, not just the *next* attempt prevented from starting. A
        no-op if nothing is running.
        """
        self._cancel_event.set()
        self._execution.cancel_current()

    def run(
        self,
        task: SingleTask,
        *,
        input_source: InputSource = InputSource.TEXT,
        max_replans: int = DEFAULT_MAX_REPLANS,
        on_created: Optional[Callable[[TaskState], None]] = None,
    ) -> TaskState:
        self._cancel_event.clear()
        run_started_at = time.perf_counter()
        task_id = task.task_id or str(uuid.uuid4())
        episode_id = str(uuid.uuid4())
        task_state = TaskState(
            task_id=task_id,
            user_request=task.goal or "",
            input_source=input_source,
            goal=task.goal,
            objects=[o for o in (task.object,) if o],
            target=task.target or task.target_location,
            status=TaskStatus.CREATED,
        )
        if on_created is not None:
            # Hands the caller a reference to *this exact* mutable
            # object, immediately -- lets `api/routes/tasks.py`'s
            # `_TaskStore` store it before any I/O happens, so a
            # concurrent `GET /tasks/{id}` sees this same object's
            # fields update live as `run()` mutates them in place,
            # exactly like `execute_plan()`'s `record` parameter
            # already lets `routes/execution.py` observe live progress.
            on_created(task_state)
        self._publish(task_state, EventType.TASK_CREATED)
        self._publish(task_state, EventType.TASK_PARSED)

        memory_context = self._retrieve_memory(task, episode_id, task_state)

        world_state = WorldState.initial()
        task_state.status = TaskStatus.PLANNING
        started = time.perf_counter()
        planning_result = self._planner.plan(task, world_state, memory_context)
        task_state.latencies_ms["planning_ms"] = (
            task_state.latencies_ms.get("planning_ms", 0.0)
            + (time.perf_counter() - started) * 1000.0
        )
        self._sync_agent_states(task_state)
        if not planning_result.success or planning_result.plan is None:
            task_state.latencies_ms["total_ms"] = (
                time.perf_counter() - run_started_at
            ) * 1000.0
            return self._finish_failed(
                task,
                task_state,
                episode_id,
                record=None,
                reason="; ".join(planning_result.errors) or "planning failed",
            )
        task_state.current_plan = planning_result.plan
        self._publish(task_state, EventType.PLAN_CREATED)

        attempt = 0
        while True:
            if self._cancel_event.is_set():
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_cancelled(task_state)

            self._observe(task, task_state)

            task_state.status = TaskStatus.EXECUTING
            self._publish(task_state, EventType.ACTION_STARTED)
            started = time.perf_counter()
            record = self._execution.execute_plan(task_state.current_plan, world_state)
            task_state.latencies_ms["execution_ms"] = (
                task_state.latencies_ms.get("execution_ms", 0.0)
                + (time.perf_counter() - started) * 1000.0
            )
            self._sync_agent_states(task_state)
            task_state.execution_history.append(record)
            task_state.completed_steps = [
                s.step_id
                for s in record.step_results
                if s.status == StepStatus.COMPLETED
            ]
            self._publish(
                task_state,
                (
                    EventType.ACTION_COMPLETED
                    if record.status == ExecutionStatus.SUCCESS
                    else EventType.ACTION_FAILED
                ),
            )

            if record.status == ExecutionStatus.CANCELLED:
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_cancelled(task_state)

            failures = self._diagnose(record, world_state)
            task_state.failures.extend(failures)

            task_state.status = TaskStatus.REFLECTING
            started = time.perf_counter()
            reflection = self._reflection.reflect(
                record, failures, attempt=attempt, max_attempts=max_replans
            )
            task_state.latencies_ms["reflection_ms"] = (
                task_state.latencies_ms.get("reflection_ms", 0.0)
                + (time.perf_counter() - started) * 1000.0
            )
            self._publish(
                task_state,
                EventType.REFLECTION_COMPLETED,
                payload=reflection.model_dump(mode="json"),
            )

            if reflection.action == "continue":
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_succeeded(
                    task, task_state, episode_id, record, world_state
                )
            if reflection.action == "abort":
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_failed(
                    task,
                    task_state,
                    episode_id,
                    record=record,
                    reason=reflection.reason,
                )

            attempt += 1
            if reflection.action == "retry":
                continue

            if self._cancel_event.is_set():
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_cancelled(task_state)

            # "replan"
            task_state.status = TaskStatus.REPLANNING
            self._publish(task_state, EventType.REPLAN_TRIGGERED)
            started = time.perf_counter()
            planning_result = self._planner.replan(task, world_state, memory_context)
            task_state.latencies_ms["planning_ms"] = (
                task_state.latencies_ms.get("planning_ms", 0.0)
                + (time.perf_counter() - started) * 1000.0
            )
            self._sync_agent_states(task_state)
            if not planning_result.success or planning_result.plan is None:
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_failed(
                    task,
                    task_state,
                    episode_id,
                    record=record,
                    reason="; ".join(planning_result.errors) or "replanning failed",
                )
            task_state.current_plan = planning_result.plan
            self._publish(task_state, EventType.PLAN_CREATED)

    # -- memory -----------------------------------------------------------

    def _retrieve_memory(
        self, task: SingleTask, episode_id: str, task_state: TaskState
    ):
        if self._memory is None:
            return None
        task_state.status = TaskStatus.RETRIEVING_MEMORY
        context = MemoryQueryContext(
            task_id=task.task_id,
            episode_id=episode_id,
            goal=task.goal,
            object=task.object,
            target=task.target,
        )
        started = time.perf_counter()
        memory_context = self._memory.retrieve_relevant_memories(context)
        task_state.latencies_ms["memory_retrieval_ms"] = (
            time.perf_counter() - started
        ) * 1000.0
        task_state.retrieved_memories = [
            {"memory_id": r.memory.memory_id, "score": r.final_score}
            for r in memory_context.results
        ]
        self._publish(task_state, EventType.MEMORY_RETRIEVED)
        return memory_context

    # -- observation --------------------------------------------------------

    def _observe(self, task: SingleTask, task_state: TaskState) -> None:
        """
        Section 7.16's `OBSERVE` step, skipped entirely when no
        `VisionAgentWrapper` was configured (the default -- see
        `__init__`) so every existing caller/test that never passed
        one keeps working byte-for-byte unchanged. Perception failures
        (e.g. no detector wired up server-side) are caught and logged,
        never allowed to break the task -- vision is informational for
        Mission Control's "Detected Objects" panel, never a
        precondition the rest of this loop depends on (planning/
        execution already resolve objects via simulator ground truth,
        see `execution.resolver.ObjectResolver`).
        """
        if self._vision is None:
            return
        prompt = f"{task.object or task.target or 'object'}."
        started = time.perf_counter()
        try:
            scene = self._vision.perceive(prompt)
        except Exception:
            logger.warning("orchestrator.observe_failed", exc_info=True)
            return
        task_state.latencies_ms["vision_ms"] = (
            task_state.latencies_ms.get("vision_ms", 0.0)
            + (time.perf_counter() - started) * 1000.0
        )
        task_state.known_objects = scene.labels()
        task_state.observations = [
            {
                "label": d.label,
                "confidence": d.confidence,
                "position": d.position_3d,
            }
            for d in scene.detections
        ]
        self._sync_agent_states(task_state)
        self._publish(task_state, EventType.OBSERVATION_RECEIVED)

    def _remember_terminal(
        self,
        task: SingleTask,
        task_state: TaskState,
        episode_id: str,
        *,
        success: bool,
        record: Optional[ExecutionRecord],
        world_state: Optional[WorldState],
        reason: Optional[str],
    ) -> Optional[Memory]:
        if self._memory is None:
            return None
        started = time.perf_counter()
        memory: Optional[Memory]
        if success:
            episodic_details = EpisodicDetails(
                task_summary=task.goal or "unknown",
                outcome="success",
                location=world_state.robot_location if world_state else None,
                relevant_objects=[v for v in (task.object, task.target) if v],
            )
            memory = self._memory.remember_episode(
                episodic_details, episode_id=episode_id, task_id=task.task_id
            )
        else:
            action_name = "unknown"
            cause = None
            error_code = None
            if record is not None:
                failing_step = next(
                    (s for s in record.step_results if s.status == StepStatus.FAILED),
                    None,
                )
                if failing_step is not None:
                    action_name = failing_step.action
                    if failing_step.error is not None:
                        cause = failing_step.error.message
                        error_code = failing_step.error.code.value
            failure_details = FailureDetails(
                task=task.goal or "unknown",
                action=action_name,
                failure_reason=cause or reason or "task failed",
                cause=cause,
                recovery=None,
                outcome="failed",
                error_code=error_code,
            )
            memory = self._memory.remember_failure(
                failure_details, episode_id=episode_id, task_id=task.task_id
            )
        task_state.latencies_ms["memory_write_ms"] = (
            task_state.latencies_ms.get("memory_write_ms", 0.0)
            + (time.perf_counter() - started) * 1000.0
        )
        if memory is not None:
            task_state.created_memories.append(
                {"memory_id": memory.memory_id, "memory_type": memory.memory_type.value}
            )
            self._publish(task_state, EventType.MEMORY_UPDATED)
        return memory

    # -- diagnosis ----------------------------------------------------------

    def _diagnose(
        self, record: ExecutionRecord, world_state: WorldState
    ) -> List[AgentFailure]:
        generic = ExecutionAgentWrapper.failures_from_record(record)
        refined = self._navigation.diagnose(record, world_state)
        if refined is None:
            return generic
        # The navigation diagnosis replaces the generic translation of
        # the *same* failing step (it is strictly more specific -- see
        # `NavigationAgent`'s docstring); any other failed step's
        # generic failure is kept as-is.
        return [refined] + generic[1:]

    # -- terminal transitions ------------------------------------------------

    def _finish_succeeded(
        self,
        task: SingleTask,
        task_state: TaskState,
        episode_id: str,
        record: ExecutionRecord,
        world_state: WorldState,
    ) -> TaskState:
        # Memory is written *before* `status` flips to its terminal
        # value and *before* `TASK_COMPLETED` publishes -- a caller
        # (an API poller, a test) that treats a terminal `status` as
        # "this task is fully done, read whatever else you need off
        # it" must never observe a status that says so while
        # `created_memories` is still empty. `task_state` is a single
        # mutable object visible to another thread the instant `on_
        # created()` ran (see `run()`'s docstring) -- this ordering is
        # what makes that visible progress actually consistent, not
        # just "eventually correct."
        self._remember_terminal(
            task,
            task_state,
            episode_id,
            success=True,
            record=record,
            world_state=world_state,
            reason=None,
        )
        task_state.status = TaskStatus.SUCCEEDED
        self._publish(task_state, EventType.TASK_COMPLETED)
        return task_state

    def _finish_failed(
        self,
        task: SingleTask,
        task_state: TaskState,
        episode_id: str,
        *,
        record: Optional[ExecutionRecord],
        reason: str,
    ) -> TaskState:
        # See `_finish_succeeded`'s docstring for why memory is written
        # before `status`/the event flip to terminal.
        self._remember_terminal(
            task,
            task_state,
            episode_id,
            success=False,
            record=record,
            world_state=None,
            reason=reason,
        )
        task_state.status = TaskStatus.FAILED
        self._publish(task_state, EventType.TASK_FAILED, payload={"reason": reason})
        return task_state

    def _finish_cancelled(self, task_state: TaskState) -> TaskState:
        """
        Part 3's cancellation contract: `TaskStatus.CANCELLED`,
        `EventType.TASK_CANCELLED`, and deliberately **no** memory
        write -- a cancelled task is not a failure to learn a recovery
        lesson from, and section 3 explicitly requires cancellation to
        never corrupt memory. `execution_history`/`failures`/`events`
        already recorded for this run are left exactly as they are
        (nothing here mutates or removes them) -- "must not corrupt...
        event history" satisfied by simply never touching it.
        """
        task_state.status = TaskStatus.CANCELLED
        self._publish(task_state, EventType.TASK_CANCELLED)
        return task_state

    # -- events / agent state -------------------------------------------------

    def _publish(
        self, task_state: TaskState, event: EventType, *, payload: Optional[dict] = None
    ) -> None:
        self._events.publish(
            Event(
                task_id=task_state.task_id,
                agent="orchestrator",
                event=event,
                payload=payload or {},
            )
        )

    def _sync_agent_states(self, task_state: TaskState) -> None:
        if self._registry is not None:
            task_state.agent_states = self._registry.snapshot_states()
        else:
            task_state.agent_states = {
                self._planner.name: self._planner.get_state(),
                self._execution.name: self._execution.get_state(),
            }
