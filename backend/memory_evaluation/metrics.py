"""
metrics.py (backend/memory_evaluation)

Purpose
-------
Recall@K, Precision@K, and MRR for a list of retrieved-id rankings
against expected-relevant-id sets -- the phase spec's section 20/26
required evaluation metrics. Deliberately generic (operates on plain
`Sequence[str]`/`Set[str]`, not on `MemoryResult`/`EvalQuery` directly)
so these functions are independently testable with hand-constructed
inputs, matching `backend/evaluation/metrics.py`'s own "pure functions
over plain data" convention for the Language evaluation framework.
"""

from __future__ import annotations

from typing import Sequence, Set


def recall_at_k(retrieved_ids: Sequence[str], expected_ids: Set[str], k: int) -> float:
    """
    Fraction of `expected_ids` present anywhere in `retrieved_ids[:k]`.
    `1.0` when `expected_ids` is empty (nothing to miss) -- matches the
    conventional definition and avoids a divide-by-zero.
    """
    if not expected_ids:
        return 1.0
    top_k = set(retrieved_ids[:k])
    hits = len(top_k & expected_ids)
    return hits / len(expected_ids)


def precision_at_k(
    retrieved_ids: Sequence[str], expected_ids: Set[str], k: int
) -> float:
    """
    Fraction of `retrieved_ids[:k]` that are actually in `expected_ids`.
    `0.0` when nothing was retrieved (rather than dividing by zero) --
    an empty result set has zero precision, not undefined precision.
    """
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for memory_id in top_k if memory_id in expected_ids)
    return hits / len(top_k)


def reciprocal_rank(retrieved_ids: Sequence[str], expected_ids: Set[str]) -> float:
    """`1 / rank` of the first relevant id in `retrieved_ids` (1-indexed), or `0.0` if none."""
    for rank, memory_id in enumerate(retrieved_ids, start=1):
        if memory_id in expected_ids:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(
    all_retrieved_ids: Sequence[Sequence[str]], all_expected_ids: Sequence[Set[str]]
) -> float:
    """Mean of `reciprocal_rank()` across a batch of queries."""
    if not all_retrieved_ids:
        return 0.0
    scores = [
        reciprocal_rank(retrieved, expected)
        for retrieved, expected in zip(all_retrieved_ids, all_expected_ids)
    ]
    return sum(scores) / len(scores)
