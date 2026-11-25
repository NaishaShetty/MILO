"""
thor.py (backend/benchmark)

The benchmark on real AI2-THOR: resumable and chunked, so it can run overnight and be
stopped and restarted. It runs the published `milo_benchmark` tasks (v1.1 by default:
54 tasks over 9 real scenes) through `planning_evaluation.run_benchmark.run_episode`,
which launches a fresh Unity process per episode and scores the goal from AI2-THOR's own
object state.

    cd backend
    python -m benchmark.thor                          # every planner, every task (make benchmark-thor)
    python -m benchmark.thor --chunk 20               # stop after 20 new episodes
    python -m benchmark.thor --planners react --react-model qwen2.5:7b   # ReAct on a local model

Each finished episode is appended to results/thor/v<version>/episodes.jsonl; a rerun skips
every (planner, task) already there, so an interrupted run resumes where it stopped.
results/thor/v<version>/summary.json has goal success per planner and tier.

Needs a GPU and a display (or VISION_SIMULATOR_PLATFORM=cloud_rendering). Expect about
15-30 s per episode on an RTX 4050 laptop: roughly 1 hour per classical planner for v1.1,
more for ReAct (one model call per step). Stop any other GPU job first (Ollama keeps a
model in VRAM for MILO_OLLAMA_KEEP_ALIVE; see docs/local_model.md).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parents[2]
CLASSICAL = ["rule_based", "behavior_tree", "htn"]


def _done(path: Path) -> Set[Tuple[str, str]]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            out.add((row["planner"], row["task_id"]))
    return out


def summarise(path: Path) -> Dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    by: Dict[str, Dict[str, List[bool]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        ok = bool(r.get("goal_success"))
        by[r["planner"]]["all"].append(ok)
        by[r["planner"]][r.get("difficulty_tier") or "?"].append(ok)
    return {
        "episodes": len(rows),
        "goal_success": {
            p: {tier: {"done": len(v), "success": round(sum(v) / len(v), 4)} for tier, v in tiers.items()}
            for p, tiers in by.items()
        },  # fmt: skip
        "react_model": next(
            (r.get("react_model") for r in rows if r.get("react_model")), None
        ),
    }


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--version", default="1.1", choices=["1.0", "1.1"])
    ap.add_argument("--planners", nargs="+", default=CLASSICAL)
    ap.add_argument(
        "--react-model", default=None, help="local model for ReAct, served by Ollama"
    )
    ap.add_argument(
        "--chunk",
        type=int,
        default=0,
        help="stop after this many new episodes (0 = all)",
    )
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)

    if "react" in a.planners:
        if not a.react_model:
            raise SystemExit(
                "ReAct needs --react-model (it would otherwise fall back to rule-based)"
            )
        url = os.environ.get("MILO_OLLAMA_URL", "http://localhost:11434").rstrip("/")
        os.environ.update(LANGUAGE_LLM_PROVIDER="qwen", LANGUAGE_LLM_BASE_URL=f"{url}/v1",
                          LANGUAGE_LLM_MODEL=a.react_model, QWEN_API_KEY="not-needed")  # fmt: skip

    # Imported late: it reads the language-model settings from the environment.
    from planning_evaluation.loader import load_tasks
    from planning_evaluation.run_benchmark import (
        PLANNERS,
        run_episode,
        run_react_episode,
    )

    out_dir = a.out or REPO / "results" / "thor" / f"v{a.version}"
    out_dir.mkdir(parents=True, exist_ok=True)
    episodes = out_dir / "episodes.jsonl"
    done = _done(episodes)
    tasks = load_tasks(version=a.version)
    todo = [(p, t) for p in a.planners for t in tasks if (p, t.task_id) not in done]
    print(f"{len(done)} episodes already done, {len(todo)} to go"
          + (f", stopping after {a.chunk}" if a.chunk else ""), flush=True)  # fmt: skip
    planners: Dict[str, Any] = {}
    started = time.time()
    for n, (name, task) in enumerate(todo[: a.chunk or None], start=1):
        planner = planners.setdefault(name, PLANNERS[name]())
        result = (
            run_react_episode(planner, task)
            if name == "react"
            else run_episode(name, planner, task)
        )
        row = asdict(result)
        row["react_model"] = f"{a.react_model} via Ollama" if name == "react" else None
        row["date"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(episodes, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        per = (time.time() - started) / n
        print(f"[{n}/{len(todo)}] {name:13s} {task.task_id:24s} goal={row['goal_success']} "
              f"({per:.0f} s/episode)", flush=True)  # fmt: skip
    if episodes.exists():
        summary = summarise(episodes)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary["goal_success"], indent=1))


if __name__ == "__main__":
    main()
