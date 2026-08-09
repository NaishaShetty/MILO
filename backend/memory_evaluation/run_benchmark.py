"""
run_benchmark.py (backend/memory_evaluation)

Purpose
-------
Phase 6.4's experiment runner (spec section 20): the smallest CLI that
answers "does persistent memory change task performance, efficiency,
or failure recovery, compared with the identical robot with memory
switched off?" over the benchmark suite in `scenarios.py`.

    cd backend && python -m memory_evaluation.run_benchmark \
        [--output-dir ../experiments/results] [--sizes 10 100 1000]

What this does NOT do
----------------------
It does not tune the memory system against this benchmark, does not
special-case any scenario, and does not treat a single deterministic
run as repeated independent trials -- see "Statistical honesty" below.
It also does not call real AI2-THOR: every run is `RuleBasedPlanner` +
`FakeSimulator` (see `scenarios.py`'s own docstring), exactly matching
every other Phase 5/6 test in this repository. Numbers produced here
are a `FakeSimulator`/in-process-latency benchmark, not a real-hardware
or real-Unity-simulator measurement -- reported as such in every output
file this script writes.

Statistical honesty
--------------------
Every scenario here is fully deterministic: the same planner, the same
simulator, the same fixed scene data, no LLM, no randomness. Running a
scenario twice produces byte-identical results. The per-episode/
per-category numbers below are therefore a *descriptive* comparison
across the benchmark's distinct scenarios (each scenario is one
independent *design point*, not one independent *trial* of the same
design point) -- not a basis for a p-value or confidence interval, and
this script does not compute one. See the "N" reported in the summary:
it counts benchmark episodes, not repeated trials of identical
conditions.

Output
------
Writes one timestamped, machine-readable JSON file (raw per-episode
results + every sub-experiment + reproducibility metadata) and one CSV
(one row per episode, for quick spreadsheet inspection) per run, plus a
human-readable table on stdout. Raw results and generated summaries are
the same file here (deliberately -- this is a small benchmark; splitting
"raw" vs "summary" storage per section 21 would be premature structure
for ~20 episodes total). Reproducibility metadata records
`git_commit=None` honestly when run outside a git repository (recorded
via `git rev-parse HEAD`, best-effort, never fabricated).
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence

from memory_evaluation.experiment import EpisodeResult, run_scenario
from memory_evaluation.memory_size import run_memory_size_experiment
from memory_evaluation.pollution import run_pollution_check
from memory_evaluation.scenarios import ALL_SCENARIOS
from memory_evaluation.task_ablation import run_task_level_ablation


def _git_commit() -> Any:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _reproducibility_metadata() -> Dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "planner": "RuleBasedPlanner",
        "simulator": "FakeSimulator (deterministic in-memory fake; not real AI2-THOR)",
        "embedding_model": "HashingEmbedder (deterministic, offline, lexical)",
        "vector_store": "SQLiteVectorStore",
        "memory_store": "SQLiteMemoryStore",
        "task_set": [s.scenario_id for s in ALL_SCENARIOS],
        "seeds": {s.scenario_id: s.seed for s in ALL_SCENARIOS},
        "hardware": "CI/dev machine CPU (no GPU used by this benchmark)",
        "determinism": (
            "Fully deterministic (RuleBasedPlanner + FakeSimulator, no LLM, "
            "no randomness). Repeated runs are byte-identical, not "
            "independent trials -- see this module's docstring."
        ),
    }


def _run_core_comparison(base_dir: Path) -> List[Dict[str, Any]]:
    episodes: List[Dict[str, Any]] = []
    for scenario in ALL_SCENARIOS:
        for condition in ("memory_off", "memory_on"):
            results: List[EpisodeResult] = run_scenario(
                scenario, condition, base_dir / scenario.scenario_id / condition
            )
            episodes.extend(ep.to_dict() for ep in results)
    return episodes


def _paired_deltas(episodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pairs each (scenario_id, episode_label) across memory_off vs
    memory_on and reports the per-metric difference -- section 10's
    "measure ΔSuccess/ΔActions/ΔTotalTime between conditions"."""
    by_key: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
    for ep in episodes:
        key = (ep["scenario_id"], ep["episode_label"])
        by_key.setdefault(key, {})[ep["condition"]] = ep

    pairs = []
    for (scenario_id, label), conditions in sorted(by_key.items()):
        if "memory_off" not in conditions or "memory_on" not in conditions:
            continue
        off, on = conditions["memory_off"], conditions["memory_on"]
        pairs.append(
            {
                "scenario_id": scenario_id,
                "episode_label": label,
                "success_off": off["success"],
                "success_on": on["success"],
                "success_changed": off["success"] != on["success"],
                "delta_actions": on["action_count"] - off["action_count"],
                "delta_total_latency_ms": (
                    on["total_latency_ms"] - off["total_latency_ms"]
                ),
                "memory_used_in_plan_on": on["memory_used_in_plan"],
            }
        )

    def _rate(values: Sequence[bool]) -> float:
        return sum(1 for v in values if v) / len(values) if values else 0.0

    all_off_success = [c["memory_off"]["success"] for c in by_key.values()]
    all_on_success = [c["memory_on"]["success"] for c in by_key.values()]
    all_off_actions = [c["memory_off"]["action_count"] for c in by_key.values()]
    all_on_actions = [c["memory_on"]["action_count"] for c in by_key.values()]

    summary = {
        "n_episode_pairs": len(pairs),
        "success_rate_memory_off": _rate(all_off_success),
        "success_rate_memory_on": _rate(all_on_success),
        "success_rate_delta_pp": (
            100.0 * (_rate(all_on_success) - _rate(all_off_success))
        ),
        "mean_actions_memory_off": mean(all_off_actions) if all_off_actions else 0.0,
        "mean_actions_memory_on": mean(all_on_actions) if all_on_actions else 0.0,
        "episodes_where_success_changed": sum(1 for p in pairs if p["success_changed"]),
        "episodes_where_memory_influenced_plan": sum(
            1 for p in pairs if p["memory_used_in_plan_on"]
        ),
    }
    return {"pairs": pairs, "summary": summary}


