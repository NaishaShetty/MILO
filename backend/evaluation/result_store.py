"""
result_store.py

Purpose
-------
Persists one benchmark run's outputs to
`results/language/benchmark_runs/<run_id>/`, per the spec's "Result
Storage" and "Reproducibility" requirements: `metadata.json` (what
configuration produced this run), `raw_results.json` (every
`RawBenchmarkRecord`), `metrics.json` (the `MetricsReport`), and
`summary.json` (a small, human-scannable digest of the two). This is
the only module in `backend/evaluation/` that touches the filesystem
for output -- every other module stays pure/in-memory, so tests never
need to touch disk to exercise scoring logic.

Never overwritten, never leaks credentials
-------------------------------------------------
Each run gets a directory named after its `run_id`
(`models.generate_run_id`, time-sortable and collision-resistant);
`save()` refuses to write into an existing directory (spec: "Do not
overwrite previous benchmark runs by default. Each run must have a
unique identifier."). `RunMetadata` (see `models.py`) is constructed
without any field capable of holding a credential -- there is no
"extra"/passthrough dict on this path that could accidentally carry an
API key into a committed result file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Sequence

from evaluation.exceptions import ResultStoreError
from evaluation.models import (
    MetricsReport,
    RawBenchmarkRecord,
    RecoveryReport,
    RunMetadata,
    to_jsonable,
)

#: `backend/evaluation/result_store.py` -> repository root, mirroring
#: `dataset_loader.py`'s own `.resolve().parents` pattern.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RESULTS_DIR = _REPO_ROOT / "results" / "language" / "benchmark_runs"


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


class BenchmarkResultStore:
    """Phase 3.6's result-persistence layer -- see module docstring."""

    def __init__(self, base_dir: Path = DEFAULT_RESULTS_DIR) -> None:
        self._base_dir = base_dir

    def save(
        self,
        run_metadata: RunMetadata,
        records: Sequence[RawBenchmarkRecord],
        metrics: MetricsReport,
        recovery: Optional[RecoveryReport] = None,
    ) -> Path:
        """
        Writes one run's full output to a fresh
        `<base_dir>/<run_id>/` directory and returns that path. Raises
        `ResultStoreError` if the directory already exists -- a
        `run_id` collision would silently overwrite a previous
        researcher's results, which this framework never does.
        `recovery`, when given, is additionally written to
        `recovery.json` (Phase 3.6.6's own report -- optional since not
        every caller needs a standalone recovery analysis alongside the
        general metrics).
        """
        run_dir = self._base_dir / run_metadata.run_id
        if run_dir.exists():
            raise ResultStoreError(f"Benchmark run directory already exists: {run_dir}")
        run_dir.mkdir(parents=True)

        _write_json(run_dir / "metadata.json", to_jsonable(run_metadata))
        _write_json(
            run_dir / "raw_results.json", [to_jsonable(record) for record in records]
        )
        _write_json(run_dir / "metrics.json", to_jsonable(metrics))
        _write_json(
            run_dir / "summary.json", self._build_summary(run_metadata, metrics)
        )
        if recovery is not None:
            _write_json(run_dir / "recovery.json", to_jsonable(recovery))
        return run_dir

    @staticmethod
    def _build_summary(run_metadata: RunMetadata, metrics: MetricsReport) -> Any:
        """
        A small, human-scannable digest -- the file a researcher opens
        first, before `metrics.json`'s full detail. Derived entirely
        from `run_metadata`/`metrics`, never a separate source of truth
        (nothing here is computed independently of what `metrics.json`
        already contains).
        """
        return {
            "run_id": run_metadata.run_id,
            "timestamp": run_metadata.timestamp,
            "benchmark_version": run_metadata.benchmark_version,
            "provider": run_metadata.provider,
            "model": run_metadata.model,
            "prompt_version": run_metadata.prompt_version,
            "schema_version": run_metadata.schema_version,
            "run_mode": run_metadata.run_mode.value,
            "num_cases": run_metadata.num_cases,
            "num_completed": run_metadata.num_completed,
            "num_failed": run_metadata.num_failed,
            "task_accuracy_micro": metrics.overall.task_accuracy_micro.value,
            "task_accuracy_macro": metrics.overall.task_accuracy_macro.value,
            "per_category_task_accuracy": {
                category: category_metrics.accuracy["task_accuracy"].value
                for category, category_metrics in metrics.per_category.items()
            },
            "average_latency_ms": metrics.overall.latency_stats.average_ms,
        }
