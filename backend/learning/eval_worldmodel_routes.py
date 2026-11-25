"""
eval_worldmodel_routes.py (backend/learning)

Does the world model catch a failure before it happens? On the benchmark's competing-route
tier (the nearest shelf/table is blocked for good, a farther one is clear) every plan
fails. A plan counts as caught if its rollout score (outcome predictor + world model) is
lower than every plan on the known tier that succeeds, i.e. it could be rejected before
acting without rejecting a good one.

    cd backend
    python -m learning.eval_worldmodel_routes --artifacts artifacts      (make eval-worldmodel-routes)
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark.run import case_scene, run_case
from benchmark.suite import Case, known_cases, route_cases
from learning.serving import load_predictor
from learning.worldmodel import WorldModel, rollout_score
from planner.factory import create_planner
from planner.state import WorldState
from schemas.task import SingleTask


def _score(case: Case, predictor: Any, world: WorldModel) -> float:
    plan = (
        create_planner("rule_based")
        .plan(SingleTask(**case.task_fields()), WorldState.initial())
        .plan
    )
    assert plan is not None
    metadata = {"objects": case_scene(case), "inventoryObjects": []}
    return rollout_score(plan, predictor, world, metadata, "rule_based")


def evaluate(artifacts: Path) -> Dict[str, Any]:
    predictor = load_predictor(artifacts / "outcome")
    world = WorldModel.load(artifacts / "worldmodel" / "world.pkl")
    if predictor is None or world is None:
        raise SystemExit(
            f"no trained outcome predictor / world model under {artifacts}"
        )
    good: List[float] = [
        _score(c, predictor, world)
        for c in known_cases()
        if run_case(c, "rule_based")["success"]
    ]
    routes: List[Dict[str, Any]] = []
    for c in route_cases():
        routes.append({"case": c.case_id, "score": round(_score(c, predictor, world), 4),
                       "failed": not run_case(c, "rule_based")["success"]})  # fmt: skip
    floor = min(good)
    # Caught = scored below every plan that succeeds (so rejecting it costs no good plan).
    caught = [r for r in routes if r["failed"] and float(r["score"]) < floor]
    return {
        "route_plans": routes,
        "successful_known_plans": {
            "n": len(good),
            "min": round(floor, 4),
            "median": round(statistics.median(good), 4),
        },
        "failures": sum(r["failed"] for r in routes),
        "caught_before_acting": len(caught),
    }


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    report = evaluate(a.artifacts)
    out = a.out or a.artifacts / "worldmodel" / "routes_eval.json"
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
