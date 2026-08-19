"""
loader.py (backend/planning_evaluation)

Purpose
-------
Loads `dataset/v<version>/tasks.json` (the `milo_benchmark` dataset)
into `BenchmarkTask` records the runner can execute -- the one place
that knows the JSON schema, so `run_benchmark.py`/`run_memory_ablation.py`
never parse the dataset file directly.

`tasks.json`'s shape: a flat top-level JSON array of task records (one
dict per task) -- not a single wrapper object with a nested `tasks`
list. This matters for more than local loading: the Hugging Face Hub's
dataset viewer and `datasets.load_dataset("json", ...)` both
auto-infer a tabular schema from a top-level array of same-shaped
records, but treat a single wrapper object as exactly one row (with a
non-tabular nested list buried inside it) -- the earlier nested shape
is why the published `naishashetty/milo_benchmark` repo's viewer
showed "1 rows" instead of 25. Dataset-level metadata (name, version,
description, license, difficulty-tier definitions) intentionally lives
only in the dataset card (`dataset/v<version>/README.md`'s prose and
YAML front matter) now, not as a field inside every row or as a
sibling key next to the array.

`v1.1`'s `tier4_multi_step` addition -- `subtasks`
----------------------------------------------------
Every `tier1_locate`/`tier2_pickup`/`tier3_store` row keeps the
original flat `goal`/`object`/`target` shape (`subtasks: null`). A
`tier4_multi_step` row instead sets `goal`/`object`/`target` to `null`
and populates `subtasks`: an ordered list of `{"goal", "object",
"target"}` dicts, each an independent single-object sub-goal (see
`dataset/v1.1/README.md`'s "New in v1.1" section for why two
*independent* sub-goals, rather than a nested `MultiTask`, is the
right shape here -- no planner in this project accepts anything but a
`SingleTask`, so the runner executes each sub-goal as its own
`TaskRunner.run()` call against the same live simulator/episode, in
order). `BenchmarkTask.subtasks` is `None` for every non-tier4 row;
`BenchmarkTask.to_single_task()` stays valid only for those.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from schemas.task import SingleTask

DATASET_DIR = Path(__file__).resolve().parent / "dataset"


@dataclass(frozen=True)
class SubtaskSpec:
    """One independent sub-goal of a `tier4_multi_step` task."""

    goal: str
    object: Optional[str]
    target: Optional[str]


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    scene: str
    room_type: str
    difficulty_tier: str
    instruction: str
    goal: Optional[str]
    object: Optional[str]
    target: Optional[str]
    notes: str = ""
    #: Set only for `tier4_multi_step` rows -- see this module's
    #: docstring. `None` for every `tier1_locate`/`tier2_pickup`/
    #: `tier3_store` row, which use the flat `goal`/`object`/`target`
    #: fields above instead.
    subtasks: Optional[List[SubtaskSpec]] = None

    def to_single_task(self) -> SingleTask:
        if self.subtasks is not None:
            raise ValueError(
                f"{self.task_id} is a multi-subtask task (tier4_multi_step) "
                "-- use to_single_tasks() instead of to_single_task()."
            )
        return SingleTask(
            goal=self.goal,
            object=self.object,
            target=self.target,
            task_id=self.task_id,
        )

    def to_single_tasks(self) -> List[SingleTask]:
        """
        Uniform accessor for any `BenchmarkTask`: one `SingleTask` for a
        flat row, or one `SingleTask` per `subtasks` entry (in order)
        for a `tier4_multi_step` row. Each subtask's `SingleTask.task_id`
        is suffixed (`-sub1`, `-sub2`, ...) so per-subtask plans/episodes
        stay individually identifiable in logs/memory without colliding
        with the parent `task_id`.
        """
        if self.subtasks is None:
            return [self.to_single_task()]
        return [
            SingleTask(
                goal=sub.goal,
                object=sub.object,
                target=sub.target,
                task_id=f"{self.task_id}-sub{i}",
            )
            for i, sub in enumerate(self.subtasks, start=1)
        ]


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
            goal=row.get("goal"),
            object=row.get("object"),
            target=row.get("target"),
            notes=row.get("notes", ""),
            subtasks=(
                [SubtaskSpec(**sub) for sub in row["subtasks"]]
                if row.get("subtasks")
                else None
            ),
        )
        for row in raw
    ]
