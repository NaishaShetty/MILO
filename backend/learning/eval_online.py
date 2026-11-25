"""
eval_online.py (backend/learning)

Online comparison of the rule-based reflector against the learned one (and the
shadow comparison), on the *held-out test scenes*, with identical seeds:

    cd backend
    python -m learning.eval_online --episodes 600 --model artifacts/outcome --out artifacts/online_eval.json

Every mode replays the same (scene, task, injected fault) per episode seed, so
differences come only from the reflector. Reports mission success, replans per
mission, wasted steps, mission time (simulated seconds), and -- for missions
the learned reflector aborted -- the share that the rule-based run also
failed ("would have failed anyway"). Also reports shadow-mode agreement.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.reflection_agent import ReflectionAgent
from execution.models import StepStatus
from learning.build_dataset import split_scenes
from learning.generate import make_faults, make_task
from learning.reflector import LearnedReflector
from learning.serving import OutcomePredictor, load_predictor
from learning.synthetic import SyntheticSimulator, make_scene
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner

PLANNERS = ["rule_based", "htn", "behavior_tree"]


def test_scenes(n_scenes: int = 50, seed: int = 0, test_frac: float = 0.2) -> List[str]:
    return split_scenes([f"scene_{i}" for i in range(n_scenes)], test_frac, seed)[1]


def run_one(
    episode: int,
    scene: str,
    mode: str,
    predictor: Optional[OutcomePredictor],
    seed: int = 0,
) -> Dict[str, Any]:
    rng = random.Random(f"eval-{seed}-{episode}")
    objects = make_scene(scene, seed)
    task, _ = make_task(rng, objects)
    faults = make_faults(rng, task)
    planner = rng.choice(PLANNERS)
    sim = SyntheticSimulator(objects, faults)
    kwargs: Dict[str, Any] = {}
    reflector: Optional[LearnedReflector] = None
    if mode != "rule" and predictor is not None:
        reflector = LearnedReflector(
            ReflectionAgent(), predictor, mode="on" if mode == "learned" else "shadow"
        )
        kwargs = {"reflection_agent": reflector, "outcome_predictor": predictor}
    orch = Orchestrator(
        PlannerAgentWrapper(create_planner(planner)), ExecutionAgentWrapper(sim), **kwargs  # type: ignore[arg-type]
    )
    decisions: List[Dict[str, Any]] = []
    if reflector is not None:
        original = reflector.pop_decisions

        def collect() -> List[Dict[str, Any]]:
            got = original()
            decisions.extend(got)
            return got

        reflector.pop_decisions = collect  # type: ignore[method-assign]
    state = orch.run(task, planner_type=planner)
    steps = [s for r in state.execution_history for s in r.step_results]
    dispatched = [
        s
        for s in steps
        if s.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.BLOCKED)
    ]
    failed = [s for s in dispatched if s.status != StepStatus.COMPLETED]
    ok = state.status.value == "succeeded"
    return {
        "episode": episode,
        "success": ok,
        "replans": orch._replans,
        "retries": orch._retries,
        "wasted_steps": len(failed) if ok else len(dispatched),
        "time_s": sim.clock_s,
        "fault": faults.kind,
        "aborted_by_model": any(
            d.get("used") and d.get("learned") == "abort" for d in decisions
        ),
        "decisions": decisions,
    }


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    n = max(len(rows), 1)
    return {
        "episodes": len(rows),
        "mission_success": sum(r["success"] for r in rows) / n,
        "replans_per_mission": sum(r["replans"] for r in rows) / n,
        "retries_per_mission": sum(r["retries"] for r in rows) / n,
        "wasted_steps_per_mission": sum(r["wasted_steps"] for r in rows) / n,
        "mean_time_s": statistics.mean(r["time_s"] for r in rows) if rows else 0.0,
    }


def evaluate(model: Path, episodes: int = 600, seed: int = 0) -> Dict[str, Any]:
    predictor = load_predictor(model)
    if predictor is None:
        raise SystemExit(f"no model found at {model}")
    scenes = test_scenes(seed=seed)
    runs: Dict[str, List[Dict[str, Any]]] = {
        m: [] for m in ("rule", "shadow", "learned")
    }
    for i in range(episodes):
        scene = scenes[i % len(scenes)]
        for mode in runs:
            runs[mode].append(run_one(i, scene, mode, predictor, seed))
    aborted = [i for i, r in enumerate(runs["learned"]) if r["aborted_by_model"]]
    shadow_decisions = [
        d
        for r in runs["shadow"]
        for d in r["decisions"]
        if d.get("learned") is not None
    ]
    return {
        "episodes": episodes,
        "test_scenes": scenes,
        "model_version": predictor.version,
        "rule_based": summarise(runs["rule"]),
        "shadow": summarise(runs["shadow"]),
        "learned": summarise(runs["learned"]),
        "aborted_by_learned": len(aborted),
        "aborted_would_have_failed_anyway": (
            sum(not runs["rule"][i]["success"] for i in aborted) / len(aborted)
            if aborted
            else None
        ),
        "shadow_agreement": (
            sum(d["agree"] for d in shadow_decisions) / len(shadow_decisions)
            if shadow_decisions
            else None
        ),
        "shadow_decisions_compared": len(shadow_decisions),
        "predictor_latency": predictor.latency_summary(),
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", type=Path, default=Path("artifacts/outcome"))
    parser.add_argument("--episodes", type=int, default=600)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("artifacts/online_eval.json"))
    args = parser.parse_args(argv)
    report = evaluate(args.model, args.episodes, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    for name in ("rule_based", "shadow", "learned"):
        print(name, {k: round(v, 3) for k, v in report[name].items()})
    print(
        {
            k: report[k]
            for k in (
                "aborted_by_learned",
                "aborted_would_have_failed_anyway",
                "shadow_agreement",
                "predictor_latency",
            )
        }
    )


if __name__ == "__main__":
    main()
