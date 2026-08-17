"""
run_ablation_real.py (backend/memory_evaluation)

Purpose
-------
Phase B's CLI entry point: runs `real_scenarios.ALL_REAL_SCENARIOS`
under both `memory_on`/`memory_off` against a REAL AI2-THOR `Simulator`
and a real `SentenceTransformerEmbedder` (see `experiment_real.py`'s
docstring for the full rationale), and writes the same
JSON+CSV+reproducibility-metadata shape `run_benchmark.py` does --
reusing that module's `_paired_deltas`/`_git_commit` directly rather
than re-deriving the same pairing logic a second time, since both
scripts produce the exact same `EpisodeResult` schema (only the
summary printer and reproducibility metadata differ, so those two stay
local to this module).

    cd backend
    RUN_SIMULATOR_TESTS=true python -m memory_evaluation.run_ablation_real \
        [--output-dir ../experiments/results]

Requires a real AI2-THOR/Unity binary reachable (same precondition as
`simulator/test_execution_e2e.py`) -- gated behind the same
`RUN_SIMULATOR_TESTS` opt-in convention as that file, checked at the top
of `main()` rather than via `pytest.mark.skipif` since this is a CLI
script, not a test.

Statistical honesty
--------------------
`real_scenarios.ALL_REAL_SCENARIOS` totals 16 episodes -- a first real
number against production conditions, explicitly not a statistically
powered study (a real AI2-THOR mission takes real wall-clock seconds
per action; running enough repeats for a confidence interval is future
work, not this pass's scope). Every number this script reports is
descriptive over these 16 (32 once both conditions run), not a
p-value/CI basis, matching `run_benchmark.py`'s own "Statistical
honesty" section. Real AI2-THOR is not perfectly deterministic run to
run (real physics settling, real agent pose) the way `FakeSimulator` is
-- this script does not claim byte-identical reproducibility the way
`run_benchmark.py` can.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from memory_evaluation.experiment_real import (
    REAL_EMBEDDING_CONFIG,
    run_real_scenario,
)
from memory_evaluation.real_scenarios import ALL_REAL_SCENARIOS
from memory_evaluation.run_benchmark import _git_commit, _paired_deltas


def _reproducibility_metadata() -> Dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "planner": "RuleBasedPlanner",
        "simulator": "Simulator (real AI2-THOR/Unity, FloorPlan1, restarted between episodes)",
        "embedding_model": (
            f"SentenceTransformerEmbedder ({REAL_EMBEDDING_CONFIG.provider}, "
            "sentence-transformers/all-MiniLM-L6-v2 via transformers, mean-pooled)"
        ),
        "vector_store": "SQLiteVectorStore",
        "memory_store": "SQLiteMemoryStore",
        "task_set": [s.scenario_id for s in ALL_REAL_SCENARIOS],
        "seeds": {s.scenario_id: s.seed for s in ALL_REAL_SCENARIOS},
        "hardware": platform.processor() or "unspecified CPU",
        "determinism": (
            "NOT byte-identical across runs: real AI2-THOR physics/pose settling "
            "and a real embedding model both introduce run-to-run variation the "
            "FakeSimulator/HashingEmbedder benchmark (run_benchmark.py) does not "
            "have. See this module's docstring's 'Statistical honesty' section."
        ),
        "phase": "Phase B -- real AI2-THOR + real embedder follow-up to the "
        "FakeSimulator/HashingEmbedder benchmark in run_benchmark.py",
    }


def _print_summary(comparison: Dict[str, Any]) -> None:
    summary = comparison["summary"]
    print("=" * 72)
    print("Phase B -- Real AI2-THOR memory vs no-memory ablation summary")
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
    header = f"{'scenario':<32}{'episode':<24}{'off':>6}{'on':>6}{'d_actions':>11}{'influenced':>12}"
    print(header)
    print("-" * len(header))
    for p in comparison["pairs"]:
        print(
            f"{p['scenario_id']:<32}{p['episode_label']:<24}"
            f"{str(p['success_off']):>6}{str(p['success_on']):>6}"
            f"{p['delta_actions']:>11}{str(p['memory_used_in_plan_on']):>12}"
        )


def _run_core_comparison(base_dir: Path) -> List[Dict[str, Any]]:
    episodes: List[Dict[str, Any]] = []
    for scenario in ALL_REAL_SCENARIOS:
        for condition in ("memory_off", "memory_on"):
            print(f"  {scenario.scenario_id} / {condition} ...", flush=True)
            results = run_real_scenario(
                scenario, condition, base_dir / scenario.scenario_id / condition
            )
            episodes.extend(ep.to_dict() for ep in results)
    return episodes


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import tempfile

    if os.environ.get("RUN_SIMULATOR_TESTS", "false").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        print(
            "Real AI2-THOR ablation is opt-in -- set RUN_SIMULATOR_TESTS=true "
            "(and ensure a display/binary is reachable) to run it. Refusing to "
            "launch AI2-THOR/Unity without that explicit opt-in.",
            file=sys.stderr,
        )
        return 1

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "experiments" / "results",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Directory for the SQLite databases this run creates. "
        "Defaults to a temporary directory, deleted on exit.",
    )
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = args.work_dir or Path(tmp)
        work_dir.mkdir(parents=True, exist_ok=True)

        print("Running real-AI2-THOR core memory_on vs memory_off comparison...")
        episodes = _run_core_comparison(work_dir / "core")
        comparison = _paired_deltas(episodes)

        report = {
            "reproducibility": _reproducibility_metadata(),
            "episodes": episodes,
            "comparison": comparison,
        }

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        json_path = args.output_dir / f"real_ablation_{timestamp}.json"
        csv_path = args.output_dir / f"real_ablation_{timestamp}_episodes.csv"

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

        _print_summary(comparison)
        print()
        print(f"Raw results written to: {json_path}")
        print(f"Episode CSV written to: {csv_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
