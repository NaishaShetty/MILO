"""
experiment.py (backend/memory_evaluation)

Purpose
-------
The smallest reusable runner needed to answer Phase 6.4's central
question: "does enabling persistent memory change task performance,
efficiency, or failure recovery, compared with the identical robot
with the memory pathway switched off?"

The controlled interface (section 2 of the phase spec) already exists
in production code -- `orchestration.task_runner.TaskRunner.run(...,
memory_enabled=bool)` -- this module does not reimplement it. It only
adds: running a `scenarios.BenchmarkScenario` episode-by-episode under
one condition, and collecting the metrics section 7/8 of the spec asks
for into a plain, JSON-serializable record per episode.

MEMORY_ON vs MEMORY_OFF, concretely
------------------------------------
`memory_off` never constructs a `MemoryAgent` at all for the scenario
(`memory_agent=None` on every `TaskRunner`) -- no retrieval, no writes,
identical task/scene/planner/simulator otherwise. `memory_on`
constructs one real `MemoryAgent` (backed by a real `SQLiteMemoryStore`
+ `SQLiteVectorStore` under a scenario-scoped temporary directory) and
passes `memory_enabled=True` to every episode in the scenario, so
memory formed in episode N is available to episode N+1 -- exactly
`TaskRunner`'s own existing, tested contract (see
`tests/test_orchestration_task_runner.py::TestGoldenMemoryTest`).
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# `FakeSimulator` (backend/tests/_execution_test_helpers.py) is the
# same deterministic, zero-AI2THOR-dependency scene fake every Phase 5/
# 6.3 test already runs against -- reused here rather than duplicating
# ~190 lines of AI2-THOR-shaped scene mutation logic a second time.
# `tests/` has no `__init__.py` (a namespace package, matching this
# project's mypy `explicit_package_bases` convention), so it is not
# importable as `backend.tests....`; under pytest it works because
# pytest inserts each test file's directory onto `sys.path`, but this
# module is also imported by the standalone `run_benchmark` CLI
# (`cd backend && python -m memory_evaluation.run_benchmark`), which
# gets no such insertion for free -- hence the explicit bootstrap below.
_TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from _execution_test_helpers import FakeSimulator  # noqa: E402

from memory.agent import MemoryAgent, MemoryProvenance  # noqa: E402
from memory.config import MemoryConfig  # noqa: E402
from memory.retrieval import RankingWeights  # noqa: E402
from memory_evaluation.scenarios import BenchmarkScenario  # noqa: E402
from orchestration.task_runner import TaskRunner  # noqa: E402
from planner.rule_based import RuleBasedPlanner  # noqa: E402

Condition = Literal["memory_on", "memory_off"]


@dataclass
class EpisodeResult:
    """One episode's full, JSON-serializable outcome -- section 19's
    "prefer machine-readable output" applied at the finest grain this
    benchmark measures."""

    scenario_id: str
    category: str
    seed: int
    condition: str
    episode_label: str
    task_id: Optional[str]
    goal: Optional[str]
    object: Optional[str]

    success: bool
    plan_success: bool
    action_count: int
    plan_step_count: int
    plan_targets: List[Optional[str]]
    memory_context_count: int
    memory_used_in_plan: bool
    failure_cause: Optional[str]
    recovered_from: Optional[List[str]]

    latencies_ms: Dict[str, float] = field(default_factory=dict)
    total_latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _build_memory_agent(
    database_dir: Path, weights: Optional[RankingWeights] = None
) -> MemoryAgent:
    config = MemoryConfig(
        enabled=True,
        database_path=database_dir / "memory.db",
        vector_store_path=database_dir / "vector_store",
    )
    return MemoryAgent.from_config(config, weights=weights)


def _seed_preconditions(agent: MemoryAgent, scenario: BenchmarkScenario) -> None:
    """Seeds `scenario.preconditions` via `MemoryAgent.remember_observation`
    -- the same public write path a real observation uses, never a
    private/bypass insertion."""
    for subject, predicate, obj, confidence in scenario.preconditions:
        agent.remember_observation(
            subject,
            predicate,
            obj,
            provenance=MemoryProvenance.OBSERVATION,
            confidence=confidence,
        )


def _memory_was_used_in_plan(
    plan_targets: List[Optional[str]],
    memory_context_count: int,
    primary_object: Optional[str],
) -> bool:
    """
    A minimal, controlled "memory influence" signal (section 9): true
    only when memory was actually retrieved AND the plan's first target
    is not the task's own primary object -- i.e. the planner inserted a
    memory-suggested location step ahead of the object step itself
    (`planner.rule_based._apply_memory_hint`'s only observable effect).
    Does not merely check "memory was present" (section 9's explicit
    warning against that weaker signal, and a bug this function used to
    have: earlier revisions accepted only `memory_context_count`/
    `plan_targets` and returned `memory_context_count > 0 and
    len(plan_targets) > 0` -- true whenever ANY memory was retrieved
    for a non-empty plan, regardless of whether the plan's shape
    changed at all, contradicting this very docstring. Caught via the
    real-AI2-THOR ablation in `experiment_real.py`, where it was
    silently over-reporting "memory influenced the plan" for episodes
    whose plan was identical to the memory_off case.)
    """
    if memory_context_count == 0 or not plan_targets or not primary_object:
        return False
    first_target = (plan_targets[0] or "").strip().lower()
    return first_target != primary_object.strip().lower()


def run_scenario(
    scenario: BenchmarkScenario,
    condition: Condition,
    database_dir: Path,
    *,
    weights: Optional[RankingWeights] = None,
) -> List[EpisodeResult]:
    """
    Runs every episode in `scenario`, in order, under one condition.
    `database_dir` is scenario+condition-scoped (a fresh, empty memory
    subsystem per call) -- callers that want persistence-across-restart
    behavior pass the same `database_dir` again with a freshly
    constructed `MemoryAgent`, matching
    `TestPersistenceAcrossRestart`'s pattern; this function does not do
    that itself.
    """
    memory_enabled = condition == "memory_on"
    agent = (
        _build_memory_agent(database_dir, weights=weights) if memory_enabled else None
    )
    if agent is not None:
        _seed_preconditions(agent, scenario)

    results: List[EpisodeResult] = []
    for episode in scenario.episodes:
        simulator = FakeSimulator(
            objects=episode.objects, fail_actions=episode.fail_actions
        )
        runner = TaskRunner(RuleBasedPlanner(), simulator, memory_agent=agent)
        run_result = runner.run(
            episode.task,
            episode_id=str(uuid.uuid4()),
            memory_enabled=memory_enabled,
        )

        plan = run_result.planning_result.plan
        plan_targets = [s.target for s in plan.steps] if plan is not None else []
        action_count = (
            len(run_result.execution_record.step_results)
            if run_result.execution_record is not None
            else 0
        )
        memory_context_count = (
            len(run_result.memory_context.results)
            if run_result.memory_context is not None
            else 0
        )
        failure_cause = (
            run_result.failure_memory.metadata.get("cause")
            if run_result.failure_memory is not None
            else None
        )
        recovered_from = (
            run_result.episodic_memory.metadata.get("recovered_from")
            if run_result.episodic_memory is not None
            else None
        )

        results.append(
            EpisodeResult(
                scenario_id=scenario.scenario_id,
                category=scenario.category,
                seed=scenario.seed,
                condition=condition,
                episode_label=episode.label,
                task_id=episode.task.task_id,
                goal=episode.task.goal,
                object=episode.task.object,
                success=run_result.succeeded,
                plan_success=run_result.planning_result.success,
                action_count=action_count,
                plan_step_count=len(plan_targets),
                plan_targets=plan_targets,
                memory_context_count=memory_context_count,
                memory_used_in_plan=_memory_was_used_in_plan(
                    plan_targets, memory_context_count, episode.task.object
                ),
                failure_cause=failure_cause,
                recovered_from=recovered_from,
                latencies_ms=dict(run_result.latencies_ms),
                total_latency_ms=sum(run_result.latencies_ms.values()),
            )
        )
    return results


def run_scenario_both_conditions(
    scenario: BenchmarkScenario, base_dir: Path
) -> Dict[str, List[EpisodeResult]]:
    """Convenience wrapper: runs `scenario` under both conditions, each
    against its own fresh memory subsystem, and returns both result
    lists keyed by condition name."""
    return {
        "memory_off": run_scenario(scenario, "memory_off", base_dir / "off"),
        "memory_on": run_scenario(scenario, "memory_on", base_dir / "on"),
    }
