"""
run_evaluation.py (backend/memory_evaluation)

Purpose
-------
CLI entry point measuring `backend/memory/retrieval.RetrievalEngine`
against `dataset.py`'s fixed evaluation set -- Recall@K, Precision@K,
MRR, and latency (phase spec sections 20/22), across each ablation
config in `ablation.py` (section 21). Run with:

    cd backend && python -m memory_evaluation.run_evaluation

Unlike `evaluation/run_benchmark.py` (Phase 3.6, gated behind
`RUN_LLM_BENCHMARK=true` because it calls a real, billed LLM API), this
script has no such gate: `HashingEmbedder` is offline, free, and fast,
so running it is always safe -- matching `vision_evaluation/
run_benchmark.py`'s "synthetic, always safe to run" precedent, not
`evaluation/run_benchmark.py`'s "costs money, opt-in" one.
"""

from __future__ import annotations

import platform
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

from memory.embeddings import HashingEmbedder
from memory.manager import MemoryManager
from memory.retrieval import RankingWeights, RetrievalEngine
from memory.sqlite_store import SQLiteMemoryStore
from memory.sqlite_vector_store import SQLiteVectorStore
from memory_evaluation.ablation import ABLATION_CONFIGS
from memory_evaluation.dataset import EVAL_QUERIES, build_dataset
from memory_evaluation.metrics import (
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)

#: Fixed "now" for recency scoring -- matches `dataset.py`'s
#: `BASE_TIME`, keeping every ablation run's recency component (and
#: therefore its score/ranking) identical across repeated runs.
EVAL_NOW = 1_700_000_000.0


def _build_engine(
    dimension: int, database_dir: Path, weights: RankingWeights
) -> RetrievalEngine:
    manager = MemoryManager(store=SQLiteMemoryStore(database_dir / "memory.db"))
    embedder = HashingEmbedder(dimension=dimension)
    vector_store = SQLiteVectorStore(database_dir / "vectors.db", dimension=dimension)
    return RetrievalEngine(manager, vector_store, embedder, weights=weights)


def run_evaluation(top_k: int = 5) -> Dict[str, Any]:
    """
    Runs every ablation config against the fixed dataset/query set and
    returns a report dict: per-config Recall@K/Precision@K (K in
    `(1, 3, top_k)`), MRR, mean/p95 latency (milliseconds), plus
    dataset/environment metadata for reproducibility (section 22).
    """
    dataset = build_dataset()
    report: Dict[str, Any] = {
        "dataset_size": len(dataset),
        "num_queries": len(EVAL_QUERIES),
        "top_k": top_k,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "embedder": "HashingEmbedder",
        "configs": {},
    }

    for config_name, weights in ABLATION_CONFIGS.items():
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_dir = Path(tmp_dir)
            engine = _build_engine(
                dimension=512, database_dir=database_dir, weights=weights
            )
            for memory in dataset:
                engine.store_and_index(memory)

            latencies_ms: List[float] = []
            all_retrieved: List[List[str]] = []
            all_expected = [q.expected_memory_ids for q in EVAL_QUERIES]

            for query in EVAL_QUERIES:
                start = time.perf_counter()
                results = engine.retrieve(
                    query.query,
                    memory_types=query.memory_types,
                    top_k=top_k,
                    now=EVAL_NOW,
                )
                latencies_ms.append((time.perf_counter() - start) * 1000.0)
                all_retrieved.append([r.memory.memory_id for r in results])

            sorted_latencies = sorted(latencies_ms)
            p95_index = min(
                len(sorted_latencies) - 1, int(0.95 * len(sorted_latencies))
            )

            recalls = {
                k: sum(
                    recall_at_k(retrieved, expected, k)
                    for retrieved, expected in zip(all_retrieved, all_expected)
                )
                / len(EVAL_QUERIES)
                for k in (1, 3, top_k)
            }
            precisions = {
                k: sum(
                    precision_at_k(retrieved, expected, k)
                    for retrieved, expected in zip(all_retrieved, all_expected)
                )
                / len(EVAL_QUERIES)
                for k in (1, 3, top_k)
            }

            report["configs"][config_name] = {
                "recall_at_k": recalls,
                "precision_at_k": precisions,
                "mrr": mean_reciprocal_rank(all_retrieved, all_expected),
                "mean_latency_ms": sum(latencies_ms) / len(latencies_ms),
                "p95_latency_ms": sorted_latencies[p95_index],
            }

    return report


def _print_report(report: Dict[str, Any]) -> None:
    print(
        f"Dataset: {report['dataset_size']} memories, "
        f"{report['num_queries']} queries, top_k={report['top_k']}"
    )
    print(f"Embedder: {report['embedder']} | Python {report['python_version']}")
    print()
    header = f"{'config':<32}{'R@1':>8}{'R@3':>8}{'R@k':>8}{'P@1':>8}{'MRR':>8}{'mean_ms':>10}"
    print(header)
    print("-" * len(header))
    for name, metrics in report["configs"].items():
        print(
            f"{name:<32}"
            f"{metrics['recall_at_k'][1]:>8.2f}"
            f"{metrics['recall_at_k'][3]:>8.2f}"
            f"{metrics['recall_at_k'][report['top_k']]:>8.2f}"
            f"{metrics['precision_at_k'][1]:>8.2f}"
            f"{metrics['mrr']:>8.2f}"
            f"{metrics['mean_latency_ms']:>10.3f}"
        )


if __name__ == "__main__":
    _print_report(run_evaluation())
