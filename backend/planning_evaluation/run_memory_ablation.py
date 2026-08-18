"""
run_memory_ablation.py (backend/planning_evaluation)

Purpose
-------
Phase E's memory-conditioned axis: extends Phase B's real-AI2-THOR
memory_on vs memory_off comparison (`memory_evaluation.experiment_real`,
`FloorPlan1`-only) across the same scene diversity Phase D validated --
5 scenes, all 4 iTHOR room types, not just the one scene the original
Phase B ablation used. Reuses `memory_evaluation.experiment.
EpisodeResult`/`_memory_was_used_in_plan` and
`memory_evaluation.experiment_real`'s `_build_real_memory_agent`/
`_seed_initial_state_from_live_metadata` directly -- this module only
adds the missing `scene=` parameter `run_real_scenario` doesn't expose
(it always constructs `Simulator()`, implicitly `FloorPlan1`).

Design: same "find X twice" recall scenario per scene
------------------------------------------------------------
Mirrors `real_scenarios.REAL_CATEGORY_A_OBJECT_RECALL`'s design
(episode 1: find object with no prior memory; episode 2: find the same
object again, same scene) using `dataset/v1.0/tasks.json`'s first
`tier1_locate` task per scene as the target object -- reuses the
dataset rather than defining a second, disconnected task list. Under
`memory_on`, episode 2 should show `rule_based.py`'s
`_apply_memory_hint` effect (an extra `locate`/`navigate` step ahead of
the object itself, per that function's own "current perception
overrides stale memory" precedence rule); under `memory_off`, episode
2 looks identical to episode 1.

Output
------
Writes `experiments/results/milo_benchmark_memory_ablation_<timestamp>.json`
and a matching `_episodes.csv`, same convention as
`run_ablation_real.py`/`run_floorplan_sweep.py`/`run_benchmark.py`.

How to run
-----------
Opt-in gated (10 scenes-x-conditions-x-episodes = 20 real episodes):

    cd backend
    RUN_SIMULATOR_TESTS=true python -m planning_evaluation.run_memory_ablation
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List

from memory_evaluation.experiment import (
    Condition,
    EpisodeResult,
    _memory_was_used_in_plan,
)
from memory_evaluation.experiment_real import (
    _build_real_memory_agent,
    _seed_initial_state_from_live_metadata,
)
from orchestration.task_runner import TaskRunner
from planner.rule_based import RuleBasedPlanner
from planning_evaluation.loader import BenchmarkTask, load_tasks
from simulator.simulator import Simulator

RESULTS_DIR = Path(__file__).resolve().parents[2] / "experiments" / "results"


def _first_locate_task_per_scene() -> Dict[str, BenchmarkTask]:
    tasks = load_tasks()
    by_scene: Dict[str, BenchmarkTask] = {}
    for t in tasks:
        if t.difficulty_tier == "tier1_locate" and t.scene not in by_scene:
            by_scene[t.scene] = t
    return by_scene


def run_scene_condition(
    scene: str, room_type: str, bt, condition: Condition, database_dir: Path
) -> List[EpisodeResult]:
    memory_enabled = condition == "memory_on"
    agent = _build_real_memory_agent(database_dir) if memory_enabled else None

    results: List[EpisodeResult] = []
    for episode_label in ("episode_1_first_visit", "episode_2_recall"):
        task = bt.to_single_task()
        simulator = Simulator(scene=scene)
        simulator.start()
        try:
            metadata = simulator.get_metadata()
            initial_state = _seed_initial_state_from_live_metadata(task, metadata)
            runner = TaskRunner(RuleBasedPlanner(), simulator, memory_agent=agent)
            started = time.perf_counter()
            run_result = runner.run(
                task,
                episode_id=str(uuid.uuid4()),
                memory_enabled=memory_enabled,
                initial_state=initial_state,
            )
            wall_clock_ms = (time.perf_counter() - started) * 1000.0

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
            latencies = dict(run_result.latencies_ms)
            latencies["wall_clock_ms"] = wall_clock_ms

            results.append(
                EpisodeResult(
                    scenario_id=f"{scene}_{room_type}_recall",
                    category="A_object_location_recall",
                    seed=hash(scene) % 10_000,
                    condition=condition,
                    episode_label=episode_label,
                    task_id=task.task_id,
                    goal=task.goal,
                    object=task.object,
                    success=run_result.succeeded,
                    plan_success=run_result.planning_result.success,
                    action_count=action_count,
                    plan_step_count=len(plan_targets),
                    plan_targets=plan_targets,
                    memory_context_count=memory_context_count,
                    memory_used_in_plan=_memory_was_used_in_plan(
                        plan_targets, memory_context_count, task.object
                    ),
                    failure_cause=failure_cause,
                    recovered_from=None,
                    latencies_ms=latencies,
                    total_latency_ms=sum(latencies.values()),
                )
            )
        finally:
            simulator.stop()
    return results


def main() -> None:
    if os.environ.get("RUN_SIMULATOR_TESTS", "").lower() != "true":
        print(
            "Skipped: set RUN_SIMULATOR_TESTS=true to run this ablation "
            "(it launches a real AI2-THOR/Unity subprocess per episode)."
        )
        sys.exit(0)

    by_scene = _first_locate_task_per_scene()

    all_results: List[EpisodeResult] = []
    with TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        for scene, bt in by_scene.items():
            for condition in ("memory_off", "memory_on"):
                results = run_scene_condition(
                    scene, bt.room_type, bt, condition, base_dir / condition / scene
                )
                all_results.extend(results)
                for r in results:
                    print(
                        f"[{scene:>12}] [{condition:>11}] {r.episode_label:<22} "
                        f"success={r.success} memory_used={r.memory_used_in_plan} "
                        f"plan_steps={r.plan_step_count}"
                    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"milo_benchmark_memory_ablation_{timestamp}.json"
    csv_path = RESULTS_DIR / f"milo_benchmark_memory_ablation_{timestamp}_episodes.csv"

    episodes = [r.to_dict() for r in all_results]
    report = {
        "reproducibility": {
            "generated_at_utc": timestamp,
            "dataset": "milo_benchmark v1.0 (tier1_locate tasks, one per scene)",
            "simulator": "Simulator (real AI2-THOR/Unity, restarted between episodes)",
            "planner": "RuleBasedPlanner",
            "scenes": list(by_scene.keys()),
        },
        "episodes": episodes,
        "totals": {
            "total_episodes": len(all_results),
            "succeeded": sum(1 for r in all_results if r.success),
        },
    }

    json_path.write_text(json.dumps(report, indent=2, default=str))
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(episodes[0].keys()))
        writer.writeheader()
        writer.writerows(episodes)

    print()
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
