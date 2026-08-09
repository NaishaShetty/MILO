"""
dataset.py (backend/memory_evaluation)

Purpose
-------
A small, fully deterministic evaluation dataset for Phase 6.2's
retrieval engine -- section 20 of the phase spec. Every memory below
has an explicit, stable `memory_id` and `created_at` (via
`semantics.build_*_memory`'s `memory_id`/`created_at` overrides) so a
test/report can name "the expected relevant memory" for a query by a
fixed string, rather than a random UUID minted at import time. This
keeps the dataset -- unlike the memories a running system would form
-- reproducible across every run, exactly like `datasets/language/
evaluation/*.json` is for the Language Interface.

Why this lives in Python, not a `datasets/memory/*.json` file
--------------------------------------------------------------------
`datasets/language/evaluation/*.json` works because `SingleTask`/
`ParsedInstruction` round-trip cleanly through JSON. A `Memory` built
via `semantics.build_*_memory` is the *result* of calling a factory
function, not a flat record -- expressing it as JSON would mean either
duplicating the factories' logic in a JSON-to-Memory loader (a second
place `content` could drift from `metadata`, exactly what `semantics.
py`'s factories exist to prevent) or storing pre-computed `content`
strings in JSON that could silently drift from what the *current*
`format_*_content` functions would produce. Building the dataset by
calling the real factories keeps it validated against the same code
path production callers use, at the cost of not being a
`git diff`-friendly data file -- an acceptable trade for a ~10-record
dataset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Set

from memory.models import Memory, MemoryProvenance, MemoryType
from memory.semantics import (
    EpisodicDetails,
    FailureDetails,
    build_episodic_memory,
    build_failure_memory,
    build_semantic_memory,
    build_user_memory,
)

#: Fixed base timestamp (2023-11-14T22:13:20Z) -- arbitrary but fixed,
#: so every dataset memory's `created_at`/`observed_at` (offsets from
#: this) are identical on every run and every machine.
BASE_TIME = 1_700_000_000.0
_DAY = 86400.0


def build_dataset() -> List[Memory]:
    """Returns the fixed set of evaluation memories, newest-observation-independent."""
    return [
        # -- Semantic --------------------------------------------------
        build_semantic_memory(
            "refrigerator",
            "located_in",
            "kitchen",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.95,
            memory_id="sem-fridge-kitchen",
            created_at=BASE_TIME - 10 * _DAY,
        ),
        build_semantic_memory(
            "red_mug",
            "located_on",
            "dining_table",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.9,
            memory_id="sem-mug-table",
            created_at=BASE_TIME - 1 * _DAY,
        ),
        build_semantic_memory(
            "apple",
            "typically_stored_in",
            "lower_cabinet",
            provenance=MemoryProvenance.INFERENCE,
            confidence=0.7,
            memory_id="sem-apple-cabinet",
            created_at=BASE_TIME - 5 * _DAY,
        ),
        # -- Episodic ----------------------------------------------------
        build_episodic_memory(
            EpisodicDetails(
                task_summary="bring the red mug",
                outcome="success",
                location="kitchen",
                duration_seconds=42.0,
                relevant_objects=["red mug", "dining table"],
            ),
            episode_id="ep-mug-1",
            task_id="task-mug-1",
            memory_id="epi-mug-success",
            created_at=BASE_TIME - 1 * _DAY,
        ),
        build_episodic_memory(
            EpisodicDetails(
                task_summary="bring the apple",
                outcome="success",
                location="kitchen",
                duration_seconds=30.0,
                relevant_objects=["apple", "lower cabinet"],
            ),
            episode_id="ep-apple-1",
            task_id="task-apple-1",
            memory_id="epi-apple-success",
            created_at=BASE_TIME - 5 * _DAY,
        ),
        # -- Failure -------------------------------------------------
        build_failure_memory(
            FailureDetails(
                task="reach the kitchen",
                action="navigate",
                failure_reason="navigation blocked by chair in the kitchen",
                cause="a chair was in the path",
                recovery="took an alternate route around the chair",
                outcome="success",
            ),
            episode_id="ep-fridge-1",
            task_id="task-fridge-1",
            memory_id="fail-chair-block",
            created_at=BASE_TIME - 2 * _DAY,
        ),
        build_failure_memory(
            FailureDetails(
                task="open the refrigerator",
                action="open",
                failure_reason="refrigerator door was closed and blocked opening",
                cause="door closed",
                recovery="retried the open action",
                outcome="success",
            ),
            episode_id="ep-fridge-2",
            task_id="task-fridge-2",
            memory_id="fail-fridge-closed",
            created_at=BASE_TIME - 3 * _DAY,
        ),
        # -- User --------------------------------------------------------
        build_user_memory(
            "prefers",
            "tea",
            memory_id="user-prefers-tea",
            created_at=BASE_TIME - 20 * _DAY,
        ),
        build_user_memory(
            "stores_fruit_in",
            "lower_cabinet",
            memory_id="user-fruit-cabinet",
            created_at=BASE_TIME - 20 * _DAY,
        ),
    ]


@dataclass(frozen=True)
class EvalQuery:
    """One evaluation query: text, expected relevant `memory_id`s, and optional type filter."""

    query: str
    expected_memory_ids: Set[str]
    memory_types: Optional[List[MemoryType]] = None


EVAL_QUERIES: List[EvalQuery] = [
    EvalQuery("Where is the red mug?", {"sem-mug-table", "epi-mug-success"}),
    EvalQuery(
        "Where do we normally keep apples?",
        {"sem-apple-cabinet", "epi-apple-success"},
    ),
    EvalQuery(
        "Why did the robot fail to reach the refrigerator?",
        {"fail-chair-block", "fail-fridge-closed"},
        memory_types=[MemoryType.FAILURE],
    ),
    EvalQuery(
        "What happened the last time it searched for the mug?",
        {"epi-mug-success"},
    ),
    EvalQuery("Where is the refrigerator located?", {"sem-fridge-kitchen"}),
    EvalQuery("What beverage does the user prefer?", {"user-prefers-tea"}),
]
