"""
measure_observe_cost.py (backend/scripts)

Measures what one planning-loop observation costs, with and without the
segmenter (SAM2): `VisionAgent.perceive(prompt)` (what the loop used to
do every iteration) vs `perceive(prompt, include_masks=False)` (what
`Orchestrator._observe` does now). Needs the real thing -- an AI2-THOR
simulator and the Grounding DINO / SAM2 weights -- so it is a manual
script, not a test:

    cd backend
    python -m scripts.measure_observe_cost [--runs 10] [--prompt "apple."]

Prints mean/median per-call milliseconds for both modes (after
`--warmup` discarded calls) plus a per-stage breakdown, as a JSON line
you can paste into a commit message or the README.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any, Dict, List

from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from simulator.simulator import Simulator
from vision.factory import build_vision_system


def _time_stages(agent, prompt: str, include_masks: bool):
    """Runs one perceive() manually, returning per-stage milliseconds."""
    image = agent.get_rgb_image()
    scene = Scene()
    scene.metadata[SceneMetadata.DETECTION_PROMPT] = prompt
    stages = {}
    names = ["detector", "segmenter", "depth", "tracker", "scene_graph"]
    for name, stage in zip(names, agent.pipeline.stages):
        if stage is None or (name == "segmenter" and not include_masks):
            continue
        started = time.perf_counter()
        scene = stage.process(image, scene)
        stages[name] = (time.perf_counter() - started) * 1000.0
    return stages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--prompt", default="apple. refrigerator.")
    args = parser.parse_args()

    simulator = Simulator(render_depth=True)
    simulator.start()
    try:
        agent = build_vision_system(simulator).agent
        modes = (("full", True), ("no_masks", False))
        for _ in range(args.warmup):
            for _, include_masks in modes:
                agent.perceive(args.prompt, include_masks=include_masks)

        # Modes alternate within each run so GPU clocks / background load
        # drift hits both equally, and every sample is a full perceive()
        # call timed stage by stage (so totals and breakdown agree).
        totals: Dict[str, List[float]] = {label: [] for label, _ in modes}
        stages: Dict[str, Dict[str, List[float]]] = {label: {} for label, _ in modes}
        for _ in range(args.runs):
            for label, include_masks in modes:
                per_stage = _time_stages(agent, args.prompt, include_masks)
                totals[label].append(sum(per_stage.values()))
                for name, ms in per_stage.items():
                    stages[label].setdefault(name, []).append(ms)

        results: Dict[str, Any] = {}
        for label, _ in modes:
            results[label] = {
                "mean_ms": round(statistics.mean(totals[label]), 1),
                "median_ms": round(statistics.median(totals[label]), 1),
                "stage_mean_ms": {
                    k: round(statistics.mean(v), 1) for k, v in stages[label].items()
                },
                "stage_median_ms": {
                    k: round(statistics.median(v), 1) for k, v in stages[label].items()
                },
                "stage_min_ms": {k: round(min(v), 1) for k, v in stages[label].items()},
            }
        results["saved_ms_per_observe_mean"] = round(
            results["full"]["mean_ms"] - results["no_masks"]["mean_ms"], 1
        )
        results["saved_ms_per_observe_median"] = round(
            results["full"]["median_ms"] - results["no_masks"]["median_ms"], 1
        )
        # Skipping the segmenter removes exactly that stage and nothing
        # else, so its own cost is the per-observe saving. The detector
        # (Grounding DINO) swings a lot between calls on a laptop GPU, so
        # the totals above are noisy; this is the steadier figure.
        seg = stages["full"].get("segmenter", [0.0])
        results["segmenter_stage_median_ms"] = round(statistics.median(seg), 1)
        results["segmenter_stage_min_ms"] = round(min(seg), 1)
        results["runs"] = args.runs
        print(json.dumps(results))
    finally:
        simulator.stop()


if __name__ == "__main__":
    main()
