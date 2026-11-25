"""
build_dataset.py (backend/learning)

Turns the episode logs (`<in>/shard-*.db`) into train / validation / test
tables plus a data report.

    cd backend
    python -m learning.build_dataset --db-dir data/episodes --out data/dataset

Splits (deterministic, seeded, never by step):
- **test**: whole *scenes* held out (`--test-scene-frac`, default 20%), so the
  final test measures generalisation to unseen layouts;
- **train / validation**: the remaining scenes' *episodes* are split by a
  hash of the episode id (`--val-frac`, default 15%); every step of an episode
  stays together.

Outputs: `train.csv`, `val.csv`, `test.csv` (one row per labelled step, the
before/after feature snapshots flattened to `b_*` / `a_*` columns),
`episodes_<split>.csv`, `report.json`, `report.md`, `manifest.json` (with a
content hash of the inputs for the model registry).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from learning.schema import FAILURE_TYPES, SCHEMA_VERSION

#: A failure type with fewer labelled steps than this is flagged in the report.
MIN_FAILURES_PER_TYPE = 200


def _h(text: str, seed: int) -> float:
    """Stable value in [0, 1) for a string."""
    digest = hashlib.sha256(f"{seed}:{text}".encode()).hexdigest()
    return int(digest[:12], 16) / float(16**12)


def split_scenes(
    scenes: List[str], test_frac: float, seed: int
) -> Tuple[List[str], List[str]]:
    """(train_val_scenes, test_scenes): whole scenes held out, by hash rank."""
    ranked = sorted(scenes, key=lambda s: _h(s, seed))
    n_test = max(1, round(len(ranked) * test_frac)) if len(ranked) > 1 else 0
    return sorted(ranked[n_test:]), sorted(ranked[:n_test])


def assign_splits(
    episodes: Dict[str, str],
    test_frac: float,
    val_frac: float,
    seed: int,
    test_scenes: Optional[List[str]] = None,
) -> Dict[str, str]:
    """`{episode_id: "train" | "val" | "test"}` from `{episode_id: scene_id}`.
    `test_scenes`, when given, are the held-out scenes (e.g. real AI2-THOR ones)."""
    if test_scenes is None:
        _, test_scenes = split_scenes(sorted(set(episodes.values())), test_frac, seed)
    out = {}
    for episode_id, scene in episodes.items():
        if scene in test_scenes:
            out[episode_id] = "test"
        else:
            out[episode_id] = "val" if _h(episode_id, seed + 1) < val_frac else "train"
    return out


def _read(db_dir: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    episodes: List[Dict[str, Any]] = []
    steps: List[Dict[str, Any]] = []
    dirs = [
        Path(d) for d in (db_dir if isinstance(db_dir, (list, tuple)) else [db_dir])
    ]
    shards = [
        s
        for d in dirs
        for s in (sorted(d.glob("shard-*.db")) or sorted(d.glob("*.db")))
    ]
    for shard in shards:
        with closing(sqlite3.connect(str(shard))) as conn:
            conn.row_factory = sqlite3.Row
            version = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if version is None or int(version[0]) != SCHEMA_VERSION:
                raise ValueError(f"{shard}: schema version mismatch")
            episodes += [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM episodes WHERE outcome IS NOT NULL"
                )
            ]
            steps += [dict(r) for r in conn.execute("SELECT * FROM steps")]
    return episodes, steps, [s.name for s in shards]


def _flatten(step: Dict[str, Any], episode: Dict[str, Any]) -> Dict[str, Any]:
    row = {
        k: v for k, v in step.items() if k not in ("before", "after", "model_decisions")
    }
    for prefix, key in (("b_", "before"), ("a_", "after")):
        snap = json.loads(step[key]) if step.get(key) else {}
        for name, value in (snap or {}).items():
            row[prefix + name] = value
    row.update(
        scene_id=episode["scene_id"],
        planner=episode["planner"],
        task_kind=episode["task_kind"],
        injected_fault=episode["injected_fault"],
        episode_outcome=episode["outcome"],
    )
    return row


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    columns: List[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def report(
    splits: Dict[str, List[Dict[str, Any]]], episodes: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, Any]:
    all_rows = [r for rows in splits.values() for r in rows]
    fail_types = Counter(r["failure_type"] for r in all_rows)
    actions: Dict[str, Counter] = defaultdict(Counter)
    for r in all_rows:
        actions[r["action"]]["success" if r["success"] == 1 else "failure"] += 1
    per_split = {
        name: {
            "steps": len(rows),
            "episodes": len(episodes[name]),
            "scenes": len({e["scene_id"] for e in episodes[name]}),
            "step_success_rate": round(
                sum(r["success"] == 1 for r in rows) / max(len(rows), 1), 4
            ),
            "mission_success_rate": round(
                sum(e["outcome"] == "succeeded" for e in episodes[name])
                / max(len(episodes[name]), 1),
                4,
            ),
        }
        for name, rows in splits.items()
    }
    thin = [
        t
        for t in FAILURE_TYPES
        if t != "none" and fail_types.get(t, 0) < MIN_FAILURES_PER_TYPE
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "total_labelled_steps": len(all_rows),
        "total_episodes": sum(len(v) for v in episodes.values()),
        "scenes": len({e["scene_id"] for v in episodes.values() for e in v}),
        "per_split": per_split,
        "failure_types": {t: fail_types.get(t, 0) for t in FAILURE_TYPES},
        "coverage_per_action": {a: dict(c) for a, c in sorted(actions.items())},
        "episode_outcomes": dict(
            Counter(e["outcome"] for v in episodes.values() for e in v)
        ),
        "reflection_verdicts": dict(Counter(r["verdict"] for r in all_rows)),
        "failure_types_below_minimum": thin,
        "min_failures_per_type": MIN_FAILURES_PER_TYPE,
    }


def _markdown(rep: Dict[str, Any]) -> str:
    lines = ["# MILO episode dataset report", ""]
    lines += [
        f"- labelled steps: **{rep['total_labelled_steps']}**, episodes: **{rep['total_episodes']}**, scenes: **{rep['scenes']}**",
        "",
    ]
    lines += [
        "## Splits",
        "",
        "| split | steps | episodes | scenes | step success | mission success |",
        "|---|---|---|---|---|---|",
    ]
    for name, s in rep["per_split"].items():
        lines.append(
            f"| {name} | {s['steps']} | {s['episodes']} | {s['scenes']} | {s['step_success_rate']} | {s['mission_success_rate']} |"
        )
    lines += [
        "",
        "## Failure types (labelled steps)",
        "",
        "| type | steps |",
        "|---|---|",
    ]
    lines += [f"| {t} | {n} |" for t, n in rep["failure_types"].items()]
    if rep["failure_types_below_minimum"]:
        lines += [
            "",
            f"**Below {rep['min_failures_per_type']} examples:** {', '.join(rep['failure_types_below_minimum'])}",
        ]
    lines += [
        "",
        "## Coverage per action",
        "",
        "| action | success | failure |",
        "|---|---|---|",
    ]
    lines += [
        f"| {a} | {c.get('success', 0)} | {c.get('failure', 0)} |"
        for a, c in rep["coverage_per_action"].items()
    ]
    return "\n".join(lines) + "\n"


def build(
    db_dir: Any,
    out: Path,
    test_frac: float = 0.2,
    val_frac: float = 0.15,
    seed: int = 0,
    test_scenes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    episodes, steps, shards = _read(db_dir)
    by_id = {e["episode_id"]: e for e in episodes}
    split_of = assign_splits(
        {e["episode_id"]: e["scene_id"] for e in episodes},
        test_frac,
        val_frac,
        seed,
        test_scenes,
    )

    rows: Dict[str, List[Dict[str, Any]]] = {"train": [], "val": [], "test": []}
    eps: Dict[str, List[Dict[str, Any]]] = {"train": [], "val": [], "test": []}
    for e in episodes:
        eps[split_of[e["episode_id"]]].append(e)
    for s in steps:
        if s["success"] is None or s["episode_id"] not in by_id:
            continue  # skipped / cancelled steps carry no label
        rows[split_of[s["episode_id"]]].append(_flatten(s, by_id[s["episode_id"]]))

    out.mkdir(parents=True, exist_ok=True)
    for name in rows:
        _write_csv(out / f"{name}.csv", rows[name])
        _write_csv(out / f"episodes_{name}.csv", eps[name])
    rep = report(rows, eps)
    (out / "report.json").write_text(json.dumps(rep, indent=2))
    (out / "report.md").write_text(_markdown(rep))
    digest = hashlib.sha256(
        json.dumps(sorted(e["episode_id"] for e in episodes)).encode()
    ).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "data_hash": digest,
                "shards": shards,
                "seed": seed,
                "test_frac": test_frac,
                "val_frac": val_frac,
            },
            indent=2,
        )
    )
    return rep


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--db-dir", type=Path, nargs="+", default=[Path("data/episodes")]
    )
    parser.add_argument("--out", type=Path, default=Path("data/dataset"))
    parser.add_argument("--test-scene-frac", type=float, default=0.2)
    parser.add_argument("--val-frac", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--test-scenes",
        default=None,
        help="comma-separated scene ids to hold out (default: a hashed fraction)",
    )
    args = parser.parse_args(argv)
    held_out = args.test_scenes.split(",") if args.test_scenes else None
    rep = build(
        args.db_dir, args.out, args.test_scene_frac, args.val_frac, args.seed, held_out
    )
    print((args.out / "report.md").read_text())
    if rep["failure_types_below_minimum"]:
        print(
            "WARNING: too few examples for:",
            ", ".join(rep["failure_types_below_minimum"]),
        )


if __name__ == "__main__":
    main()
