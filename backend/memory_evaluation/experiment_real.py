"""
experiment_real.py (backend/memory_evaluation)

Purpose
-------
Phase B (the post-8.7-audit follow-up): re-runs `experiment.py`'s
memory_on vs memory_off comparison against a REAL AI2-THOR `Simulator`
(`simulator.simulator.Simulator`, not `FakeSimulator`) and a real,
learned sentence-embedding model (`memory.embeddings.
SentenceTransformerEmbedder`, not the deterministic `HashingEmbedder`)
-- closing the two caveats `experiment.py`'s and `run_benchmark.py`'s
own docstrings, and the README's Known Limitations, documented: "this
benchmark runs on a FakeSimulator/HashingEmbedder, not production
AI2-THOR or a learned model."

Why a separate module rather than adding a `real=True` flag to
`experiment.py`
------------------------------------------------------------------------
`experiment.py`'s `run_scenario()` constructs a fresh `FakeSimulator`
per episode from an `EpisodeSpec.objects` list authored by hand
(`scenarios.py`) -- there is no equivalent "hand the simulator a scene"
call for real AI2-THOR (see `real_scenarios.py`'s docstring on why every
real episode instead runs against the same live `FloorPlan1`). Branching
`run_scenario()` internally on "fake vs real" would tangle two
genuinely different simulator-construction strategies into one function
with a boolean parameter deciding half its body -- clearer as two small,
parallel functions that both produce the same `EpisodeResult` shape (via
`experiment.EpisodeResult`, reused directly, never redefined) so
`run_benchmark.py`'s `_paired_deltas()`/CSV writer work unmodified on
either one's output.

Real-conditions caveats this module does NOT remove
------------------------------------------------------------
- Every episode runs against a single scene (`FloorPlan1`) -- no
  scene/object teleportation between episodes (see `real_scenarios.py`).
- `TaskRunner.run(..., initial_state=...)` (added alongside this module)
  is used here to seed each episode's `WorldState` with the target's
  REAL, live `isOpen` before planning -- without this, `WorldState.
  initial()`'s default (`is_open=None` for every object) means
  `rule_based.py`'s `_deposit()` fix has no real data to act on, and the
  production API path (which does not yet pass `initial_state`) still
  does not benefit from it end to end; see `docs/roadmap.md`'s
  "Vision-grounded WorldState" item for the general fix this narrow
  seam stands in for.
- A handful of episodes (`real_scenarios.ALL_REAL_SCENARIOS`) is a
  first real number, not a statistically powered study -- see
  `run_ablation_real.py`'s own "Statistical honesty" section.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from memory.embeddings import EmbeddingConfig
from memory_evaluation.experiment import Condition, EpisodeResult, _memory_was_used_in_plan
from memory_evaluation.real_scenarios import RealScenario
from orchestration.task_runner import TaskRunner
from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from simulator.simulator import Simulator

#: The embedding provider Phase B swaps in -- see `memory.embeddings`'s
#: own docstring for why `all-MiniLM-L6-v2` and why plain `transformers`
#: rather than the `sentence-transformers` package.
REAL_EMBEDDING_CONFIG = EmbeddingConfig(
    provider="sentence_transformer", dimension=384, model_name="", device="cpu"
)


def _build_real_memory_agent(database_dir: Path) -> MemoryAgent:
    config = MemoryConfig(
        enabled=True,
        database_path=database_dir / "memory.db",
        vector_store_path=database_dir / "vector_store",
    )
    return MemoryAgent.from_config(config, embedding_config=REAL_EMBEDDING_CONFIG)


def _seed_initial_state_from_live_metadata(
    task, metadata: Dict[str, Any]
) -> WorldState:
    """
    Builds a `WorldState` seeded with the REAL, current `isOpen` of
    every named receptacle this task references -- the "live AI2-THOR
    metadata scan by name" the README's Known Limitations already
    names as the (narrower) alternative to full Vision-grounded
    `WorldState`. Matches `execution.resolver.ObjectResolver`'s own
    matching rule (case-insensitive `objectType` equality) so "does
    this name resolve" and "what do we seed" never disagree.

    Only seeds `is_open` when AI2-THOR's own metadata says the object
    is `openable`: confirmed live that AI2-THOR reports `isOpen: False`
    on EVERY object, including non-openable ones (e.g. `CounterTop`) --
    not `None`/absent the way this project's own `WorldState.
    ObjectState` treats "no open/closed state at all". Skipping the
    `openable` check here first produced a real, reproduced bug: a
    `place` task targeting a countertop got seeded with a false
    `is_open=False`, `rule_based.py`'s `_deposit()` correctly (per its
    own contract) inserted an `open` step for what it was told was a
    closed container, and real AI2-THOR rejected it with `"CounterTop
    ... is not an Openable object"` -- a failure this harness caused by
    over-reading live metadata, not a planner bug.
    """
    state = WorldState.initial()
    referenced_names = {
        n for n in (task.object, task.target, task.target_location) if n
    }
    by_type: Dict[str, Dict[str, Any]] = {}
    for obj in metadata.get("objects") or []:
        obj_type = obj.get("objectType")
        if isinstance(obj_type, str):
            by_type[obj_type.strip().lower()] = obj

    for name in referenced_names:
        live = by_type.get(name.strip().lower())
        if live is not None and live.get("openable") and live.get("isOpen") is not None:
            state.object(name).is_open = bool(live["isOpen"])
    return state


def run_real_scenario(
    scenario: RealScenario,
    condition: Condition,
    database_dir: Path,
) -> List[EpisodeResult]:
    """
    Runs every episode in `scenario`, in order, under one condition,
    against a real AI2-THOR `Simulator` restarted between episodes
    (see `real_scenarios.py`'s docstring on why: no object-teleport
    capability exists to give each episode a distinct scene the way
    `FakeSimulator` can, so a fresh Unity process is this project's
    honest substitute for "a fresh, unmodified scene per episode").
    """
    memory_enabled = condition == "memory_on"
    agent = _build_real_memory_agent(database_dir) if memory_enabled else None

    results: List[EpisodeResult] = []
    for episode in scenario.episodes:
        simulator = Simulator()
        simulator.start()
        try:
            metadata = simulator.get_metadata()
            initial_state = _seed_initial_state_from_live_metadata(
                episode.task, metadata
            )
            runner = TaskRunner(RuleBasedPlanner(), simulator, memory_agent=agent)
            run_started = time.perf_counter()
            run_result = runner.run(
                episode.task,
                episode_id=str(uuid.uuid4()),
                memory_enabled=memory_enabled,
                initial_state=initial_state,
            )
            wall_clock_ms = (time.perf_counter() - run_started) * 1000.0

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
            latencies = dict(run_result.latencies_ms)
            latencies["wall_clock_ms"] = wall_clock_ms

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
                    latencies_ms=latencies,
                    total_latency_ms=sum(latencies.values()),
                )
            )
        finally:
            simulator.stop()
    return results


def run_real_scenario_both_conditions(
    scenario: RealScenario, base_dir: Path
) -> Dict[str, List[EpisodeResult]]:
    return {
        "memory_off": run_real_scenario(scenario, "memory_off", base_dir / "off"),
        "memory_on": run_real_scenario(scenario, "memory_on", base_dir / "on"),
    }
