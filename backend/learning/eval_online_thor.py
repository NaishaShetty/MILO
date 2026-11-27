"""
eval_online_thor.py (backend/learning)

The decision for leaving shadow mode, made on real AI2-THOR: the rule-based reflector
against the learned one, on real missions in the held-out scenes.

    cd backend
    python -m learning.eval_online_thor --model artifacts/outcome_real --episodes 300
                                                        (make eval-outcome-thor)

- **Paired**: each episode runs twice, same scene, same task, same planner: once with
  the rule-based reflector and once with the learned one making the retry / replan /
  stop decisions (`MILO_LEARNED_REFLECTOR=on` behaviour). Differences come only from
  the reflector.
- **Held-out scenes only** (`collect_thor.HELD_OUT_SCENES`), none of which the model
  was trained on, and a different task seed from the collected episodes, so these are
  not the missions the offline test used.
- **The model really decides**: the predictor switches itself off when it gets slow
  (`OutcomePredictor` latency budget). Each learned run records whether that happened,
  and the predictor is reset between episodes.
- **Resumable**: one JSON line per finished pair in `--out`; finished pairs are skipped.

Reports mission success, wasted steps, replans and retries per mission, and the pairs
where only one side succeeded (the honest count for a small sample).
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.reflection_agent import ReflectionAgent
from execution.models import StepStatus
from learning.collect_thor import HELD_OUT_SCENES, thor_task
from learning.generate import PLANNERS
from learning.reflector import LearnedReflector
from learning.serving import OutcomePredictor, load_predictor
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner


def run_one(scene: str, index: int, mode: str, predictor: Optional[OutcomePredictor],
            seed: int) -> Dict[str, Any]:  # fmt: skip
    from simulator.simulator import Simulator

    episode_id = f"online-{scene}-{index}"
    rng = random.Random(f"{seed}-{episode_id}")
    sim = Simulator(scene=scene)
    sim.start()
    try:
        made = thor_task(rng, sim.get_metadata().get("objects") or [])
        if made is None:
            return {"skipped": "no task"}
        task, text = made
        planner = rng.choice(PLANNERS)
        kwargs: Dict[str, Any] = {}
        decisions: List[Dict[str, Any]] = []
        if mode == "learned" and predictor is not None:
            predictor.disabled_reason = None  # fresh start for each episode
            reflector = LearnedReflector(ReflectionAgent(), predictor, mode="on")
            original = reflector.pop_decisions

            def collect() -> List[Dict[str, Any]]:
                got = original()
                decisions.extend(got)
                return got

            reflector.pop_decisions = collect  # type: ignore[method-assign]
            kwargs = {"reflection_agent": reflector, "outcome_predictor": predictor}
        orch = Orchestrator(
            PlannerAgentWrapper(create_planner(planner)), ExecutionAgentWrapper(sim), **kwargs  # type: ignore[arg-type]
        )
        started = time.perf_counter()
        state = orch.run(task, planner_type=planner)
        steps = [s for r in state.execution_history for s in r.step_results]
        dispatched = [s for s in steps if s.status in
                      (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.BLOCKED)]  # fmt: skip
        failed = [s for s in dispatched if s.status != StepStatus.COMPLETED]
        ok = state.status.value == "succeeded"
        return {
            "task": text,
            "planner": planner,
            "success": ok,
            "wasted_steps": len(failed) if ok else len(dispatched),
            "steps": len(dispatched),
            "replans": orch._replans,
            "retries": orch._retries,
            "seconds": round(time.perf_counter() - started, 2),
            "learned_decisions_used": sum(1 for d in decisions if d.get("used")),
            "aborted_by_model": any(
                d.get("used") and d.get("learned") == "abort" for d in decisions
            ),
            "predictor_switched_off": (
                predictor.disabled_reason if (mode == "learned" and predictor) else None
            ),
        }
    finally:
        sim.stop()


def jobs(episodes: int) -> List[tuple]:
    return [(HELD_OUT_SCENES[i % len(HELD_OUT_SCENES)], i // len(HELD_OUT_SCENES))
            for i in range(episodes)]  # fmt: skip


def summarise(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    def side(m: str) -> Dict[str, float]:
        rows = [p[m] for p in pairs]
        n = max(len(rows), 1)
        return {
            "mission_success": round(sum(r["success"] for r in rows) / n, 4),
            "wasted_steps_per_mission": round(
                sum(r["wasted_steps"] for r in rows) / n, 3
            ),
            "replans_per_mission": round(sum(r["replans"] for r in rows) / n, 3),
            "retries_per_mission": round(sum(r["retries"] for r in rows) / n, 3),
            "steps_per_mission": round(sum(r["steps"] for r in rows) / n, 3),
        }

    only_learned = sum(
        1 for p in pairs if p["learned"]["success"] and not p["rule"]["success"]
    )
    only_rule = sum(
        1 for p in pairs if p["rule"]["success"] and not p["learned"]["success"]
    )
    aborted = [p for p in pairs if p["learned"]["aborted_by_model"]]
    return {
        "pairs": len(pairs),
        "rule_based": side("rule"),
        "learned": side("learned"),
        "pairs_only_learned_succeeded": only_learned,
        "pairs_only_rule_succeeded": only_rule,
        "aborted_by_learned": len(aborted),
        "aborted_would_have_failed_anyway": (
            round(sum(not p["rule"]["success"] for p in aborted) / len(aborted), 3)
            if aborted else None
        ),  # fmt: skip
        "learned_runs_where_predictor_switched_off": sum(
            1 for p in pairs if p["learned"]["predictor_switched_off"]
        ),
        "learned_runs_where_it_made_a_decision": sum(
            1 for p in pairs if p["learned"]["learned_decisions_used"]
        ),
    }


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--model", type=Path, default=Path("artifacts/outcome_real"))
    ap.add_argument("--episodes", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument(
        "--out", type=Path, default=Path("../results/outcome_real/online_thor.jsonl")
    )
    a = ap.parse_args(argv)
    predictor = load_predictor(a.model)
    if predictor is None:
        raise SystemExit(f"no model found at {a.model}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if a.out.exists():
        for line in a.out.read_text().splitlines():
            if line.strip():
                p = json.loads(line)
                done[p["episode"]] = p
    todo = [(s, i) for s, i in jobs(a.episodes) if f"online-{s}-{i}" not in done]
    print(
        f"{len(done)} pairs done, {len(todo)} to go (model {predictor.version})",
        flush=True,
    )
    started = time.time()
    with a.out.open("a") as f:
        for n, (scene, index) in enumerate(todo, start=1):
            pair: Dict[str, Any] = {
                "episode": f"online-{scene}-{index}",
                "scene": scene,
            }
            try:
                for mode in ("rule", "learned"):
                    pair[mode] = run_one(scene, index, mode, predictor, a.seed)
            except Exception as exc:  # one broken scene must not stop the run
                print(
                    f"[{n}] {scene} #{index}: error {type(exc).__name__}: {exc}"[:200],
                    flush=True,
                )
                continue
            if "skipped" in pair["rule"] or "skipped" in pair["learned"]:
                continue
            f.write(json.dumps(pair) + "\n")
            f.flush()
            done[pair["episode"]] = pair
            per = (time.time() - started) / n
            print(f"[{n}/{len(todo)}] {scene} #{index} {pair['rule']['task']!r}: rule "
                  f"{'ok' if pair['rule']['success'] else 'fail'}, learned "
                  f"{'ok' if pair['learned']['success'] else 'fail'}  "
                  f"(~{per * (len(todo) - n) / 3600:.1f} h left)", flush=True)  # fmt: skip
    report = {"model": str(a.model), "model_version": predictor.version, "seed": a.seed,
              "scenes": HELD_OUT_SCENES, **summarise(list(done.values()))}  # fmt: skip
    a.out.with_suffix(".summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
