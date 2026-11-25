"""
eval_missions.py (backend/learning/detector)

Effect of the lightweight detector on REAL AI2-THOR missions, on held-out test
scenes, same tasks and seeds for both modes:

    cd backend
    python -m learning.detector.eval_missions --model artifacts/detector --episodes 30

`full`: the cheap observe path uses Grounding DINO (today's behaviour).
`fast`: the ONNX detector, Grounding DINO as fallback when unsure OR a named target is not found.
`fast_conf`: same, but falling back only when the fast detector is unsure.
Task = pick up a random pickupable object (success: the simulator reports it in
the inventory) or open a fridge/cabinet/drawer (success: `isOpen`), judged from
simulator metadata, never from the detector. Reports mission success, mean
mission time, mean time spent observing, and how often the fast path fell back.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.execution_agent import ExecutionAgentWrapper
from agents.memory_agent import MemoryAgentWrapper  # noqa: F401
from agents.planner_agent import PlannerAgentWrapper
from agents.vision_agent import VisionAgentWrapper
from learning.detector.classes import class_of
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from schemas.task import SingleTask
from simulator.simulator import Simulator
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.factory import build_vision_system


def pick_task(meta: Dict[str, Any], rng: random.Random) -> Optional[Dict[str, Any]]:
    items = sorted(
        {
            o["objectType"]
            for o in meta["objects"]
            if o.get("pickupable") and class_of(o["objectType"])
        }
    )
    doors = sorted(
        {
            o["objectType"]
            for o in meta["objects"]
            if o.get("openable") and o["objectType"] in ("Fridge", "Cabinet", "Drawer")
        }
    )
    if not items and not doors:
        return None
    if doors and (not items or rng.random() < 0.4):
        t = rng.choice(doors)
        return {"goal": "open", "object": class_of(t) or t.lower(), "type": t}
    t = rng.choice(items)
    return {"goal": "pick_up", "object": class_of(t) or t.lower(), "type": t}


def succeeded(meta: Dict[str, Any], task: Dict[str, Any]) -> bool:
    if task["goal"] == "pick_up":
        return any(
            i.get("objectType") == task["type"]
            for i in meta.get("inventoryObjects") or []
        )
    return any(
        o["objectType"] == task["type"] and o.get("isOpen") for o in meta["objects"]
    )


def run_mode(
    mode: str, scenes: List[str], episodes: int, model: Path, seed: int
) -> Dict[str, Any]:
    import os

    os.environ["MILO_FAST_DETECTOR"] = "1" if mode.startswith("fast") else "0"
    os.environ["MILO_DETECTOR_FALLBACK"] = (
        "confidence" if mode == "fast_conf" else "target"
    )
    os.environ["MILO_DETECTOR_DIR"] = str(model)
    sim = Simulator(render_depth=True)
    sim.start()
    try:
        system = build_vision_system(sim)
        orch = Orchestrator(
            PlannerAgentWrapper(create_planner("rule_based")),
            ExecutionAgentWrapper(sim),
            vision_agent=VisionAgentWrapper(system.agent),
        )
        rows = []
        for i in range(episodes):
            rng = random.Random(f"{seed}-{i}")
            scene = scenes[i % len(scenes)]
            sim.env.controller.reset(scene=scene)
            task = pick_task(sim.get_metadata(), rng)
            if task is None:
                continue
            started = time.perf_counter()
            state = orch.run(SingleTask(goal=task["goal"], object=task["object"]))
            rows.append(
                {
                    "ok": succeeded(sim.get_metadata(), task),
                    "total_s": time.perf_counter() - started,
                    "vision_s": state.latencies_ms.get("vision_ms", 0.0) / 1000.0,
                }
            )
        fb = (
            getattr(system.agent.fast_pipeline.stages[0], "stats", None)
            if system.agent.fast_pipeline
            else None
        )
        n = max(len(rows), 1)
        return {
            "episodes": len(rows),
            "mission_success": sum(r["ok"] for r in rows) / n,
            "mean_mission_s": (
                statistics.mean(r["total_s"] for r in rows) if rows else 0.0
            ),
            "mean_observe_s": (
                statistics.mean(r["vision_s"] for r in rows) if rows else 0.0
            ),
            "fallback_stats": fb,
        }
    finally:
        sim.stop()


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", type=Path, default=Path("artifacts/detector"))
    parser.add_argument("--episodes", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--out", type=Path, default=Path("artifacts/detector/missions.json")
    )
    args = parser.parse_args(argv)
    test_scenes = json.loads((args.model / "split.json").read_text())["test"]
    report = {
        m: run_mode(m, test_scenes, args.episodes, args.model, args.seed)
        for m in ("full", "fast", "fast_conf")
    }
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()


_ = GroundingDINODetector
