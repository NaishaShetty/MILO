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
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from agents.events import Event, EventBus, EventType
from agents.execution_agent import ExecutionAgentWrapper
from agents.failures import AgentFailure, FailureCategory
from agents.memory_agent import MemoryAgentWrapper
from agents.navigation_agent import NavigationAgent
from agents.planner_agent import PlannerAgentWrapper
from agents.reflection_agent import ReflectionAgent
from agents.registry import AgentRegistry
from agents.task_state import InputSource, TaskState, TaskStatus
from agents.vision_agent import VisionAgentWrapper
from execution.models import ExecutionRecord, ExecutionStatus, StepStatus
from execution.resolver import spellings_of
from memory.agent import MemoryQueryContext
from memory.models import Memory, MemoryProvenance
from memory.semantics import EpisodicDetails, FailureDetails
from orchestration.answerer import where_parts
from orchestration.composite import expand_composite
from orchestration.explain import (
    explain_plan,
    explain_step,
    explain_verdict,
)
from planner.grounding import ground_world_state
from planner.models import PlanStep
from planner.state import WorldState
from planner.task_library import COMPOSITE_GOALS
from schemas.task import MultiTask, SingleTask

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
        planner_factory: Optional[Callable[[str], PlannerAgentWrapper]] = None,
        episode_logger=None,
        outcome_predictor=None,
        plan_ranker=None,
        trace_recorder=None,
        approval_gate=None,
        in_mission_recovery: Optional[bool] = None,
    ) -> None:
        self._planner = planner_agent
        #: Targeted in-mission fixes (`orchestration.recovery`); None = follow
        #: `MILO_INMISSION_RECOVERY`.
        self._in_mission_recovery = in_mission_recovery
        #: Builds a planner wrapper for a requested strategy name; without
        #: one, every task uses `planner_agent`.
        self._planner_factory = planner_factory
        self._default_planner = planner_agent
        self._current_state: Optional[TaskState] = None
        #: Optional `learning.episode_log.EpisodeLogger` (the data flywheel).
        self._episode_logger = episode_logger
        #: Optional `learning.serving.OutcomePredictor` (per-step confidence) and
        #: `learning.ranker.PlanRanker` (choose among planners' plans). Both optional.
        self._predictor = outcome_predictor
        self._ranker = plan_ranker
        #: Optional `tracelog.recorder.TraceRecorder`: per-mission trace store.
        self._trace = trace_recorder
        #: Optional `oversight.gate.ApprovalGate`: ask before risky steps and
        #: before running plans MILO worked out itself.
        self._gate = approval_gate
        self._undo_before: Dict[int, Dict[str, Any]] = {}
        self._contexts: Dict[int, Dict] = {}
        #: Extra fields for the logger's `begin()` (scene id, seed, injected fault...).
        self.episode_context: Dict = {}
        self._snapshots: Dict[int, Dict] = {}
        self._retries = 0
        self._replans = 0
        #: In-mission recovery tally: (failure, action, target) -> fixes applied.
        self._mitigations: Dict[Tuple[str, str, str], int] = {}
        self._memory_stats: Dict[str, float] = {}
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
        if self._current_state is not None:
            self._current_state.cancel_requested = True
            if self._gate is not None:
                # stop waiting for an answer that no longer matters
                self._gate.cancel_all(self._current_state.task_id)
        self._execution.cancel_current()

    def run(
        self,
        task: Union[SingleTask, MultiTask],
        **kwargs,
    ) -> TaskState:
        """Runs a task (see `_run`) and, if an episode logger is attached, records the outcome."""
        started = time.perf_counter()
        self._retries = self._replans = 0
        self._mitigations = {}
        self._snapshots = {}
        self._memory_stats = {}
        self._contexts = {}
        state = self._run(task, **kwargs)
        if self._episode_logger is not None:
            self._episode_logger.finish(
                state.task_id,
                outcome=state.status.value,
                replans=self._replans,
                retries=self._retries,
                total_steps=sum(len(r.step_results) for r in state.execution_history),
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
        return state

    def _run(
        self,
        task: Union[SingleTask, MultiTask],
        *,
        input_source: InputSource = InputSource.TEXT,
        max_replans: int = DEFAULT_MAX_REPLANS,
        on_created: Optional[Callable[[TaskState], None]] = None,
        planner_type: Optional[str] = None,
    ) -> TaskState:
        self._cancel_event.clear()
        run_started_at = time.perf_counter()
        self._planner = self._select_planner(planner_type)
        # A `MultiTask` is run as one plan over its sub-goals; the rest of
        # this method works with a single "header" task describing it.
        subtasks: Optional[List[SingleTask]] = None
        if isinstance(task, MultiTask):
            subtasks = list(task.subtasks)
            task = SingleTask(goal=task.goal or "multi_step", task_id=task.task_id)
        task_id = task.task_id or str(uuid.uuid4())
        episode_id = str(uuid.uuid4())
        task_state = TaskState(
            task_id=task_id,
            # a novel task carries the user's own words (its goal is just "novel")
            user_request=(
                task.estimated_goal
                if task.goal == "novel" and task.estimated_goal
                else task.goal or ""
            ),
            input_source=input_source,
            goal=task.goal,
            objects=[o for o in (task.object,) if o],
            target=task.target or task.target_location,
            status=TaskStatus.CREATED,
            planner=self._planner.planner_type,
        )
        self._current_state = task_state
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
        if self._planner.planner_type == "novel":
            self._think(
                task_state, "planner", "I don't know this one yet. Let me work it out."
            )
        if self._episode_logger is not None:
            self._episode_logger.begin(
                task_state.task_id,
                **{
                    "task_text": task_state.user_request,
                    "parsed_task": task.model_dump(mode="json"),
                    "task_kind": task.goal or "",
                    "planner": task_state.planner or "",
                    **self.episode_context,
                },
            )

        memory_context = self._retrieve_memory(task, episode_id, task_state)
        self._reconcile_memory(task_state)
        self._think_about_memory(task_state, memory_context)
        self._memory_stats = self._memory_stats_of(memory_context)

        if subtasks is None and (task.goal or "") in COMPOSITE_GOALS:
            # "Clear the table" / "tidy up": look at the room, decide which
            # objects, then run them as one multi-object plan.
            expansion = expand_composite(
                task, self._execution.get_metadata() or {}, self._usual_places()
            )
            if not expansion.subtasks:
                task_state.answer = expansion.message
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_succeeded(
                    task, task_state, episode_id, None, WorldState.initial()
                )
            subtasks = expansion.subtasks
        if subtasks:
            task_state.objects = [s.object for s in subtasks if s.object]
            task_state.sub_goals = [
                {
                    "goal": s.goal,
                    "object": s.object,
                    "target": s.target or s.target_location,
                }
                for s in subtasks
            ]

        world_state = WorldState.initial()
        self._seed_from_simulator(world_state)
        # Ground world_state against live vision *before* planning, not
        # only for post-hoc observability -- see `_observe()`'s
        # docstring. Skipped entirely when no vision_agent is
        # configured, matching this method's existing behavior.
        self._observe(task, task_state, world_state)
        task_state.status = TaskStatus.PLANNING
        started = time.perf_counter()
        planning_result = self._plan(
            task, subtasks, world_state, memory_context, replan=False
        )
        task_state.latencies_ms["planning_ms"] = (
            task_state.latencies_ms.get("planning_ms", 0.0)
            + (time.perf_counter() - started) * 1000.0
        )
        self._sync_agent_states(task_state)
        if not planning_result.success or planning_result.plan is None:
            task_state.latencies_ms["total_ms"] = (
                time.perf_counter() - run_started_at
            ) * 1000.0
            if planning_result.errors:
                self._think(task_state, "planner", "; ".join(planning_result.errors))
            return self._finish_failed(
                task,
                task_state,
                episode_id,
                record=None,
                reason="; ".join(planning_result.errors) or "planning failed",
            )
        task_state.current_plan = planning_result.plan
        self._apply_lessons(task, task_state)
        self._note_planner(task_state, planning_result.plan)
        self._think(
            task_state,
            "planner",
            explain_plan(
                len(planning_result.plan.steps),
                planning_result.plan.metadata.get("skipped_steps"),
            ),
        )
        self._publish(task_state, EventType.PLAN_CREATED)
        refused = self._preview(task_state)
        if refused is not None:
            task_state.latencies_ms["total_ms"] = (
                time.perf_counter() - run_started_at
            ) * 1000.0
            return self._finish_failed(
                task, task_state, episode_id, record=None, reason=refused
            )

        if not planning_result.plan.steps:
            # Every step was already satisfied by the current world state
            # (see `planner.progress`): nothing to execute.
            task_state.latencies_ms["total_ms"] = (
                time.perf_counter() - run_started_at
            ) * 1000.0
            return self._finish_succeeded(
                task, task_state, episode_id, None, world_state, subtasks
            )

        attempt = 0
        while True:
            if self._cancel_event.is_set():
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_cancelled(task_state)

            self._observe(task, task_state, world_state)

            task_state.status = TaskStatus.EXECUTING
            self._publish(task_state, EventType.ACTION_STARTED)
            started = time.perf_counter()
            record = self._execution.execute_plan(
                task_state.current_plan,
                world_state,
                listener=self._step_listener(task_state),
            )
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
            extra = (
                {"contexts": self._contexts}
                if getattr(self._reflection, "uses_contexts", False)
                else {}
            )
            reflection = self._reflection.reflect(
                record, failures, attempt=attempt, max_attempts=max_replans, **extra
            )
            decisions = (
                self._reflection.pop_decisions()  # type: ignore[attr-defined]
                if hasattr(self._reflection, "pop_decisions")
                else []
            )
            task_state.latencies_ms["reflection_ms"] = (
                task_state.latencies_ms.get("reflection_ms", 0.0)
                + (time.perf_counter() - started) * 1000.0
            )
            self._explain_reflection(
                task_state, record, failures, reflection.action, reflection.explanation
            )
            if self._episode_logger is not None:
                self._episode_logger.log_attempt(
                    task_state.task_id,
                    attempt=attempt,
                    record=record,
                    snapshots=self._snapshots,
                    retries_so_far=self._retries,
                    replans_so_far=self._replans,
                    memory_stats=self._memory_stats,
                    verdict=reflection.action,
                    model_decisions=decisions,
                )
                self._snapshots = {}
            if reflection.action == "retry":
                self._retries += 1
            elif reflection.action == "replan":
                self._replans += 1
            self._publish(
                task_state,
                EventType.REFLECTION_COMPLETED,
                payload={
                    **reflection.model_dump(mode="json"),
                    "model_decisions": decisions,
                },
            )

            unmet = (
                self._unmet_stated_goal(task_state)
                if reflection.action == "continue" and attempt < max_replans
                else None
            )
            if unmet:
                # Every step "worked" but the plan's own success conditions are
                # false in the world: replan with that reason instead of finishing.
                task_state.failures.append(
                    AgentFailure(
                        category=FailureCategory.ENVIRONMENT_CHANGED,
                        message=unmet,
                        agent="orchestrator",
                    )
                )
                self._think(task_state, "eyes", unmet)
                reflection = reflection.model_copy(update={"action": "replan"})
                self._replans += 1
            if reflection.action == "continue":
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_succeeded(
                    task, task_state, episode_id, record, world_state, subtasks
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
                self._recover_in_mission(task_state, record)
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
            planning_result = self._plan(
                task, subtasks, world_state, memory_context, replan=True
            )
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
            self._apply_lessons(task, task_state)
            self._recover_in_mission(task_state, record)
            self._note_planner(task_state, planning_result.plan)
            self._think(
                task_state,
                "planner",
                explain_plan(
                    len(planning_result.plan.steps),
                    planning_result.plan.metadata.get("skipped_steps"),
                ),
            )
            self._publish(task_state, EventType.PLAN_CREATED)
            if not planning_result.plan.steps:
                # The failed attempt had in fact finished the job.
                task_state.latencies_ms["total_ms"] = (
                    time.perf_counter() - run_started_at
                ) * 1000.0
                return self._finish_succeeded(
                    task, task_state, episode_id, record, world_state, subtasks
                )

    # -- planning -----------------------------------------------------------

    def _plan(
        self,
        task: SingleTask,
        subtasks: Optional[List[SingleTask]],
        world_state: WorldState,
        memory_context,
        *,
        replan: bool,
    ):
        """One sub-goal -> `plan`/`replan`; several -> `plan_multi`."""
        if subtasks:
            multi = self._planner.replan_multi if replan else self._planner.plan_multi
            return multi(
                subtasks,
                world_state,
                memory_context,
                task_id=task.task_id or "",
                goal=task.goal or "multi_step",
            )
        single = self._planner.replan if replan else self._planner.plan
        result = single(task, world_state, memory_context)
        if (
            self._ranker is not None
            and self._planner_factory is not None
            and not replan
        ):
            result = self._rank(task, world_state, memory_context, result)
        return result

    def _rank(self, task, world_state, memory_context, first):
        """Flagged: also ask the other planners and keep the plan the predictor likes best."""
        try:
            candidates = [first]
            for name in self._ranker.planner_names:
                if name == self._planner.planner_type or self._planner_factory is None:
                    continue
                candidates.append(
                    self._planner_factory(name).plan(task, world_state, memory_context)
                )
            return self._ranker.best(candidates, self._execution.get_metadata())
        except Exception:
            logger.warning("orchestrator.rank_failed", exc_info=True)
            return first

    def _select_planner(self, planner_type: Optional[str]) -> PlannerAgentWrapper:
        """The planner for this run: the requested strategy, else the default."""
        if not planner_type or self._planner_factory is None:
            return self._default_planner
        if planner_type == self._default_planner.planner_type:
            return self._default_planner
        planner = self._planner_factory(planner_type)
        if self._registry is not None:
            self._registry.register(planner)  # so agent states show the live one
        return planner

    # -- narration ---------------------------------------------------------

    def _think(
        self,
        task_state: TaskState,
        kind: str,
        text: str,
        step_id: Optional[int] = None,
    ) -> None:
        """Appends one line to MILO's running commentary."""
        if not text:
            return
        task_state.thoughts.append(
            {"kind": kind, "text": text, "at": time.time(), "step_id": step_id}
        )

    def _think_about_memory(self, task_state: TaskState, memory_context) -> None:
        results = getattr(memory_context, "results", None) or []
        if results:
            top = results[0].memory
            self._think(task_state, "memory", f"I remember: {top.content}.")

    def _note_planner(self, task_state: TaskState, plan) -> None:
        """Surfaces a planner fallback ("HTN has no method for that, so the
        rule-based planner planned it") as a plain note on the task."""
        fallback = plan.metadata.get("planner_fallback")
        if isinstance(fallback, dict):
            task_state.planner_note = fallback.get("reason")
        elif plan.metadata.get("react_fallback"):
            task_state.planner_note = (
                "The thinking planner wasn't available, so the rule-based "
                "planner made this plan."
            )

    def _predict_step(self, task_state: TaskState, step: PlanStep) -> None:
        """Confidence for the step about to run (never blocks: failures are logged and ignored)."""
        predictor = self._predictor
        plan = task_state.current_plan
        if predictor is None or plan is None or not predictor.usable:
            return
        try:
            from learning.predictor_features import context_from_live

            steps = plan.steps
            index = next(
                (i for i, s in enumerate(steps) if s.step_id == step.step_id), 0
            )
            ctx = context_from_live(
                action=step.action,
                target=step.target,
                metadata=self._execution.get_metadata(),
                step_index=index,
                remaining_steps=len(steps) - index - 1,
                retries_so_far=self._retries,
                replans_so_far=self._replans,
                planner=task_state.planner or "rule_based",
                memory_stats=self._memory_stats,
            )
            self._contexts[step.step_id] = ctx
            pred = predictor.predict(ctx, explain=True)
            step.confidence = round(pred.p_success, 3)
            step.why = "; ".join(pred.top_factors) or None
        except Exception:
            logger.warning("orchestrator.predict_failed", exc_info=True)

    def _snapshot(self, step: PlanStep, status: str) -> None:
        """Feature snapshots around a step, for the episode log."""
        from learning.features import world_features

        meta = self._execution.get_metadata()
        snap = self._snapshots.setdefault(step.step_id, {})
        if status == "started":
            snap["before"] = world_features(meta, step.target)
        elif status in ("success", "failed", "blocked", "already_done"):
            snap["after"] = world_features(meta, step.target)

    @staticmethod
    def _memory_stats_of(memory_context) -> Dict[str, float]:
        results = getattr(memory_context, "results", None) or []
        if not results:
            return {"hits": 0, "sim_max": 0.0, "sim_mean": 0.0, "prior_success": -1.0}
        sims = [float(r.similarity) for r in results]
        outcomes = [
            r.memory.metadata.get("outcome")
            for r in results
            if isinstance(r.memory.metadata, dict) and r.memory.metadata.get("outcome")
        ]
        prior = (
            sum(1 for o in outcomes if o == "success") / len(outcomes)
            if outcomes
            else -1.0
        )
        return {
            "hits": len(results),
            "sim_max": max(sims),
            "sim_mean": sum(sims) / len(sims),
            "prior_success": prior,
        }

    def _step_listener(self, task_state: TaskState) -> Callable[[PlanStep, str], None]:
        """Narrates execution live: sets each step's `explanation`, the
        task's `current_step`, and adds a thought when a step finishes."""

        def listen(step: PlanStep, status: str) -> None:
            if status == "started":
                self._before_step(task_state, step)
            elif status == "success":
                before = self._undo_before.pop(step.step_id, None)
                if before is not None:
                    task_state.undo_log.append(before)
            if self._episode_logger is not None:
                self._snapshot(step, status)
            if status == "started" and self._predictor is not None:
                self._predict_step(task_state, step)
            if status == "started":
                task_state.current_step = step.step_id
                step.explanation = explain_step(step, "doing")
            elif status in ("success", "already_done"):
                step.explanation = explain_step(step, "done")
                if status == "success":
                    kind = "eyes" if step.action == "locate" else "hands"
                    self._think(task_state, kind, step.explanation, step.step_id)
            elif status == "cancelled":
                step.explanation = "I stopped before this one."
            if self._trace is not None:
                self._trace.on_step(task_state, step, status)

        return listen

    def _explain_reflection(
        self,
        task_state: TaskState,
        record: ExecutionRecord,
        failures: List[AgentFailure],
        verdict: str,
        explanation: Optional[str] = None,
    ) -> None:
        """Turns a reflection verdict into a sentence on the failed step
        and a thought -- "I couldn't reach the fridge, so I'm trying
        another route."""
        plan = task_state.current_plan
        failed_step = None
        if plan is not None:
            failed_id = next(
                (
                    s.step_id
                    for s in record.step_results
                    if s.status in (StepStatus.FAILED, StepStatus.BLOCKED)
                ),
                None,
            )
            failed_step = next((s for s in plan.steps if s.step_id == failed_id), None)
        sentence = explanation or explain_verdict(
            verdict, failed_step, failures[0] if failures else None
        )
        if failed_step is not None and verdict != "continue":
            failed_step.explanation = sentence
        self._think(
            task_state,
            "reflect",
            sentence,
            failed_step.step_id if failed_step is not None else None,
        )

    def _seed_from_simulator(self, world_state: WorldState) -> None:
        """
        Starts the symbolic state from what the simulator itself reports
        about each object -- open/closed, openable, switched on/off --
        so "close the drawer" or "turn off the tap" plan against the real
        starting state instead of an all-unknown one (a `close` of a
        thing not known to be open does not validate). Live vision, when
        configured, then overrides this (`ground_world_state`).
        Best-effort: a missing/odd metadata snapshot just leaves the
        state as it was.
        """
        metadata = self._execution.get_metadata() or {}
        # AI2-THOR calls it "Faucet"/"Fridge"; plans (and people) say
        # "tap"/"refrigerator" -- seed every spelling.
        for obj in metadata.get("objects") or []:
            name = str(obj.get("objectType") or "").strip().lower()
            if not name:
                continue
            for key in spellings_of(name):
                state = world_state.object(key)
                if obj.get("isOpen") is not None:
                    state.is_open = bool(obj["isOpen"])
                if obj.get("openable") is not None:
                    state.is_openable = bool(obj["openable"])
                if obj.get("isToggled") is not None:
                    state.is_on = bool(obj["isToggled"])

    def _usual_places(self) -> Dict[str, Tuple[str, str]]:
        if self._memory is None:
            return {}
        try:
            return self._memory.usual_places()
        except Exception:
            logger.warning("orchestrator.usual_places_failed", exc_info=True)
            return {}

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

    def _observe(
        self,
        task: SingleTask,
        task_state: TaskState,
        world_state: Optional[WorldState] = None,
    ) -> None:
        """
        Section 7.16's `OBSERVE` step, skipped entirely when no
        `VisionAgentWrapper` was configured (the default -- see
        `__init__`) so every existing caller/test that never passed
        one keeps working byte-for-byte unchanged. Perception failures
        (e.g. no detector wired up server-side) are caught and logged,
        never allowed to break the task -- a bad scene degrades
        `world_state` back to whatever it already was (memory/a prior
        scene), it never corrupts it.

        When `world_state` is given, this also grounds it against the
        scene via `planner.grounding.ground_world_state()` -- the
        `SpatialScene -> WorldState` translation that lets `run()`
        plan and execute against what the robot actually currently
        sees, rather than an always-empty `WorldState.initial()` or
        `execution.resolver.ObjectResolver`'s simulator-metadata scan
        (still used for dispatch-time objectId resolution, a separate
        concern -- see `grounding.py`'s module docstring). `run()`
        calls this once before planning and again each loop iteration
        before execution, so replans see updated perception too.
        """
        if self._vision is None:
            return
        prompt = f"{task.object or task.target or 'object'}."
        started = time.perf_counter()
        # The planning loop only needs labels, depth and open/closed
        # state, so it takes the cheap path (no SAM2 masks). The Vision
        # panel's own route keeps calling the full `perceive()`. A
        # wrapper without `observe()` (older test doubles) just gets
        # the full call.
        observe = getattr(self._vision, "observe", None)
        try:
            scene = (
                observe(prompt)
                if observe is not None
                else self._vision.perceive(prompt)
            )
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
        if world_state is not None:
            ground_world_state(
                scene, world_state, held_objects=self._read_held_objects()
            )
        self._sync_agent_states(task_state)
        self._publish(task_state, EventType.OBSERVATION_RECEIVED)

    def _read_held_objects(self) -> Optional[List[str]]:
        """
        The simulator's `inventoryObjects` (via the vision wrapper), or
        `None` when unavailable -- `ground_world_state` then falls back
        to its depth-only held-object guess.
        """
        reader = getattr(self._vision, "held_objects", None)
        if reader is None:
            return None
        try:
            held = reader()
        except Exception:
            logger.warning("orchestrator.held_objects_failed", exc_info=True)
            return None
        return list(held) if isinstance(held, (list, tuple)) else None

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

    def _remember_learned(
        self,
        task: SingleTask,
        subtasks: Optional[List[SingleTask]],
        task_state: TaskState,
        episode_id: str,
    ) -> None:
        """
        "Write what was learned after every mission": where the things
        MILO just put away now live, and where a `find` found its object.
        Only facts the mission itself established -- never a guess -- and
        only on success. Each lesson is also a plain sentence on the
        `TaskState` for the Missions page.
        """
        metadata: Dict = {}
        for sub in subtasks or [task]:
            goal = (sub.goal or "").lower()
            obj = sub.object
            target = sub.target or sub.target_location
            relation: Optional[str] = None
            place: Optional[str] = None
            sentence: Optional[str] = None
            if (
                goal in ("store", "put_away", "place", "pick_and_place")
                and obj
                and target
            ):
                relation = (
                    "stored_in" if goal in ("store", "put_away") else "located_on"
                )
                place = target
                sentence = f"The {obj} goes {'in' if relation == 'stored_in' else 'on'} the {target}."
            elif goal == "find" and obj:
                if not metadata:
                    metadata = self._execution.get_metadata() or {}
                found = where_parts(obj, metadata)
                if found is None:
                    continue
                preposition, place = found
                relation = "stored_in" if preposition == "in" else "located_on"
                sentence = f"The {obj} is {preposition} the {place}."
                task_state.answer = sentence
            if relation is None or place is None or obj is None:
                continue
            task_state.learned.append(sentence or "")
            if self._memory is None:
                continue
            memory = self._memory.remember_observation(
                obj,
                relation,
                place,
                provenance=MemoryProvenance.OBSERVATION,
                confidence=0.8,
                episode_id=episode_id,
                task_id=task.task_id,
            )
            if memory is not None:
                task_state.created_memories.append(
                    {
                        "memory_id": memory.memory_id,
                        "memory_type": memory.memory_type.value,
                    }
                )

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
        record: Optional[ExecutionRecord],
        world_state: WorldState,
        subtasks: Optional[List[SingleTask]] = None,
    ) -> TaskState:
        failed_check = self._verify_goal(task, subtasks, task_state)
        if failed_check is not None:
            return self._finish_failed(
                task, task_state, episode_id, record=record, reason=failed_check
            )
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
        self._remember_learned(task, subtasks, task_state, episode_id)
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
        self._after_mission(task_state)
        self._publish(task_state, EventType.TASK_COMPLETED)
        return task_state

    def _before_step(self, task_state: TaskState, step: PlanStep) -> None:
        """Records the state undo needs, then asks the user about a risky step."""
        try:
            meta = self._execution.get_metadata() or {}
            from oversight.ambiguity import same_kind

            def snap(name: Optional[str]) -> Dict[str, Any]:
                if not name:
                    return {}
                match = (
                    [o for o in meta.get("objects") or [] if o.get("objectId") == name]
                    if "|" in name
                    else same_kind(name, meta)[:1]
                )
                obj = match[0] if match else {}
                parents = obj.get("parentReceptacles") or []
                return {
                    "id": obj.get("objectId"),
                    "parent": str(parents[0]) if parents else None,
                    "isOpen": obj.get("isOpen"),
                    "isToggled": obj.get("isToggled"),
                }

            before = snap(step.target)
            if step.action == "place":
                # where it was before it was picked up, not "in MILO's hand"
                earlier = next(
                    (
                        e
                        for e in reversed(task_state.undo_log)
                        if e["action"] == "pickup"
                        and e.get("target") in (before.get("id"), step.target)
                    ),
                    None,
                )
                before["parent"] = (earlier or {}).get("before", {}).get("parent")
            target = before.get("id") or step.target
            home = before.get("parent")
            self._undo_before[step.step_id] = {
                "step_id": step.step_id,
                "action": step.action,
                "target": target,
                "container": step.parameters.get("container"),
                "before": {**before, "parent": home},
            }
        except Exception:
            logger.warning("orchestrator.undo_snapshot_failed", exc_info=True)
        if self._gate is None or step.parameters.get("approved"):
            return
        why = self._gate.step_risk(step.action, step.target)
        if not why:
            return
        decision = self._gate.ask(
            task_state,
            {
                "kind": "step",
                "step_id": step.step_id,
                "action": step.action,
                "target": step.target,
                "text": explain_step(step, "doing"),
                "why": why,
            },
        )
        if decision.choice == "approve":
            step.parameters["approved"] = True
            self._think(task_state, "hands", "Thanks, going ahead.", step.step_id)
        else:
            step.parameters["skip_requested"] = True
            self._think(
                task_state, "hands", "OK, I'll leave that step out.", step.step_id
            )

    def _preview(self, task_state: TaskState) -> Optional[str]:
        """A plan MILO worked out itself (not a saved skill) is shown before it runs:
        approve, approve with steps left out, or cancel. Returns a reason to stop."""
        plan = task_state.current_plan
        novel = (plan.metadata.get("novel") if plan else None) or {}
        if self._gate is None or plan is None or novel.get("source") != "model":
            return None
        decision = self._gate.ask(
            task_state,
            {
                "kind": "plan",
                "why": "I worked this plan out myself. Shall I go ahead?",
                "steps": [
                    {
                        "step_id": s.step_id,
                        "action": s.action,
                        "target": s.target,
                        "container": s.parameters.get("container"),
                        "text": explain_step(s, "doing"),
                    }
                    for s in plan.steps
                ],
            },
        )
        if decision.choice != "approve":
            return "You stopped the plan before I started."
        if decision.steps is not None:
            keep = {int(s["step_id"]) for s in decision.steps if "step_id" in s}
            plan.steps = [s for s in plan.steps if s.step_id in keep]
            self._think(
                task_state,
                "planner",
                f"OK, I'll do it your way ({len(plan.steps)} steps).",
            )
        return None

    def _unmet_stated_goal(self, task_state: TaskState) -> Optional[str]:
        """For a plan that states its own success conditions: the reason they are
        not met in the world right now, else None."""
        plan = task_state.current_plan
        stated = (plan.metadata.get("success_predicates") if plan else None) or []
        if not stated:
            return None
        try:
            from verification.predicates import Predicate, check_all

            missed = [
                r
                for r in check_all(
                    [Predicate.from_dict(p) for p in stated],
                    self._execution.get_metadata(),
                )
                if not r.ok
            ]
        except Exception:
            return None
        if not missed:
            return None
        return "Every step ran, but " + "; ".join(r.reason for r in missed) + "."

    def _learn_from_failure(
        self, task: SingleTask, task_state: TaskState, episode_id: str
    ) -> None:
        from memory import lessons

        agent = self._raw_memory()
        if agent is None or not lessons.enabled():
            return
        try:
            lesson = lessons.lesson_from(task_state, task.goal, task.object)
            if lesson is not None:
                lessons.remember(
                    agent, lesson, episode_id=episode_id, task_id=task.task_id
                )
        except Exception:
            logger.warning("orchestrator.lesson_write_failed", exc_info=True)

    def _raw_memory(self) -> Any:
        return getattr(self._memory, "_memory_agent", None) if self._memory else None

    def _reconcile_memory(self, task_state: TaskState) -> None:
        """Out-of-date location memories lose weight (or are quarantined) when the
        scene in front of MILO disagrees with them."""
        agent = self._raw_memory()
        if agent is None or not hasattr(agent, "reconcile"):
            return
        changed = agent.reconcile(self._execution.get_metadata())
        if changed:
            names = sorted(
                {str((m.metadata or {}).get("subject", "")) for m in changed}
            )
            self._think(
                task_state,
                "memory",
                "What I remembered about the "
                + ", ".join(n for n in names if n)
                + " is out of date, so I'll trust my eyes instead.",
            )

    def _apply_lessons(self, task: SingleTask, task_state: TaskState) -> None:
        """Failure memory: recall lessons for this kind of task and adjust the plan."""
        from memory import lessons

        agent = self._raw_memory()
        plan = task_state.current_plan
        if agent is None or plan is None or not lessons.enabled():
            return
        try:
            found = lessons.recall(agent.list_memories(), task.goal, task.object)
            said = lessons.apply(plan, found)
        except Exception:
            logger.warning("orchestrator.lessons_failed", exc_info=True)
            return
        if said:
            plan.metadata["lessons"] = found
            self._think(task_state, "memory", said)

    def _recover_in_mission(
        self, task_state: TaskState, record: ExecutionRecord
    ) -> None:
        """Targeted fix before the next attempt: look around after "not visible",
        walk up again after "not reachable" (see `orchestration.recovery`). Any
        error leaves the plan as the plain retry/replan would have it."""
        from orchestration import recovery

        plan = task_state.current_plan
        on = self._in_mission_recovery
        if plan is None or not (recovery.enabled() if on is None else on):
            return
        try:
            said = recovery.mitigate(plan, record, self._mitigations)
        except Exception:
            logger.warning("orchestrator.recovery_failed", exc_info=True)
            return
        if said:
            self._think(task_state, "planner", said)

    def _after_mission(self, task_state: TaskState) -> None:
        """Lets a planner that learns from outcomes (the novel-task planner) see how
        the mission ended. Never raises."""
        hook = getattr(getattr(self._planner, "_planner", None), "after_mission", None)
        if hook is None:
            return
        try:
            hook(task_state)
        except Exception:
            logger.warning("orchestrator.after_mission_failed", exc_info=True)

    def _verify_goal(
        self,
        task: SingleTask,
        subtasks: Optional[List[SingleTask]],
        task_state: TaskState,
    ) -> Optional[str]:
        """Checks the goal's success predicates against the simulator's own
        metadata. `MILO_GOAL_CHECK=off|report|enforce` (default `report`: record
        and narrate; `enforce` also turns a failed check into a failed mission).
        Returns the failure reason when enforcing, else None. Never raises."""
        mode = os.environ.get("MILO_GOAL_CHECK", "report").strip().lower()
        plan = task_state.current_plan
        stated = (plan.metadata.get("success_predicates") if plan else None) or []
        if stated:
            # A plan MILO worked out itself states its own success conditions;
            # they are always enforced -- the world decides, not the model.
            mode = "enforce"
        if mode not in ("report", "enforce"):
            return None
        try:
            from verification.predicates import Predicate, check_all, goal_predicates

            predicates = [Predicate.from_dict(p) for p in stated] or [
                p for t in (subtasks or [task]) for p in goal_predicates(t)
            ]
            if not predicates:
                return None
            results = check_all(predicates, self._execution.get_metadata())
        except Exception:
            logger.warning("orchestrator.goal_check_failed", exc_info=True)
            return None
        task_state.verification = [r.to_dict() for r in results]
        missed = [r for r in results if not r.ok]
        if not missed:
            return None  # kept in `verification`; "All done!" already says it
        reason = "I checked and " + "; ".join(r.reason for r in missed) + "."
        self._think(task_state, "eyes", reason)
        return reason if mode == "enforce" else None

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
        self._learn_from_failure(task, task_state, episode_id)
        self._after_mission(task_state)
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
        summary = self._execution.restore_clean_state()
        task_state.cancel_summary = summary
        task_state.cancel_requested = True
        self._think(
            task_state,
            "reflect",
            "Okay, I stopped." + (f" {summary}" if summary else ""),
        )
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
        if self._trace is not None:
            self._trace.on_event(task_state, event.value, payload or {})

    def _sync_agent_states(self, task_state: TaskState) -> None:
        if self._registry is not None:
            task_state.agent_states = self._registry.snapshot_states()
        else:
            task_state.agent_states = {
                self._planner.name: self._planner.get_state(),
                self._execution.name: self._execution.get_state(),
            }