def _print_summary(comparison: Dict[str, Any], pollution: Dict[str, Any]) -> None:
    summary = comparison["summary"]
    print("=" * 72)
    print("Phase 6.4 -- Memory vs No-Memory benchmark summary")
    print("=" * 72)
    print(
        f"Episode pairs (scenario x episode, both conditions): {summary['n_episode_pairs']}"
    )
    print(
        f"Success rate   OFF={summary['success_rate_memory_off']:.2%}  "
        f"ON={summary['success_rate_memory_on']:.2%}  "
        f"Delta={summary['success_rate_delta_pp']:+.1f}pp"
    )
    print(
        f"Mean actions   OFF={summary['mean_actions_memory_off']:.2f}  "
        f"ON={summary['mean_actions_memory_on']:.2f}"
    )
    print(
        f"Episodes where success flipped between conditions: {summary['episodes_where_success_changed']}"
    )
    print(
        f"Episodes where memory measurably influenced the plan: {summary['episodes_where_memory_influenced_plan']}"
    )
    print()
    print("Per-episode pairs:")
    header = f"{'scenario':<28}{'episode':<24}{'off':>6}{'on':>6}{'d_actions':>11}{'influenced':>12}"
    print(header)
    print("-" * len(header))
    for p in comparison["pairs"]:
        print(
            f"{p['scenario_id']:<28}{p['episode_label']:<24}"
            f"{str(p['success_off']):>6}{str(p['success_on']):>6}"
            f"{p['delta_actions']:>11}{str(p['memory_used_in_plan_on']):>12}"
        )
    print()
    print("Memory pollution check:", json.dumps(pollution, indent=2))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "experiments" / "results",
    )
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=[10, 100, 1000],
        help="Memory-store sizes for the memory-size experiment (section 14).",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Directory for the SQLite databases this run creates. "
        "Defaults to a temporary directory, deleted on exit.",
    )
    args = parser.parse_args(argv)

    import tempfile

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = args.work_dir or Path(tmp)
        work_dir.mkdir(parents=True, exist_ok=True)

        print("Running core memory_on vs memory_off comparison...")
        episodes = _run_core_comparison(work_dir / "core")
        comparison = _paired_deltas(episodes)

        print("Running memory-size experiment...")
        size_results = run_memory_size_experiment(work_dir / "size", sizes=args.sizes)

        print("Running task-level ablation...")
        ablation_results = run_task_level_ablation(work_dir / "ablation")

        print("Running memory pollution check...")
        pollution = run_pollution_check(work_dir / "pollution").to_dict()

        report = {
            "reproducibility": _reproducibility_metadata(),
            "episodes": episodes,
            "comparison": comparison,
            "memory_size_experiment": [r.to_dict() for r in size_results],
            "task_level_ablation": ablation_results,
            "memory_pollution": pollution,
        }

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        json_path = args.output_dir / f"benchmark_{timestamp}.json"
        csv_path = args.output_dir / f"benchmark_{timestamp}_episodes.csv"

        json_path.write_text(json.dumps(report, indent=2, default=str))

        with csv_path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(episodes[0].keys()))
            writer.writeheader()
            for ep in episodes:
                row = dict(ep)
                row["plan_targets"] = ";".join(row["plan_targets"])
                row["latencies_ms"] = json.dumps(row["latencies_ms"])
                row["recovered_from"] = ";".join(row["recovered_from"] or [])
                writer.writerow(row)

        _print_summary(comparison, pollution)
        print()
        print(f"Raw results written to: {json_path}")
        print(f"Episode CSV written to: {csv_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
