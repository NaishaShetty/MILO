"""
eval_goal_check.py (backend/verification)

How often does a mission *say* it succeeded while the world disagrees? Runs held-out
synthetic episodes (same scenes/tasks/faults as the learned-model evaluations) with goal
checking in `report` mode, and with and without the trace recorder to time its cost.

    cd backend
    python -m verification.eval_goal_check --episodes 300
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.eval_online import PLANNERS, test_scenes
from learning.generate import make_faults, make_task
from learning.synthetic import SyntheticSimulator, make_scene
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from tracelog.recorder import TraceRecorder
from tracelog.store import TraceStore


def run(episodes: int, seed: int = 0) -> Dict[str, Any]:
    os.environ["MILO_GOAL_CHECK"] = "report"
    scenes = test_scenes(seed=seed)
    rows: List[Dict[str, Any]] = []
    timing: Dict[str, List[float]] = {"no_trace": [], "trace": []}
    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(Path(tmp) / "t.db")
        for i in range(episodes):
            for mode in ("no_trace", "trace"):
                rng = random.Random(f"eval-{seed}-{i}")
                objects = make_scene(scenes[i % len(scenes)], seed)
                task, _ = make_task(rng, objects)
                faults = make_faults(rng, task)
                planner = rng.choice(PLANNERS)
                orch = Orchestrator(
                    PlannerAgentWrapper(create_planner(planner)),
                    ExecutionAgentWrapper(SyntheticSimulator(objects, faults)),  # type: ignore[arg-type]
                    trace_recorder=TraceRecorder(store) if mode == "trace" else None,
                )
                t0 = time.perf_counter()
                state = orch.run(task, planner_type=planner)
                timing[mode].append((time.perf_counter() - t0) * 1000.0)
                if mode == "trace":
                    trace = store.get(state.task_id) or {"records": []}
                    rows.append(
                        {
                            "goal": task.goal,
                            "fault": faults.kind,
                            "succeeded": state.status.value == "succeeded",
                            "checked": bool(state.verification),
                            "check_ok": all(v["ok"] for v in state.verification),
                            "records": len(trace["records"]),
                        }
                    )
    said_ok = [r for r in rows if r["succeeded"] and r["checked"]]
    false_ok = [r for r in said_ok if not r["check_ok"]]
    return {
        "episodes": len(rows),
        "mission_success_reported": sum(r["succeeded"] for r in rows) / len(rows),
        "successes_with_a_checkable_goal": len(said_ok),
        "successes_the_world_contradicts": len(false_ok),
        "contradicted_by_goal": dict(Counter(r["goal"] for r in false_ok)),
        "contradicted_by_fault": dict(Counter(r["fault"] for r in false_ok)),
        "trace_records_per_mission": statistics.mean(r["records"] for r in rows),
        "mission_ms_p50": {k: statistics.median(v) for k, v in timing.items()},
        "trace_overhead_ms_p50": statistics.median(timing["trace"])
        - statistics.median(timing["no_trace"]),
    }


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--episodes", type=int, default=300)
    p.add_argument("--out", type=Path, default=Path("artifacts/goal_check.json"))
    a = p.parse_args(argv)
    report = run(a.episodes)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
