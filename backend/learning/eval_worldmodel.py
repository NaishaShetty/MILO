"""
eval_worldmodel.py (backend/learning)

Phase F: train the transition model on the Phase A training split and evaluate

 1. next-state accuracy on held-out scenes vs "nothing changes" (and, per field, vs the
    majority class), and
 2. whether rollout-aware plan scoring helps *missions*: the same held-out episodes run
    with no ranking (default planner), the static ranker (Phase B) and the rollout ranker,
    with identical seeds/faults.

    cd backend
    python -m learning.eval_worldmodel --data data/dataset --model artifacts/outcome --out artifacts/worldmodel
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.eval_online import PLANNERS, test_scenes
from learning.generate import make_faults, make_task
from learning.predictor_features import context_from_row
from learning.ranker import PlanRanker, score_plan
from learning.serving import load_predictor
from learning.synthetic import Faults, SyntheticSimulator, make_scene
from learning.train_outcome import load_rows
from learning.worldmodel import (
    FIELDS,
    WorldModel,
    after_targets,
    before_state,
    rollout_score,
)
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from planner.state import WorldState


def transition_report(
    model: WorldModel, rows: List[Dict[str, Any]], train_rows
) -> Dict:
    pred = model.predict_many([context_from_row(r) for r in rows])
    gold = [after_targets(r) for r in rows]
    base = [before_state(r) for r in rows]
    majority = {
        f: Counter(after_targets(r)[f] for r in train_rows).most_common(1)[0][0]
        for f in FIELDS
    }
    changed = {
        f: [i for i in range(len(rows)) if gold[i][f] != base[i][f]] for f in FIELDS
    }
    out: Dict[str, Any] = {"rows": len(rows)}
    for f in FIELDS:
        n = len(rows)
        out[f] = {
            "learned_acc": sum(pred[i][f] == gold[i][f] for i in range(n)) / n,
            "copy_before_acc": sum(base[i][f] == gold[i][f] for i in range(n)) / n,
            "majority_acc": sum(majority[f] == gold[i][f] for i in range(n)) / n,
            "rows_where_state_changes": len(changed[f]),
            "learned_acc_on_changes": (
                sum(pred[i][f] == gold[i][f] for i in changed[f]) / len(changed[f])
                if changed[f]
                else None
            ),
        }
    return out


def run_one(
    i: int, scene: str, mode: str, predictor, world, seed: int
) -> Dict[str, Any]:
    rng = random.Random(f"eval-{seed}-{i}")
    objects = make_scene(scene, seed)
    task, _ = make_task(rng, objects)
    faults = make_faults(rng, task)
    planner = rng.choice(PLANNERS)
    sim = SyntheticSimulator(objects, faults)
    kwargs: Dict[str, Any] = {}
    if mode == "static":
        kwargs = {"outcome_predictor": predictor, "plan_ranker": PlanRanker(predictor)}
    elif mode == "rollout":
        kwargs = {
            "outcome_predictor": predictor,
            "plan_ranker": PlanRanker(predictor, world_model=world),
        }
    orch = Orchestrator(
        PlannerAgentWrapper(create_planner(planner)),
        ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
        planner_factory=lambda n: PlannerAgentWrapper(create_planner(n)),
        **kwargs,
    )
    state = orch.run(task, planner_type=planner)
    chosen = (
        (state.current_plan.metadata.get("ranking") or {}).get("chosen")
        if state.current_plan
        else None
    )
    return {
        "success": state.status.value == "succeeded",
        "replans": orch._replans,
        "time_s": sim.clock_s,
        "switched": bool(chosen and chosen != planner),
    }


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    n = max(len(rows), 1)
    return {
        "episodes": len(rows),
        "mission_success": sum(r["success"] for r in rows) / n,
        "replans_per_mission": sum(r["replans"] for r in rows) / n,
        "mean_time_s": statistics.mean(r["time_s"] for r in rows) if rows else 0.0,
        "plan_switched": sum(r["switched"] for r in rows) / n,
    }


def evaluate(
    data: Path, model_dir: Path, out: Path, episodes: int, seed: int = 0
) -> Dict[str, Any]:
    train = load_rows(data / "train.csv")
    test = load_rows(data / "test.csv")
    world = WorldModel.fit(
        [context_from_row(r) for r in train], [after_targets(r) for r in train]
    )
    out.mkdir(parents=True, exist_ok=True)
    world.save(out / "world.pkl")
    report: Dict[str, Any] = {"transition": transition_report(world, test, train)}
    predictor = load_predictor(model_dir)
    if predictor is None:
        raise SystemExit(f"no outcome model at {model_dir}")
    scenes = test_scenes(seed=seed)
    runs: Dict[str, List[Dict[str, Any]]] = {"none": [], "static": [], "rollout": []}
    for i in range(episodes):
        for mode in runs:
            runs[mode].append(
                run_one(i, scenes[i % len(scenes)], mode, predictor, world, seed)
            )
    report["missions"] = {m: summarise(r) for m, r in runs.items()}
    # Does the plan score predict whether the mission succeeds? (default planner's plan,
    # scored against the starting state, static vs rolled-out), plus how often each plan
    # differs between planners at all -- ranking can only help when they do.
    from sklearn.metrics import roc_auc_score

    ys: List[int] = []
    static_s: List[float] = []
    roll_s: List[float] = []
    differing = 0
    for i in range(episodes):
        rng = random.Random(f"eval-{seed}-{i}")
        objects = make_scene(scenes[i % len(scenes)], seed)
        task, _ = make_task(rng, objects)
        make_faults(rng, task)
        name = rng.choice(PLANNERS)
        meta = SyntheticSimulator(objects, Faults()).get_metadata()
        plans = {}
        for n in PLANNERS:
            res = PlannerAgentWrapper(create_planner(n)).plan(
                task, WorldState.initial(), None
            )
            if res.success and res.plan:
                plans[n] = res.plan
        if name not in plans:
            continue
        ys.append(int(runs["none"][i]["success"]))
        static_s.append(score_plan(plans[name], predictor, meta, name))
        roll_s.append(rollout_score(plans[name], predictor, world, meta, name))
        differing += len({tuple(s.action for s in p.steps) for p in plans.values()}) > 1
    report["plan_score"] = {
        "episodes": len(ys),
        "auroc_static": float(roc_auc_score(ys, static_s)),
        "auroc_rollout": float(roc_auc_score(ys, roll_s)),
        "share_exactly_zero_static": sum(s < 1e-6 for s in static_s) / max(len(ys), 1),
        "share_exactly_zero_rollout": sum(s < 1e-6 for s in roll_s) / max(len(ys), 1),
        "episodes_where_planners_disagree": differing / max(len(ys), 1),
    }
    (out / "eval.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--data", type=Path, default=Path("data/dataset"))
    p.add_argument("--model", type=Path, default=Path("artifacts/outcome"))
    p.add_argument("--out", type=Path, default=Path("artifacts/worldmodel"))
    p.add_argument("--episodes", type=int, default=400)
    a = p.parse_args(argv)
    print(json.dumps(evaluate(a.data, a.model, a.out, a.episodes), indent=2))


if __name__ == "__main__":
    main()
