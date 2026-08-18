"""
run_benchmark.py (backend/planning_evaluation)

Purpose
-------
Phase E's planner-comparison axis: scores `RuleBasedPlanner`,
`BehaviorTreePlanner`, and `ReActPlanner` against every task in
`dataset/v1.0/tasks.json` on real AI2-THOR. Each episode restarts the
simulator (fresh Unity process per episode -- the "fresh scene per
episode" substitute `real_scenarios.py`/`run_floorplan_sweep.py`
already use, since `Simulator` has no object-teleportation
capability).

`ReActPlanner` baseline (Phase E follow-up)
--------------------------------------------------
Runs against Google's Gemini API (`LANGUAGE_LLM_PROVIDER=gemini` must
be set, `GEMINI_API_KEY` must be a real key -- see `language.config.
LLMRuntimeConfig.from_env()`) via `language.provider_factory.
create_llm_client()`, exactly the production wiring path, never a
benchmark-specific client. `REACT_MODEL_VERSION` records the exact
model string used (see `LLMRuntimeConfig.model`, default
`"gemini-flash-latest"`) for reproducibility -- Google's own
free-tier availability/eligibility for that model is controlled
entirely by Google, not this project.

Free-tier reality, handled honestly, not hidden: Gemini's API returned
intermittent `503 UNAVAILABLE` ("This model is currently experiencing
high demand") during real runs -- roughly 2 of 3 calls in an initial
3-call smoke test, with no relation to task content. `run_react_episode()`
retries an episode up to `REACT_MAX_TRANSIENT_RETRIES` additional times
ONLY when the planning failure looks like this specific transient
provider condition (`_is_transient_llm_error()` -- matches on `503`/
`UNAVAILABLE`/`429`/`RESOURCE_EXHAUSTED`/`rate limit`/`quota`, not on
any other planning failure), and every episode's `BenchmarkEpisodeResult.
llm_retry_attempts` records exactly how many extra attempts it took --
0 for every non-`react` planner and for any `react` episode that
succeeded first try. The final reported numbers are real outcomes
after this bounded, fully-logged retry policy, never a number silently
padded by unlimited retrying until something succeeds.

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
x 3 planners = 75 episodes, plus any transient-error retries):

    cd backend
    RUN_SIMULATOR_TESTS=true LANGUAGE_LLM_PROVIDER=gemini python -m planning_evaluation.run_benchmark

(`GEMINI_API_KEY` must already be set -- e.g. via `.env`. Without a
real key/provider configured, `react` episodes will fail immediately
with a real `ConfigurationError`/provider error, reported honestly
like any other real failure -- this script never fakes a client.)
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from language.config import LLMRuntimeConfig
from language.provider_factory import create_llm_client
from memory_evaluation.experiment_real import _seed_initial_state_from_live_metadata
from orchestration.task_runner import TaskRunner
from planner.behavior_tree import BehaviorTreePlanner
from planner.planner import Planner
from planner.react import ReActPlanner
from planner.rule_based import RuleBasedPlanner
from planning_evaluation.live_state import check_goal_live
from planning_evaluation.loader import BenchmarkTask, load_tasks
from simulator.simulator import Simulator

RESULTS_DIR = Path(__file__).resolve().parents[2] / "experiments" / "results"

#: Bounded, fully-logged retry budget for `react` episodes that fail
#: with a transient LLM-provider condition (see module docstring) --
#: never applied to `rule_based`/`behavior_tree`, which have no LLM
#: dependency to be transient about.
REACT_MAX_TRANSIENT_RETRIES = 2

#: Substrings identifying a transient LLM-provider condition (model
#: overloaded, rate limit, quota) worth one bounded retry, as opposed
#: to a real planning/parsing failure worth reporting as-is. Matched
#: case-insensitively against `PlanningResult.errors`.
_TRANSIENT_LLM_ERROR_MARKERS = (
    "503",
    "unavailable",
    "429",
    "resource_exhausted",
    "rate limit",
    "quota",
)


def _is_transient_llm_error(errors: List[str]) -> bool:
    joined = " ".join(errors).lower()
    return any(marker in joined for marker in _TRANSIENT_LLM_ERROR_MARKERS)


def _make_react_planner() -> ReActPlanner:
    client = create_llm_client(LLMRuntimeConfig.from_env())
    return ReActPlanner(llm_client=client)


#: Zero-arg factories so `rule_based`/`behavior_tree` (no constructor
#: args needed) and `react` (needs a real `LLMClient`, built from the
#: environment at call time -- see `_make_react_planner`) fit the same
#: uniform shape.
PLANNERS: Dict[str, Callable[[], Planner]] = {
    "rule_based": RuleBasedPlanner,
    "behavior_tree": BehaviorTreePlanner,
    "react": _make_react_planner,
}

#: Recorded in the report's `reproducibility` block -- resolved once
#: at import time so every episode's run reflects the exact same
#: configured provider/model, whatever `LANGUAGE_LLM_PROVIDER` is set
#: to when this script runs (`gemini` for the Phase E follow-up run;
#: informational only, never used to gate `react`'s presence in
#: `PLANNERS`).
_LLM_CONFIG = LLMRuntimeConfig.from_env()
REACT_LLM_PROVIDER = _LLM_CONFIG.provider
REACT_MODEL_VERSION = _LLM_CONFIG.model


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
    llm_retry_attempts: int = 0


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


def run_react_episode(planner: Planner, bt: BenchmarkTask) -> BenchmarkEpisodeResult:
    """
    `run_episode` wrapped with a bounded, fully-logged retry for
    `react` only -- see module docstring's "ReActPlanner baseline"
    section for why this exists and exactly what it does and does not
    retry. Every returned result's `llm_retry_attempts` records how
    many *extra* attempts (beyond the first) were used, so the raw
    numbers are auditable, not just the final pass/fail.
    """
    attempts = 0
    while True:
        result = run_episode("react", planner, bt)
        transient = not result.plan_success and _is_transient_llm_error(
            [result.failure_cause] if result.failure_cause else []
        )
        if not transient or attempts >= REACT_MAX_TRANSIENT_RETRIES:
            result.llm_retry_attempts = attempts
            return result
        attempts += 1
        time.sleep(3.0)  # brief pause before retrying an overloaded provider


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
    for planner_name, planner_factory in PLANNERS.items():
        planner = planner_factory()
        for bt in tasks:
            if planner_name == "react":
                result = run_react_episode(planner, bt)
            else:
                result = run_episode(planner_name, planner, bt)
            all_results.append(result)
            status = "GOAL_OK" if result.goal_success else "GOAL_FAIL"
            retries = f" retries={result.llm_retry_attempts}" if result.llm_retry_attempts else ""
            print(
                f"[{planner_name:>13}] [{bt.scene:>12}] {bt.task_id:<22} "
                f"{status:<9} exec={'OK' if result.execution_success else 'FAIL'} "
                f"({result.wall_clock_ms:.0f}ms){retries}"
                + (f"  cause={result.failure_cause}" if result.failure_cause else "")
            )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"milo_benchmark_{timestamp}.json"
    csv_path = RESULTS_DIR / f"milo_benchmark_{timestamp}_episodes.csv"

    episodes = [asdict(r) for r in all_results]
    react_results = [r for r in all_results if r.planner == "react"]
    report = {
        "reproducibility": {
            "generated_at_utc": timestamp,
            "dataset": "milo_benchmark v1.0",
            "simulator": "Simulator (real AI2-THOR/Unity, restarted between episodes)",
            "planners": list(PLANNERS.keys()),
            "react_llm_provider": REACT_LLM_PROVIDER,
            "react_llm_model": REACT_MODEL_VERSION,
            "react_transient_retry_policy": {
                "max_extra_attempts": REACT_MAX_TRANSIENT_RETRIES,
                "retry_trigger_markers": list(_TRANSIENT_LLM_ERROR_MARKERS),
                "episodes_that_needed_a_retry": sum(
                    1 for r in react_results if r.llm_retry_attempts > 0
                ),
                "total_extra_attempts_used": sum(
                    r.llm_retry_attempts for r in react_results
                ),
                "episodes_still_failing_after_all_retries": sum(
                    1
                    for r in react_results
                    if not r.plan_success and r.llm_retry_attempts >= REACT_MAX_TRANSIENT_RETRIES
                ),
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
