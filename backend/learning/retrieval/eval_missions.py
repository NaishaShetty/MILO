"""
eval_missions.py (backend/learning/retrieval)

Effect of the embedder on missions: the same episodes (held-out scenes, same
tasks/faults/seeds) run with memory in the loop, once per embedder. Each episode's
memory holds the TRUE fact for every object in the scene ("mug located_on table")
plus distractor facts about the same objects in other places -- so retrieval has to
surface a useful fact and the planner's memory hint (visit the remembered place
first) either helps or sends it somewhere wrong.

    cd backend
    MEMORY_EMBEDDING_PROVIDER=learned python -m learning.retrieval.eval_missions

Reports mission success, steps executed per mission, and how often a memory hint
was used. (Run with `--embedder hashing` / `--embedder learned`.)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.execution_agent import ExecutionAgentWrapper
from agents.memory_agent import MemoryAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.eval_online import test_scenes
from learning.generate import make_faults, make_task
from learning.synthetic import SyntheticSimulator, make_scene
from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from memory.models import MemoryProvenance
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner

PLACES = ["fridge", "table", "countertop", "shelf", "desk", "drawer", "cabinet", "sofa"]


def run(embedder: str, episodes: int, seed: int = 0) -> Dict[str, Any]:
    os.environ["MEMORY_EMBEDDING_PROVIDER"] = embedder
    scenes = test_scenes(seed=seed)
    rows: List[Dict[str, Any]] = []
    for i in range(episodes):
        rng = random.Random(f"mem-{seed}-{i}")
        objects = make_scene(scenes[i % len(scenes)], seed)
        task, _ = make_task(rng, objects)
        faults = make_faults(rng, task)
        with tempfile.TemporaryDirectory() as tmp:
            agent = MemoryAgent.from_config(
                MemoryConfig(
                    enabled=True,
                    database_path=Path(tmp) / "m.db",
                    vector_store_path=Path(tmp) / "v",
                )
            )
            by_id = {o["objectId"]: o for o in objects}
            for o in objects:
                if not o.get("pickupable"):
                    continue
                parent = (o.get("parentReceptacles") or [None])[0]
                name = o["objectType"].lower()
                if parent:
                    agent.remember_observation(
                        name,
                        "located_on",
                        by_id[parent]["objectType"].lower(),
                        provenance=MemoryProvenance.OBSERVATION,
                        confidence=0.9,
                    )
                for _ in range(2):  # stale beliefs about the same object elsewhere
                    agent.remember_observation(
                        name,
                        "located_on",
                        rng.choice(PLACES),
                        provenance=MemoryProvenance.OBSERVATION,
                        confidence=0.5,
                    )
            sim = SyntheticSimulator(objects, faults)
            orch = Orchestrator(
                PlannerAgentWrapper(create_planner("rule_based")),
                ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
                memory_agent=MemoryAgentWrapper(agent),
            )
            state = orch.run(task)
            steps = [s for r in state.execution_history for s in r.step_results]
            plan_steps = state.current_plan.steps if state.current_plan else []
            rows.append(
                {
                    "ok": state.status.value == "succeeded",
                    "steps": len(steps),
                    "hint": any(
                        s.parameters.get("source") == "memory" for s in plan_steps
                    ),
                }
            )
    n = max(len(rows), 1)
    return {
        "embedder": embedder,
        "episodes": len(rows),
        "mission_success": sum(r["ok"] for r in rows) / n,
        "steps_per_mission": sum(r["steps"] for r in rows) / n,
        "memory_hint_used": sum(r["hint"] for r in rows) / n,
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--episodes", type=int, default=200)
    parser.add_argument(
        "--out", type=Path, default=Path("artifacts/memory_embedder/missions.json")
    )
    args = parser.parse_args(argv)
    report = {e: run(e, args.episodes) for e in ("hashing", "learned")}
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
