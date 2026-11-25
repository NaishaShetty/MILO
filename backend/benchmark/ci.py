"""
ci.py (backend/benchmark)

The CI regression gate: run the fast subset and fail (exit 1) if any planner's success
rate drops more than `--margin` below the committed baseline.

    cd backend
    python -m benchmark.ci                      # check against benchmarks/ci_baseline.json
    python -m benchmark.ci --write-baseline     # after an intended change, record new numbers

Deterministic: same suite, same faults, same seeds, reference plans for the novel
planner -- so a drop means the code changed, not the dice.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from benchmark.run import REPO, run

PLANNERS = ["rule_based", "behavior_tree", "htn", "novel"]


def check(
    baseline: Dict[str, float], current: Dict[str, float], margin: float
) -> List[str]:
    problems = []
    for planner, base in baseline.items():
        now = current.get(planner)
        if now is None:
            problems.append(f"{planner}: missing from this run")
        elif now < base - margin:
            problems.append(
                f"{planner}: success {now:.0%} < baseline {base:.0%} - {margin:.0%}"
            )
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--baseline", type=Path, default=REPO / "benchmarks" / "ci_baseline.json"
    )
    ap.add_argument("--margin", type=float, default=0.05)
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)
    report = run("ci", PLANNERS, "reference", ablations=False)
    current = {p: s["all"]["success"] for p, s in report["planners"].items()}
    print(json.dumps(current, indent=2))
    if a.write_baseline:
        a.baseline.write_text(json.dumps(current, indent=2) + "\n")
        print(f"baseline written to {a.baseline}")
        return 0
    baseline = json.loads(a.baseline.read_text())
    problems = check(baseline, current, a.margin)
    for p in problems:
        print("REGRESSION:", p)
    print("benchmark gate:", "FAILED" if problems else "passed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
