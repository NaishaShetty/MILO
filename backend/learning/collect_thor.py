"""
collect_thor.py (backend/learning)

Real AI2-THOR episodes for the step-outcome predictor, logged with the same
`EpisodeLogger` (and so the same features) as the synthetic generator.

    cd backend
    python -m learning.collect_thor --episodes 600          (make collect-thor)

- **Real failures only**: nothing is injected; whatever goes wrong in AI2-THOR is logged.
- **Fixed scene split**: training scenes and held-out scenes never mix. Half the
  episodes (300 by default) run in the held-out scenes, which `make train-real` keeps
  out of training and evaluates on.
- **Resumable**: episode ids are `thor-<scene>-<index>`; finished ones are skipped, so an
  interrupted overnight run continues where it stopped.
- **Time**: a fresh Unity process per episode, about 7 s each on an RTX 4050 laptop
  (measured 2026-11-27), so 600 episodes take about 70 minutes. Needs a GPU and a display (or
  VISION_SIMULATOR_PLATFORM=cloud_rendering), and nothing else large on the GPU.
"""

from __future__ import annotations

import argparse
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.episode_log import EpisodeLogger
from learning.generate import PLANNERS, _done
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from schemas.task import SingleTask

#: iTHOR has 30 scenes per room type; the last 5 of each are held out for evaluation.
TRAIN_SCENES = [
    f"FloorPlan{base + i}" for base in (0, 200, 300, 400) for i in range(1, 26)
]
HELD_OUT_SCENES = [
    f"FloorPlan{base + i}" for base in (0, 200, 300, 400) for i in range(26, 31)
]

_TEXT = {"pick_up": "pick up the {o}", "fetch": "bring me the {o}", "find": "find the {o}",
         "place": "put the {o} on the {t}", "store": "put the {o} in the {t}",
         "open": "open the {o}", "close": "close the {o}",
         "turn_on": "turn on the {o}", "turn_off": "turn off the {o}"}  # fmt: skip


def thor_task(
    rng: random.Random, objects: List[Dict[str, Any]]
) -> Optional[Tuple[SingleTask, str]]:
    """A random library task that makes sense in this real scene (AI2-THOR reports
    `isToggled` on every object, so "switchable" comes from `toggleable`)."""

    def names(pred: Any) -> List[str]:
        return sorted({o["objectType"].lower() for o in objects if pred(o)})

    items = names(lambda o: o.get("pickupable"))
    surfaces = names(
        lambda o: o.get("receptacle")
        and not o.get("openable")
        and not o.get("pickupable")
    )
    containers = names(lambda o: o.get("openable") and o.get("receptacle"))
    switches = names(lambda o: o.get("toggleable"))
    options: List[Tuple[str, Optional[str], Optional[str]]] = []
    for item in items:
        options += [
            ("pick_up", item, None),
            ("fetch", item, None),
            ("find", item, None),
        ]
        options += [("place", item, s) for s in surfaces[:3]]
        options += [("store", item, c) for c in containers[:3]]
    options += [(k, c, None) for c in containers for k in ("open", "close")]
    options += [(k, s, None) for s in switches for k in ("turn_on", "turn_off")]
    if not options:
        return None
    kind, obj, target = rng.choice(options)
    return SingleTask(goal=kind, object=obj, target=target), _TEXT[kind].format(
        o=obj, t=target
    )


def run_episode(db: Path, scene: str, index: int, seed: int) -> str:
    from simulator.simulator import Simulator

    episode_id = f"thor-{scene}-{index}"
    rng = random.Random(f"{seed}-{episode_id}")
    sim = Simulator(scene=scene)
    sim.start()
    try:
        made = thor_task(rng, sim.get_metadata().get("objects") or [])
        if made is None:
            return "no task"
        task, text = made
        task.task_id = episode_id
        planner = rng.choice(PLANNERS)
        orchestrator = Orchestrator(
            PlannerAgentWrapper(create_planner(planner)),
            ExecutionAgentWrapper(sim),
            episode_logger=EpisodeLogger(db),
            in_mission_recovery=False,  # same setting as the synthetic dataset
        )
        # scene_id "FloorPlanN" marks a real AI2-THOR episode (synthetic ones are "scene_N").
        orchestrator.episode_context = {"scene_id": scene, "seed": seed, "task_text": text,
                                        "injected_fault": "none"}  # fmt: skip
        state = orchestrator.run(task, planner_type=planner)
        return f"{planner} {text!r} -> {state.status.value}"
    finally:
        sim.stop()


def jobs(episodes: int) -> List[Tuple[str, int]]:
    """Half the episodes in held-out scenes, half in training scenes, round-robin."""
    half = episodes // 2
    out = [
        (HELD_OUT_SCENES[i % len(HELD_OUT_SCENES)], i // len(HELD_OUT_SCENES))
        for i in range(half)
    ]
    out += [
        (TRAIN_SCENES[i % len(TRAIN_SCENES)], i // len(TRAIN_SCENES))
        for i in range(episodes - half)
    ]
    return out


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=Path("data/episodes_thor"))
    ap.add_argument("--episodes", type=int, default=600)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    db = a.out / "shard-thor.db"
    finished = _done(db)
    todo = [(s, i) for s, i in jobs(a.episodes) if f"thor-{s}-{i}" not in finished]
    print(f"{len(finished)} episodes already logged, {len(todo)} to go", flush=True)
    started = time.time()
    for n, (scene, index) in enumerate(todo, start=1):
        try:
            outcome = run_episode(db, scene, index, a.seed)
        except Exception as exc:  # one broken scene must not stop an overnight run
            outcome = f"error: {type(exc).__name__}: {exc}"[:200]
        per = (time.time() - started) / n
        left = (len(todo) - n) * per / 3600
        print(
            f"[{n}/{len(todo)}] {scene} #{index}: {outcome}  ({per:.0f} s/episode, ~{left:.1f} h left)",
            flush=True,
        )


if __name__ == "__main__":
    main()
