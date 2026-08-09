"""
test_memory_evaluation.py

Purpose
-------
Tests for `backend/memory_evaluation/`: metric correctness (hand-
constructed cases), the evaluation dataset's internal consistency, and
that `run_evaluation()` produces sane Recall@K/Precision@K/MRR/latency
across every ablation config -- Phase 6.2 spec sections 19-21.
"""

from __future__ import annotations

from memory_evaluation.ablation import ABLATION_CONFIGS
from memory_evaluation.dataset import EVAL_QUERIES, build_dataset
from memory_evaluation.metrics import (
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from memory_evaluation.run_evaluation import run_evaluation


class TestMetricsHandConstructed:
    def test_recall_at_k_all_found(self):
        assert recall_at_k(["a", "b", "c"], {"a", "b"}, k=3) == 1.0

    def test_recall_at_k_partial(self):
        assert recall_at_k(["a", "x", "y"], {"a", "b"}, k=3) == 0.5

    def test_recall_at_k_respects_k_cutoff(self):
        assert recall_at_k(["x", "y", "a"], {"a"}, k=2) == 0.0
        assert recall_at_k(["x", "y", "a"], {"a"}, k=3) == 1.0

    def test_recall_at_k_empty_expected_is_perfect(self):
        assert recall_at_k(["a"], set(), k=1) == 1.0

    def test_precision_at_k_all_relevant(self):
        assert precision_at_k(["a", "b"], {"a", "b", "c"}, k=2) == 1.0

    def test_precision_at_k_none_relevant(self):
        assert precision_at_k(["x", "y"], {"a"}, k=2) == 0.0

    def test_precision_at_k_empty_retrieval(self):
        assert precision_at_k([], {"a"}, k=5) == 0.0

    def test_reciprocal_rank_first_position(self):
        assert reciprocal_rank(["a", "b"], {"a"}) == 1.0

    def test_reciprocal_rank_third_position(self):
        assert reciprocal_rank(["x", "y", "a"], {"a"}) == 1.0 / 3

    def test_reciprocal_rank_not_found(self):
        assert reciprocal_rank(["x", "y"], {"a"}) == 0.0

    def test_mean_reciprocal_rank_averages_across_queries(self):
        retrieved = [["a", "x"], ["x", "a"]]
        expected = [{"a"}, {"a"}]
        assert mean_reciprocal_rank(retrieved, expected) == (1.0 + 0.5) / 2

    def test_mean_reciprocal_rank_empty_batch(self):
        assert mean_reciprocal_rank([], []) == 0.0


class TestDatasetConsistency:
    def test_dataset_has_unique_memory_ids(self):
        ids = [m.memory_id for m in build_dataset()]
        assert len(ids) == len(set(ids))

    def test_every_expected_query_id_exists_in_the_dataset(self):
        dataset_ids = {m.memory_id for m in build_dataset()}
        for query in EVAL_QUERIES:
            assert query.expected_memory_ids.issubset(dataset_ids)

    def test_dataset_covers_every_memory_type(self):
        from memory.models import MemoryType

        types_present = {m.memory_type for m in build_dataset()}
        assert types_present == set(MemoryType)

    def test_dataset_build_is_deterministic(self):
        first = build_dataset()
        second = build_dataset()
        assert [m.memory_id for m in first] == [m.memory_id for m in second]
        assert [m.content for m in first] == [m.content for m in second]


class TestRunEvaluation:
    def test_run_evaluation_covers_every_ablation_config(self):
        report = run_evaluation(top_k=5)
        assert set(report["configs"].keys()) == set(ABLATION_CONFIGS.keys())

    def test_metrics_are_within_valid_ranges(self):
        report = run_evaluation(top_k=5)
        for metrics in report["configs"].values():
            for recall in metrics["recall_at_k"].values():
                assert 0.0 <= recall <= 1.0
            for precision in metrics["precision_at_k"].values():
                assert 0.0 <= precision <= 1.0
            assert 0.0 <= metrics["mrr"] <= 1.0
            assert metrics["mean_latency_ms"] >= 0.0
            assert metrics["p95_latency_ms"] >= 0.0

    def test_recall_at_top_k_is_perfect_on_this_fixed_dataset(self):
        # Every expected memory appears somewhere in the candidate pool
        # (dataset is small relative to top_k) for the full hybrid
        # config -- a regression here means retrieval broke, not that
        # the dataset is unreasonably easy (see docs/phases/
        # phase6_memory.md's evaluation section for the measured
        # numbers this asserts against).
        report = run_evaluation(top_k=5)
        full_hybrid = report["configs"]["D_full_hybrid"]
        assert full_hybrid["recall_at_k"][5] == 1.0

    def test_vector_only_is_never_better_than_full_hybrid_on_mrr(self):
        # Not a universal truth about hybrid retrieval -- specific to
        # this dataset/embedder, asserted to catch a ranking-formula
        # regression that makes the extra signals actively harmful.
        report = run_evaluation(top_k=5)
        assert (
            report["configs"]["D_full_hybrid"]["mrr"]
            >= report["configs"]["A_vector_only"]["mrr"]
        )

    def test_run_evaluation_is_deterministic(self):
        first = run_evaluation(top_k=5)
        second = run_evaluation(top_k=5)
        for name in ABLATION_CONFIGS:
            assert (
                first["configs"][name]["recall_at_k"]
                == second["configs"][name]["recall_at_k"]
            )
            assert first["configs"][name]["mrr"] == second["configs"][name]["mrr"]
