"""
task_runner.py (backend/orchestration)

Status: legacy single-attempt entry point
------------------------------------------------
`orchestration.orchestrator.Orchestrator` is the current, actively
developed entry point for running a task -- it does everything
`TaskRunner` does, plus reflection-driven, bounded replanning on
failure (see `orchestrator.py`'s own "Relationship to
`orchestration.task_runner.TaskRunner`" docstring section for the exact
capability delta). New callers should use `Orchestrator`.

`TaskRunner` is kept, not removed, because it is still a live
dependency: `memory_evaluation/experiment.py` and
`memory_evaluation/memory_size.py` drive their benchmarks directly
through its single-attempt `run()` (the multi-attempt replanning loop
`Orchestrator` adds is not part of what those benchmarks measure), and
`tests/test_orchestration_task_runner.py` exercises it directly. Treat
it as a frozen, single-attempt implementation detail of the memory
evaluation harness, not a second general-purpose orchestration surface
-- do not add new features here; add them to `Orchestrator` instead.

Purpose
-------
`TaskRunner.run()` is the closed causal loop the phase spec's core
principle demands:

```
SingleTask
    -> MemoryAgent.retrieve_relevant_memories()   (memory_context)
    -> Planner.plan(task, state, memory_context)  (Plan, possibly
                                                     memory-conditioned)
    -> ExecutionController.execute_plan()          (ExecutionRecord)
    -> MemoryAgent.remember_episode()/remember_failure()/
       remember_observation()                      (persisted Memory)
```

See `backend/orchestration/__init__.py`'s module docstring for why this
translation lives here rather than inside `planner/`, `execution/`, or
`memory/`.

Episode lifecycle (section 14)
-------------------------------
One `episode_id` (UUID4, minted at the start of `run()` unless the
caller supplies one -- e.g. to correlate the current run with a
previous one in a test) is threaded through the `MemoryQueryContext`
used for retrieval, `Plan.metadata["memory_context"]` (via the
planner's own `_finalize()`), and every `Memory.episode_id` this run
writes -- "the same task/episode identifiers propagated through
task -> planner -> executor -> memory," per section 14, without
inventing a new identifier scheme: `task.task_id` (Phase 3's own
identifier) is threaded through unchanged as `Memory.task_id`.

Memory is optional and safe (section 5)
-------------------------------------------
`memory_agent=None` or `memory_enabled=False` skips every memory
operation -- retrieval is simply never called (`memory_context stays
None`, and every `Planner.plan()` call already treats a `None`
`memory_context` as "plan normally," per `planner/planner.py`'s own
docstring) and no memory is written after execution. `MemoryAgent`
itself never raises (see `memory/agent.py`'s docstring), so
`TaskRunner` needs no additional try/except around any memory call --
the "graceful degradation" contract is enforced one layer down, once,
not re-implemented here.

What creates a memory, exactly (section 13 -- "document which events
create memories")
------------------------------------------------------------------------
- **Planning failure** (`PlanningResult.success is False`, no
  `ExecutionRecord` was ever produced) -> one `FAILURE` memory, `cause=
  None` (rendered "unknown" -- there is no execution evidence yet, only
  a validation/generation failure whose messages become `failure_
  reason`).
- **`ExecutionStatus.SUCCESS`** -> one `EPISODIC` memory
  (`remember_episode`), always. If a matching prior, unresolved
  `FAILURE` memory exists for this task (`_find_unresolved_failures`),
  it is linked via `MemoryAgent.link_recovery()` -- section 11.
  Additionally, **at most one** `SEMANTIC` observation is formed via
  `_form_observation()` -- see that method's docstring for the exact,
  narrow trigger condition. Nothing else about the run (no per-step
  detail, no raw simulator metadata) is ever persisted as semantic
  memory.
- **Any other `ExecutionStatus`** (`FAILED`/`CANCELLED`) -> one
  `FAILURE` memory (`remember_failure`), built only from the first
  `FAILED` step's actual `ExecutionError` (never invented -- section
  10's explicit "do NOT hallucinate a cause" -- `cause=None` when no
  step recorded one).

No other event in this module ever calls a `remember_*` method. In
particular, nothing here persists per-step detail, per-frame
observations, or intermediate planning state -- section 13's "avoid
memory pollution."
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from execution.controller import ExecutionController
from execution.models import ExecutionRecord, ExecutionStatus, StepStatus
from execution.resolver import ObjectResolver
from memory.agent import MemoryAgent, MemoryQueryContext, PlannerMemoryContext
from memory.models import Memory, MemoryProvenance, MemoryType
from memory.semantics import EpisodicDetails, FailureDetails
from planner.models import PlanningResult
from planner.planner import Planner
from planner.state import WorldState
from schemas.task import SingleTask

logger = logging.getLogger(__name__)

#: Confidence assigned to a `location` observation formed from
#: simulator ground truth (`_form_observation`) -- high, but not 1.0,
#: since a single successful task completion is one data point, not a
#: verified-repeatedly fact (see `memory.retrieval`'s provenance/
#: confidence ranking, which already discounts a lone `OBSERVATION`
#: relative to a repeatedly-confirmed one via `conflicts.
#: store_semantic_observation`'s duplicate tagging).
_OBSERVATION_CONFIDENCE = 0.85


@dataclass
class TaskRunResult:
    """
    Everything one `TaskRunner.run()` call produced -- returned, never
    partially discarded, so a caller (a test, a future higher-level
    orchestrator) can inspect every stage of the loop after the fact.
    """

    task: SingleTask
    episode_id: str
    memory_context: Optional[PlannerMemoryContext]
    planning_result: PlanningResult
    execution_record: Optional[ExecutionRecord]
    episodic_memory: Optional[Memory] = None
    failure_memory: Optional[Memory] = None
    observation_memories: List[Memory] = field(default_factory=list)
    latencies_ms: Dict[str, float] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return (
            self.execution_record is not None
            and self.execution_record.status == ExecutionStatus.SUCCESS
        )


class TaskRunner:
    """
    Ties `Planner`, `ExecutionController`, and `MemoryAgent` into one
    task/episode lifecycle. See this module's docstring for the full
    loop and memory-formation policy.
    """

    def __init__(
        self,
        planner: Planner,
        simulator: Any,
        memory_agent: Optional[MemoryAgent] = None,
    ) -> None:
        self._planner = planner
        self._simulator = simulator
        self._memory_agent = memory_agent
        self._resolver = ObjectResolver()

    def run(
        self,
        task: SingleTask,
        *,
        episode_id: Optional[str] = None,
        memory_enabled: bool = True,
        top_k: int = 5,
        initial_state: Optional[WorldState] = None,
    ) -> TaskRunResult:
        """
        `initial_state`, when supplied, replaces the default
        `WorldState.initial()` -- the narrow, opt-in seam for a caller
        that already has real state to plan against (e.g.
        `memory_evaluation/run_ablation_real.py` scanning a live
        `Simulator.get_metadata()` for each task's target's current
        `isOpen` before planning, so the rule-based planner's
        state-aware `open`-before-`place` logic -- see `rule_based.
        py`'s `_deposit()` -- actually has real data to act on). Never
        used by `None` (the default): every other caller keeps today's
        "always plan from a symbolically fresh state" behavior
        unchanged, since full Vision-grounded `WorldState` construction
        for the production API path is separately tracked future work
        (see `docs/roadmap.md`), not something this parameter attempts
        to solve generally.
        """
        episode_id = episode_id or str(uuid.uuid4())
        latencies: Dict[str, float] = {}
        agent = self._memory_agent if memory_enabled else None

        memory_context = self._retrieve(task, episode_id, agent, top_k, latencies)

        state = initial_state if initial_state is not None else WorldState.initial()
        started = time.perf_counter()
        planning_result = self._planner.plan(task, state, memory_context)
        latencies["planning_ms"] = (time.perf_counter() - started) * 1000.0

        if not planning_result.success or planning_result.plan is None:
            failure_memory = self._remember_planning_failure(
                task, episode_id, planning_result, agent
            )
            return TaskRunResult(
                task=task,
                episode_id=episode_id,
                memory_context=memory_context,
                planning_result=planning_result,
                execution_record=None,
                failure_memory=failure_memory,
                latencies_ms=latencies,
            )

        controller = ExecutionController(self._simulator)
        record = controller.load_plan(planning_result.plan)
        started = time.perf_counter()
        record = controller.execute_plan(planning_result.plan, state, record=record)
        latencies["execution_ms"] = (time.perf_counter() - started) * 1000.0

        result = TaskRunResult(
            task=task,
            episode_id=episode_id,
            memory_context=memory_context,
            planning_result=planning_result,
            execution_record=record,
            latencies_ms=latencies,
        )
        if agent is not None:
            started = time.perf_counter()
            self._remember_execution_outcome(
                task, episode_id, record, state, agent, result
            )
            latencies["memory_write_ms"] = (time.perf_counter() - started) * 1000.0
        return result

    # -- retrieval ------------------------------------------------------

    def _retrieve(
        self,
        task: SingleTask,
        episode_id: str,
        agent: Optional[MemoryAgent],
        top_k: int,
        latencies: Dict[str, float],
    ) -> Optional[PlannerMemoryContext]:
        if agent is None:
            return None
        query_context = MemoryQueryContext(
            task_id=task.task_id,
            episode_id=episode_id,
            goal=task.goal,
            object=task.object,
            target=task.target,
        )
        started = time.perf_counter()
        memory_context = agent.retrieve_relevant_memories(query_context, top_k=top_k)
        latencies["memory_retrieval_ms"] = (time.perf_counter() - started) * 1000.0
        return memory_context

    # -- memory formation -------------------------------------------------

    def _remember_planning_failure(
        self,
        task: SingleTask,
        episode_id: str,
        planning_result: PlanningResult,
        agent: Optional[MemoryAgent],
    ) -> Optional[Memory]:
        if agent is None:
            return None
        reasons = list(planning_result.errors)
        if planning_result.validation is not None:
            reasons.extend(issue.message for issue in planning_result.validation.issues)
        details = FailureDetails(
            task=task.goal or "unknown",
            action="plan",
            failure_reason="; ".join(reasons) or "planning failed",
            cause=None,
            recovery=None,
            outcome="failed",
        )
        return agent.remember_failure(
            details, episode_id=episode_id, task_id=task.task_id
        )

    def _remember_execution_outcome(
        self,
        task: SingleTask,
        episode_id: str,
        record: ExecutionRecord,
        state: WorldState,
        agent: MemoryAgent,
        result: TaskRunResult,
    ) -> None:
        if record.status == ExecutionStatus.SUCCESS:
            recovered_ids = self._find_unresolved_failures(task, agent)
            details = EpisodicDetails(
                task_summary=task.goal or "unknown",
                outcome="success",
                location=state.robot_location,
                duration_seconds=(
                    record.duration_ms / 1000.0
                    if record.duration_ms is not None
                    else None
                ),
                relevant_objects=[v for v in (task.object, task.target) if v],
            )
            result.episodic_memory = agent.remember_episode(
                details,
                episode_id=episode_id,
                task_id=task.task_id,
                recovered_failure_ids=recovered_ids or None,
            )
            observation = self._form_observation(task, episode_id, agent)
            if observation is not None:
                result.observation_memories.append(observation)
            return

        failing_step = next(
            (s for s in record.step_results if s.status == StepStatus.FAILED), None
        )
        cause = None
        error_code = None
        action_name = "unknown"
        if failing_step is not None:
            action_name = failing_step.action
            if failing_step.error is not None:
                cause = failing_step.error.message
                error_code = failing_step.error.code.value
        failure_details = FailureDetails(
            task=task.goal or "unknown",
            action=action_name,
            failure_reason=cause or "execution failed",
            cause=cause,
            recovery=None,
            outcome=record.status.value,
            error_code=error_code,
        )
        result.failure_memory = agent.remember_failure(
            failure_details, episode_id=episode_id, task_id=task.task_id
        )

    def _find_unresolved_failures(
        self, task: SingleTask, agent: MemoryAgent
    ) -> List[str]:
        """
        Finds prior `FAILURE` memories for this same task that have not
        already been linked to a successful recovery -- section 11's
        "if a task initially fails but later succeeds, preserve the
        failure experience" linkage. Matched by `task_id` when the
        task was retried under the same identifier, else by the
        primary object -- both are exact-match structural checks, never
        a fabricated association.
        """
        query_context = MemoryQueryContext(
            task_id=task.task_id, goal=task.goal, object=task.object
        )
        context = agent.retrieve_relevant_memories(
            query_context, memory_types=[MemoryType.FAILURE], top_k=10
        )
        unresolved = []
        for result in context.results:
            memory = result.memory
            if memory.metadata.get("recovered_by") is not None:
                continue
            same_task = task.task_id is not None and memory.task_id == task.task_id
            same_object = bool(task.object) and memory.metadata.get("task") == task.goal
            if same_task or same_object:
                unresolved.append(memory.memory_id)
        return unresolved

    def _form_observation(
        self, task: SingleTask, episode_id: str, agent: MemoryAgent
    ) -> Optional[Memory]:
        """
        The one, narrow, event-driven path from a simulator observation
        to a `SEMANTIC` memory (section 12/13). Triggers only when
        ALL of the following hold: the task named a primary object; the
        task just completed successfully; that object resolves to a
        live simulator object; and that object's AI2-THOR receptacle
        metadata (real ground truth this project's `Simulator`/
        `FakeSimulator` already expose -- never inferred or guessed)
        names another live object. Everything else about the final
        scene (every other object, every non-primary detection) is
        deliberately never touched -- this is not a scene dump.

        Prefers `parentReceptacles` (plural, a list) over the singular
        `parentReceptacle` this originally read exclusively -- a real,
        confirmed AI2-THOR 5.0.0 behavior found investigating why this
        pathway never engaged against real AI2-THOR (Phase B, Phase E):
        `parentReceptacle` (singular) is `None` for every object tested
        across all 5 of Phase D's scenes, even loose objects resting
        directly on a real, populated receptacle, but `parentReceptacles`
        (plural) reliably names that same receptacle every time (e.g.
        FloorPlan1's mug: `parentReceptacle=None`,
        `parentReceptacles=['CounterTop|...']`). When an object lists
        more than one candidate (observed for `FloorPlan201`'s laptop,
        which touches two chairs and a dining table simultaneously),
        the first entry is used -- a deterministic choice from AI2-THOR's
        own real list, not a guess, matching `execution.resolver.
        ObjectResolver`'s own "pick one deterministically from ground
        truth, never fabricate" precedent. Synthetic `FakeSimulator`
        scenarios (`memory_evaluation/scenarios.py`,
        `tests/_execution_test_helpers.py`) only ever populate the
        singular field, so it remains the fallback -- this widens what
        real AI2-THOR can trigger without changing any existing
        `FakeSimulator`-based test's behavior.
        """
        if not task.object:
            return None
        try:
            metadata = self._simulator.get_metadata()
        except Exception:
            logger.warning("task_runner.observation_metadata_failed", exc_info=True)
            return None

        object_id = self._resolver.resolve(task.object, metadata)
        if object_id is None:
            return None
        objects = metadata.get("objects") or []
        obj = next((o for o in objects if o.get("objectId") == object_id), None)
        if obj is None:
            return None
        parent_receptacles = obj.get("parentReceptacles")
        if isinstance(parent_receptacles, list) and parent_receptacles:
            receptacle_id = parent_receptacles[0]
        else:
            receptacle_id = obj.get("parentReceptacle")
        if not receptacle_id or not isinstance(receptacle_id, str):
            return None
        receptacle = next(
            (o for o in objects if o.get("objectId") == receptacle_id), None
        )
        if receptacle is None or not isinstance(receptacle.get("objectType"), str):
            return None

        return agent.remember_observation(
            task.object.strip().lower(),
            "located_on",
            receptacle["objectType"].strip().lower(),
            provenance=MemoryProvenance.OBSERVATION,
            confidence=_OBSERVATION_CONFIDENCE,
            episode_id=episode_id,
            task_id=task.task_id,
        )
