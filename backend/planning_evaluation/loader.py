"""
loader.py (backend/planning_evaluation)

Purpose
-------
Loads `dataset/v1.0/tasks.json` (the `milo_benchmark` dataset) into
`BenchmarkTask` records the runner can execute -- the one place that
knows the JSON schema, so `run_benchmark.py`/`run_memory_ablation.py`
never parse the dataset file directly.
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
    """Loads every task from `dataset/v<version>/tasks.json`, in file order."""
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
        for row in raw["tasks"]
    ]
