"""
loader.py (backend/planning_evaluation)

Purpose
-------
Loads `dataset/v1.0/tasks.json` (the `milo_benchmark` dataset) into
`BenchmarkTask` records the runner can execute -- the one place that
knows the JSON schema, so `run_benchmark.py`/`run_memory_ablation.py`
never parse the dataset file directly.

`tasks.json`'s shape: a flat top-level JSON array of 25 task records
(one dict per task) -- not a single wrapper object with a nested
`tasks` list. This matters for more than local loading: the Hugging
Face Hub's dataset viewer and `datasets.load_dataset("json", ...)`
both auto-infer a tabular schema from a top-level array of same-shaped
records, but treat a single wrapper object as exactly one row (with a
non-tabular nested list buried inside it) -- the earlier nested shape
is why the published `naishashetty/milo_benchmark` repo's viewer
showed "1 rows" instead of 25. Dataset-level metadata (name, version,
description, license, difficulty-tier definitions) intentionally lives
only in the dataset card (`dataset/v1.0/README.md`'s prose and YAML
front matter) now, not as a field inside every row or as a sibling key
next to the array.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from schemas.task import SingleTask

DATASET_DIR = Path(__file__).resolve().parent / "dataset"


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    scene: str
    room_type: str
    difficulty_tier: str
    instruction: str
    goal: str
    object: Optional[str]
    target: Optional[str]
    notes: str = ""

    def to_single_task(self) -> SingleTask:
        return SingleTask(
            goal=self.goal,
            object=self.object,
            target=self.target,
            task_id=self.task_id,
        )


def load_tasks(version: str = "1.0") -> List[BenchmarkTask]:
    """Loads every task from `dataset/v<version>/tasks.json`, in file order.

    `tasks.json` is a flat top-level JSON array of task records -- see
    this module's docstring for why that shape matters.
    """
    path = DATASET_DIR / f"v{version}" / "tasks.json"
    raw = json.loads(path.read_text())
    return [
        BenchmarkTask(
            task_id=row["task_id"],
            scene=row["scene"],
            room_type=row["room_type"],
            difficulty_tier=row["difficulty_tier"],
            instruction=row["instruction"],
            goal=row["goal"],
            object=row.get("object"),
            target=row.get("target"),
            notes=row.get("notes", ""),
        )
        for row in raw
    ]
