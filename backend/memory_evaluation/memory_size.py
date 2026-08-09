"""
memory_size.py (backend/memory_evaluation)

Purpose
-------
Section 14 of the Phase 6.4 spec: how retrieval latency/quality and
task success change as the memory store grows. Distractor memories are
built with the existing `memory.semantics.build_semantic_memory`
factory (never a bespoke shape) and explicitly tagged
`metadata["synthetic"] = True` -- clearly identified as synthetic
evaluation data, not a real observation, and never encoding the
benchmark's actual answer. The one real fact each run needs to still
find ("mug located_on table") is always seeded through
`MemoryAgent.remember_observation()`, the same production write path
every other module in this package uses -- distractor volume is the
only thing that changes between sizes.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from _execution_test_helpers import FakeSimulator  # noqa: E402

from memory.agent import MemoryQueryContext  # noqa: E402
from memory.models import Memory, MemoryProvenance  # noqa: E402
from memory.semantics import build_semantic_memory  # noqa: E402
from memory_evaluation.experiment import _build_memory_agent  # noqa: E402
from memory_evaluation.scenarios import CATEGORY_A_OBJECT_RECALL  # noqa: E402
from orchestration.task_runner import TaskRunner  # noqa: E402
from planner.rule_based import RuleBasedPlanner  # noqa: E402

_DISTRACTOR_SUBJECTS = [
    "lamp", "vase", "remote", "book", "pillow", "plate", "bowl", "cup",
    "knife", "fork", "spoon", "pan", "pot", "towel", "soap", "bottle",
    "box", "basket", "toy", "clock",
]  # fmt: skip
_DISTRACTOR_PREDICATES = ["located_on", "located_in", "typically_stored_in"]
_DISTRACTOR_OBJECTS = [
    "shelf", "drawer", "counter", "cabinet", "floor", "desk", "sink", "closet",
]  # fmt: skip


def _make_distractor(index: int) -> Memory:
    """A synthetic, clearly-tagged filler memory -- never resembles the
    benchmark's real "mug located_on table" fact (different subject
    vocabulary entirely)."""
    subject = f"{_DISTRACTOR_SUBJECTS[index % len(_DISTRACTOR_SUBJECTS)]}_{index}"
    predicate = _DISTRACTOR_PREDICATES[index % len(_DISTRACTOR_PREDICATES)]
    obj = _DISTRACTOR_OBJECTS[index % len(_DISTRACTOR_OBJECTS)]
    return build_semantic_memory(
        subject,
        predicate,
        obj,
        provenance=MemoryProvenance.INFERENCE,
        confidence=0.3,
        extra_metadata={"synthetic": True, "distractor_index": index},
    )


@dataclass
class MemorySizeResult:
    memory_count: int
    retrieval_latency_ms: float
    task_success: bool
    plan_targets: List[Optional[str]]
    memory_context_count: int
    real_memory_retrieved: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_count": self.memory_count,
            "retrieval_latency_ms": self.retrieval_latency_ms,
            "task_success": self.task_success,
            "plan_targets": self.plan_targets,
            "memory_context_count": self.memory_context_count,
            "real_memory_retrieved": self.real_memory_retrieved,
        }


def run_memory_size_experiment(
    database_dir: Path, sizes: Sequence[int] = (10, 100, 1000)
) -> List[MemorySizeResult]:
    """
    For each `size`: builds a fresh memory subsystem, seeds `size`
    synthetic distractors plus the one real fact, measures retrieval
    latency/quality for the recall query, then runs Category A's
    second episode end to end through `TaskRunner` and records task
    success -- distractor volume is the only variable across sizes.
    """
    results: List[MemorySizeResult] = []
    episode = CATEGORY_A_OBJECT_RECALL.episodes[1]

    for size in sizes:
        agent = _build_memory_agent(database_dir / f"size_{size}")
        # `_build_memory_agent` always points at a fresh, writable
        # temporary directory this function controls -- construction
        # cannot fail here the way it can for an arbitrary caller-
        # supplied path (see `MemoryAgent.from_config`'s docstring).
        assert agent.engine is not None
        for i in range(size):
            agent.engine.store_and_index(_make_distractor(i))
        real_memory = agent.remember_observation(
            "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
        )
        memory_count = len(agent.engine.manager.list())

        query = MemoryQueryContext(goal="find", object="mug", task_id="size-probe")
        started = time.perf_counter()
        context = agent.retrieve_relevant_memories(query, top_k=5)
        latency_ms = (time.perf_counter() - started) * 1000.0
        real_retrieved = real_memory is not None and any(
            r.memory.memory_id == real_memory.memory_id for r in context.results
        )

        simulator = FakeSimulator(objects=episode.objects)
        runner = TaskRunner(RuleBasedPlanner(), simulator, memory_agent=agent)
        run_result = runner.run(episode.task, memory_enabled=True)
        plan = run_result.planning_result.plan
        plan_targets = [s.target for s in plan.steps] if plan is not None else []

        results.append(
            MemorySizeResult(
                memory_count=memory_count,
                retrieval_latency_ms=latency_ms,
                task_success=run_result.succeeded,
                plan_targets=plan_targets,
                memory_context_count=len(context.results),
                real_memory_retrieved=real_retrieved,
            )
        )
    return results
