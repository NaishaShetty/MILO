"""
generate.py (backend/learning)

Episode generator for the data flywheel. Runs missions through the *real*
Orchestrator/planners/execution controller against a `SyntheticSimulator`
(randomised scenes, object placements, task types from the task library,
controlled failure injection) and logs every step with `EpisodeLogger`.

    cd backend
    python -m learning.generate --out data/episodes --episodes 4000 --scenes 50 --workers 4

- **Deterministic**: an episode is fully determined by `(seed, scene, index)`.
- **Parallel**: `--workers N` processes, each writing its own shard
  (`<out>/shard-K.db`), so there is no write contention.
- **Resumable**: episodes already finished in a shard are skipped; re-run the
  same command after an interruption.
- **Progress bar**: tqdm if installed, otherwise a plain counter.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import random
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import List, Optional, Tuple

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.episode_log import EpisodeLogger
from learning.synthetic import FAULT_KINDS, Faults, SyntheticSimulator, make_scene
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from schemas.task import SingleTask

PLANNERS = ["rule_based", "htn", "behavior_tree"]
FAULT_RATE = 0.6

_TEXT = {
    "pick_up": "pick up the {o}",
    "fetch": "bring me the {o}",
    "deliver": "take the {o} to the {t}",
    "store": "put the {o} in the {t}",
    "place": "put the {o} on the {t}",
    "open": "open the {t}",
    "close": "close the {t}",
    "turn_on": "turn on the {o}",
    "turn_off": "turn off the {o}",
    "find": "find the {o}",
}


def _pick(rng: random.Random, objects: List[dict], pred) -> Optional[str]:
    names = sorted({o["objectType"].lower() for o in objects if pred(o)})
    return rng.choice(names) if names else None


def make_task(rng: random.Random, objects: List[dict]) -> Tuple[SingleTask, str]:
    """A random library task that makes sense in this scene, and its text."""
    item = _pick(rng, objects, lambda o: o.get("pickupable"))
    surface = _pick(
        rng,
        objects,
        lambda o: not o.get("pickupable")
        and not o.get("openable")
        and "isToggled" not in o,
    )
    container = _pick(rng, objects, lambda o: o.get("openable"))
    toggle = _pick(rng, objects, lambda o: "isToggled" in o)
    options: List[Tuple[str, Optional[str], Optional[str]]] = []
    if item:
        options += [
            ("pick_up", item, None),
            ("fetch", item, None),
            ("find", item, None),
        ]
        if surface:
            options += [("deliver", item, surface), ("place", item, surface)]
        if container:
            options += [("store", item, container)] * 2
    if container:
        options += [("open", None, container), ("close", None, container)]
    if toggle:
        options += [("turn_on", toggle, None), ("turn_off", toggle, None)]
    kind, obj, target = rng.choice(options)
    if kind in ("open", "close"):
        task = SingleTask(goal=kind, object=target)
    else:
        task = SingleTask(goal=kind, object=obj, target=target)
    return task, _TEXT[kind].format(o=obj, t=target)


def make_faults(rng: random.Random, task: SingleTask) -> Faults:
    if rng.random() > FAULT_RATE:
        return Faults()
    kind = rng.choice(FAULT_KINDS)
    # Faults hit the object the task works on (or the container for door faults).
    target = (task.object or task.target or "").lower() or None
    if kind == "door_stuck":
        target = (task.target or task.object or "").lower() or None
    return Faults(kind=kind, target=target, times=rng.choice([1, 1, 2, 99]))


def run_episode(db: Path, scene_index: int, index: int, seed: int) -> None:
    episode_id = f"s{seed}-scene{scene_index}-{index}"
    rng = random.Random(episode_id)
    scene_id = f"scene_{scene_index}"
    objects = make_scene(scene_id, seed)
    task, text = make_task(rng, objects)
    faults = make_faults(rng, task)
    task.task_id = episode_id
    planner = rng.choice(PLANNERS)

    sim = SyntheticSimulator(objects, faults)
    orchestrator = Orchestrator(
        PlannerAgentWrapper(create_planner(planner)),
        ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
        episode_logger=EpisodeLogger(db),
    )
    orchestrator.episode_context = {
        "scene_id": scene_id,
        "seed": seed,
        "task_text": text,
        "injected_fault": faults.kind,
    }
    orchestrator.run(task, planner_type=planner)


def _done(db: Path) -> set:
    if not db.exists():
        return set()
    with closing(sqlite3.connect(str(db))) as conn:
        try:
            return {
                r[0]
                for r in conn.execute(
                    "SELECT episode_id FROM episodes WHERE outcome IS NOT NULL"
                )
            }
        except sqlite3.Error:
            return set()


def _worker(args: Tuple[Path, List[Tuple[int, int]], int]) -> int:
    db, jobs, seed = args
    finished = _done(db)
    count = 0
    for scene_index, index in jobs:
        if f"s{seed}-scene{scene_index}-{index}" in finished:
            continue
        run_episode(db, scene_index, index, seed)
        count += 1
    return count


def generate(
    out: Path, episodes: int, scenes: int, seed: int, workers: int, batch: int = 25
) -> int:
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(i % scenes, i // scenes) for i in range(episodes)]
    tasks = [
        (out / f"shard-{n % workers}.db", jobs[start : start + batch], seed)
        for n, start in enumerate(range(0, len(jobs), batch))
    ]
    total, seen = 0, 0
    started = time.time()
    try:
        from tqdm import tqdm  # type: ignore[import-not-found]

        bar = tqdm(total=len(jobs), desc="episodes", unit="ep")
    except ImportError:
        bar = None

    def advance(n_jobs: int, new: int) -> None:
        nonlocal total, seen
        total += new
        seen += n_jobs
        if bar is not None:
            bar.update(n_jobs)
        else:
            print(f"\r{seen}/{len(jobs)} episodes", end="", flush=True)

    if workers == 1:
        for task in tasks:
            advance(len(task[1]), _worker(task))
    else:
        with mp.Pool(workers) as pool:
            for task, new in zip(tasks, pool.imap(_worker, tasks)):
                advance(len(task[1]), new)
    if bar is not None:
        bar.close()
    elapsed = time.time() - started
    print(
        f"\ngenerated {total} new episodes ({len(jobs) - total} already done) in {elapsed:.1f}s -> {out}"
    )
    return total


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=Path("data/episodes"))
    parser.add_argument("--episodes", type=int, default=4000)
    parser.add_argument("--scenes", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    generate(args.out, args.episodes, args.scenes, args.seed, args.workers)


if __name__ == "__main__":
    main(sys.argv[1:])
