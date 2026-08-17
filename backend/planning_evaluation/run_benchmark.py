"""
run_benchmark.py (backend/planning_evaluation)

Purpose
-------
Phase E's planner-comparison axis: scores `RuleBasedPlanner` and
`BehaviorTreePlanner` against every task in `dataset/v1.0/tasks.json`
on real AI2-THOR (`ReActPlanner` is deliberately excluded -- see
`dataset/v1.0/README.md`'s "Known limitations": this sandbox has no
LLM API key configured, and this project's own policy is to report an
honest "not runnable here" rather than a degraded or fabricated
number). Each episode restarts the simulator (fresh Unity process per
episode -- the "fresh scene per episode" substitute
`real_scenarios.py`/`run_floorplan_sweep.py` already use, since
`Simulator` has no object-teleportation capability).

Two independent success signals per episode, both recorded (see
`live_state.py`'s docstring for why they can disagree):
- `execution_success`: `TaskRunResult.succeeded` -- did every
  dispatched step complete without a simulator error.
- `goal_success`: `live_state.check_goal_live()` -- does the task's
  goal condition actually hold in the live scene after execution, per
  AI2-THOR's own object fields. This is the benchmark's primary score;
  `execution_success` is reported alongside it because the two are not
  the same claim (a plan can execute every step without a dispatch
  error and still not satisfy the goal, and vice versa is not possible
  for this task set but is not assumed).

Output
------
Writes `experiments/results/milo_benchmark_<timestamp>.json` (full
per-episode detail, `reproducibility` metadata block, per-planner and
per-tier summaries) and a matching `_episodes.csv`, same convention as
`memory_evaluation/run_ablation_real.py` and `run_floorplan_sweep.py`.

How to run
-----------
Opt-in gated (launches a real Unity subprocess per episode -- 25 tasks
x 2 planners = 50 episodes):

    cd backend
    RUN_SIMULATOR_TESTS=true python -m planning_evaluation.run_benchmark
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_evaluation.experiment_real import _seed_initial_state_from_live_metadata
from orchestration.task_runner import TaskRunner
from planner.behavior_tree import BehaviorTreePlanner
from planner.planner import Planner
from planner.rule_based import RuleBasedPlanner
from planning_evaluation.live_state import check_goal_live
from planning_evaluation.loader import BenchmarkTask, load_tasks
from simulator.simulator import Simulator

RESULTS_DIR = Path(__file__).resolve().parents[2] / "experiments" / "results"

#: `ReActPlanner` intentionally omitted -- see module docstring.
PLANNERS: Dict[str, "type[Planner]"] = {
    "rule_based": RuleBasedPlanner,
    "behavior_tree": BehaviorTreePlanner,
}


@dataclass
class BenchmarkEpisodeResult:
    planner: str
    task_id: str
    scene: str
    room_type: str
    difficulty_tier: str
    instruction: str
    goal: Optional[str]
    object: Optional[str]
    target: Optional[str]
    plan_success: bool
    execution_success: bool
    goal_success: Optional[bool]
    action_count: int
    plan_step_count: int
    failure_cause: Optional[str]
    wall_clock_ms: float


def run_episode(planner_name: str, planner: Planner, bt: BenchmarkTask) -> BenchmarkEpisodeResult:
    task = bt.to_single_task()
    simulator = Simulator(scene=bt.scene)
    simulator.start()
    try:
        pre_metadata = simulator.get_metadata()
        initial_state = _seed_initial_state_from_live_metadata(task, pre_metadata)
        runner = TaskRunner(planner, simulator)
        started = time.perf_counter()
        run_result = runner.run(
            task,
            episode_id=str(uuid.uuid4()),
            memory_enabled=False,
            initial_state=initial_state,
        )
        wall_clock_ms = (time.perf_counter() - started) * 1000.0

        post_metadata = simulator.get_metadata()
        goal_success = check_goal_live(task, post_metadata)

        plan = run_result.planning_result.plan
        plan_targets = [s.target for s in plan.steps] if plan is not None else []
        action_count = (
            len(run_result.execution_record.step_results)
            if run_result.execution_record is not None
            else 0
        )
        failure_cause = None
        if run_result.execution_record is not None:
            for step in run_result.execution_record.step_results:
                if step.error is not None:
                    failure_cause = step.error.message
                    break
        if failure_cause is None and not run_result.planning_result.success:
            failure_cause = "; ".join(run_result.planning_result.errors) or "planning failed"

        return BenchmarkEpisodeResult(
            planner=planner_name,
            task_id=bt.task_id,
            scene=bt.scene,
            room_type=bt.room_type,
            difficulty_tier=bt.difficulty_tier,
            instruction=bt.instruction,
            goal=task.goal,
            object=task.object,
            target=task.target,
            plan_success=run_result.planning_result.success,
            execution_success=run_result.succeeded,
            goal_success=goal_success,
            action_count=action_count,
            plan_step_count=len(plan_targets),
            failure_cause=failure_cause,
            wall_clock_ms=wall_clock_ms,
        )
    except Exception as exc:  # noqa: BLE001 -- record, don't abort the run
        return BenchmarkEpisodeResult(
            planner=planner_name,
            task_id=bt.task_id,
            scene=bt.scene,
            room_type=bt.room_type,
            difficulty_tier=bt.difficulty_tier,
            instruction=bt.instruction,
            goal=bt.goal,
            object=bt.object,
            target=bt.target,
            plan_success=False,
            execution_success=False,
            goal_success=False,
            action_count=0,
            plan_step_count=0,
            failure_cause=f"harness_exception: {exc!r}",
            wall_clock_ms=0.0,
        )
    finally:
        simulator.stop()


def _summarize(results: List[BenchmarkEpisodeResult]) -> Dict[str, Any]:
    def rate(rows: List[BenchmarkEpisodeResult]) -> Dict[str, Any]:
        n = len(rows)
        goal_ok = sum(1 for r in rows if r.goal_success)
        exec_ok = sum(1 for r in rows if r.execution_success)
        return {
            "n": n,
            "goal_success_rate": goal_ok / n if n else None,
            "execution_success_rate": exec_ok / n if n else None,
        }

    by_planner: Dict[str, Any] = {}
    for planner_name in PLANNERS:
        rows = [r for r in results if r.planner == planner_name]
        by_planner[planner_name] = {
            "overall": rate(rows),
            "by_tier": {
                tier: rate([r for r in rows if r.difficulty_tier == tier])
                for tier in sorted({r.difficulty_tier for r in rows})
            },
        }
    return by_planner


def main() -> None:
    if os.environ.get("RUN_SIMULATOR_TESTS", "").lower() != "true":
        print(
            "Skipped: set RUN_SIMULATOR_TESTS=true to run this benchmark "
            "(it launches a real AI2-THOR/Unity subprocess per episode)."
        )
        sys.exit(0)

    tasks = load_tasks()
    all_results: List[BenchmarkEpisodeResult] = []
    for planner_name, planner_cls in PLANNERS.items():
        planner = planner_cls()
        for bt in tasks:
            result = run_episode(planner_name, planner, bt)
            all_results.append(result)
            status = "GOAL_OK" if result.goal_success else "GOAL_FAIL"
            print(
                f"[{planner_name:>13}] [{bt.scene:>12}] {bt.task_id:<22} "
                f"{status:<9} exec={'OK' if result.execution_success else 'FAIL'} "
                f"({result.wall_clock_ms:.0f}ms)"
                + (f"  cause={result.failure_cause}" if result.failure_cause else "")
            )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"milo_benchmark_{timestamp}.json"
    csv_path = RESULTS_DIR / f"milo_benchmark_{timestamp}_episodes.csv"

    episodes = [asdict(r) for r in all_results]
    report = {
        "reproducibility": {
            "generated_at_utc": timestamp,
            "dataset": "milo_benchmark v1.0",
            "simulator": "Simulator (real AI2-THOR/Unity, restarted between episodes)",
            "planners": list(PLANNERS.keys()),
            "planners_excluded": {
                "react": "No LLM API key configured in this environment "
                "(OPENAI_API_KEY/GEMINI_API_KEY/etc unset); reported honestly "
                "rather than run in a degraded fallback mode."
            },
            "memory_enabled": False,
        },
        "summary_by_planner": _summarize(all_results),
        "episodes": episodes,
        "totals": {
            "total_episodes": len(all_results),
            "goal_succeeded": sum(1 for r in all_results if r.goal_success),
            "execution_succeeded": sum(1 for r in all_results if r.execution_success),
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
    print(json.dumps(report["summary_by_planner"], indent=2))


if __name__ == "__main__":
    main()
