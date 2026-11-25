"""Fail if the README's results drift from the files they come from.

Checks README.md against:
- benchmarks/latest.json: the benchmark, recovery-by-fault and ablation tables;
- docs/models/*.md: every number in the learned-models table appears in the model cards;
- the repo itself: every relative link and image exists;
- .github/README.md (the copy GitHub shows): same text, with links one level up.

Usage: python scripts/check_readme_numbers.py   (exit 1 with a list of problems)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
GITHUB_README = ROOT / ".github" / "README.md"

PLANNER_ROWS = {
    "rule-based": "rule_based",
    "behaviour tree": "behavior_tree",
    "HTN": "htn",
}
FAULT_COLUMNS = [
    "blocked_path",
    "out_of_reach",
    "door_stuck",
    "timeout",
    "wrong_detection",
    "missing_object",
]
ABLATION_ROWS = {
    "everything on": "full",
    "no memory": "no_memory",
    "no reflection": "no_reflection",
    "no replanning": "no_replanning",
    "no in-mission recovery": "no_in_mission_recovery",
}


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


def table_rows(text: str, after_heading: str) -> list[list[str]]:
    """Rows (as cell lists) of the first Markdown table after a line starting with `after_heading`."""
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(after_heading)), None
    )
    if start is None:
        raise SystemExit(f"README: no line starting with {after_heading!r}")
    rows, in_table = [], False
    for line in lines[start + 1 :]:
        if line.startswith("|"):
            in_table = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                rows.append(cells)
        elif in_table:
            break
    return rows[1:]  # drop the header


def after_arrow(cell: str) -> str:
    return cell.split("→")[-1].strip().strip("*")


def check_benchmark(text: str, data: dict, problems: list[str]) -> None:
    planners = data["planners"]
    rows = {r[0]: r for r in table_rows(text, "**Benchmark**")}
    for label, key in PLANNER_ROWS.items():
        row = rows.get(label)
        if row is None:
            problems.append(f"benchmark: no row for {label}")
            continue
        p = planners[key]
        want = [
            pct(p["known"]["success"]),
            pct(p["novel"]["success"]),
            pct(p["faults"]["success"]),
            str(p["all"]["steps"]),
        ]
        if row[1:5] != want:
            problems.append(
                f"benchmark {label}: README {row[1:5]} vs latest.json {want}"
            )
    novel_row = next(
        (r for k, r in rows.items() if k.startswith("novel planner")), None
    )
    if novel_row is None:
        problems.append("benchmark: no novel planner row")
    else:
        n = planners["novel"]
        if (novel_row[2], novel_row[4]) != (
            pct(n["novel"]["success"]),
            str(n["all"]["steps"]),
        ):
            problems.append(
                f"benchmark novel: README {novel_row[2]}, {novel_row[4]} vs {pct(n['novel']['success'])}, {n['all']['steps']}"
            )
    if "provider" in data and data["provider"] != "reference":
        problems.append(
            f"benchmark: latest.json provider is {data['provider']!r}; README labels it reference plans"
        )


def check_recovery(text: str, data: dict, problems: list[str]) -> None:
    row = table_rows(text, "**Recovery by fault kind**")[0]
    rec = data["planners"]["rule_based"]["recovery_by_fault"]
    for cell, kind in zip(row, FAULT_COLUMNS):
        if after_arrow(cell) != pct(rec[kind]):
            problems.append(
                f"recovery {kind}: README {cell!r} vs latest.json {pct(rec[kind])}"
            )


def check_ablations(text: str, data: dict, problems: list[str]) -> None:
    rows = {r[0]: r for r in table_rows(text, "**Ablations**")}
    for label, key in ABLATION_ROWS.items():
        want = pct(data["ablations"][key]["known+faults success"])
        got = rows.get(label, [None, None])[1]
        if got != want:
            problems.append(f"ablation {label}: README {got} vs latest.json {want}")


def check_models(text: str, problems: list[str]) -> None:
    cards = " ".join(
        p.read_text(encoding="utf8") for p in (ROOT / "docs" / "models").glob("*.md")
    )
    for row in table_rows(text, "**Learned models**"):
        for number in re.findall(r"\d+\.\d+", " ".join(row[1:3])):
            if number not in cards:
                problems.append(
                    f"learned models {row[0]}: {number} not found in docs/models/*.md"
                )


def check_links(path: Path, problems: list[str]) -> None:
    text = path.read_text(encoding="utf8")
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"^(https?:|mailto:|#)", target):
            continue
        if not (path.parent / target.split("#")[0]).resolve().exists():
            problems.append(f"{path.relative_to(ROOT)}: broken link {target}")


def github_copy(text: str) -> str:
    return re.sub(
        r"(\]\()(?!https?:|mailto:|#|\.\./)([^)\s]+)\)",
        lambda m: f"{m.group(1)}../{m.group(2)})",
        text,
    )


def main() -> int:
    text = README.read_text(encoding="utf8")
    data = json.loads((ROOT / "benchmarks" / "latest.json").read_text(encoding="utf8"))
    problems: list[str] = []
    check_benchmark(text, data, problems)
    check_recovery(text, data, problems)
    check_ablations(text, data, problems)
    check_models(text, problems)
    check_links(README, problems)
    if GITHUB_README.exists():
        check_links(GITHUB_README, problems)
        if GITHUB_README.read_text(encoding="utf8") != github_copy(text):
            problems.append(
                ".github/README.md is out of sync with README.md (regenerate with --write-github)"
            )
    if problems:
        print("README drifted from its sources:")
        for p in problems:
            print("  -", p)
        return 1
    print("README numbers and links match their sources.")
    return 0


if __name__ == "__main__":
    if "--write-github" in sys.argv:
        GITHUB_README.write_text(
            github_copy(README.read_text(encoding="utf8")), encoding="utf8"
        )
    sys.exit(main())
