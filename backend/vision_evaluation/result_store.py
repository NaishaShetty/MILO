"""
result_store.py (vision_evaluation)

Purpose
-------
Persists one perception benchmark run to
`results/perception/benchmark_runs/<run_id>/` -- `metadata.json`,
`depth_metrics.json`, `tracking_metrics.json`, `summary.json`. Mirrors
`backend/evaluation/result_store.py`'s conventions (never overwrite an
existing run directory, no secrets ever written) but is this package's
own implementation -- see `__init__.py` for why the two frameworks
don't share code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from vision_evaluation.models import MetricValue, RunMetadata, to_jsonable

#: backend/vision_evaluation/result_store.py -> repository root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RESULTS_DIR = _REPO_ROOT / "results" / "perception" / "benchmark_runs"


class PerceptionResultStoreError(Exception):
    """Raised when a benchmark run cannot be persisted -- currently only
    for a `run_id` collision (see `save()`)."""


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


class PerceptionResultStore:
    """Result-persistence layer for the perception benchmark. See module
    docstring."""

    def __init__(self, base_dir: Path = DEFAULT_RESULTS_DIR) -> None:
        self._base_dir = base_dir

    def save(
        self,
        run_metadata: RunMetadata,
        depth_metrics: Dict[str, MetricValue],
        tracking_metrics: Dict[str, MetricValue],
    ) -> Path:
        """Writes one run's output to a fresh `<base_dir>/<run_id>/`
        directory and returns that path.

        Raises:
            PerceptionResultStoreError: If the directory already exists
                -- a `run_id` collision would silently overwrite a
                previous run's results, which this store never does.
        """

        run_dir = self._base_dir / run_metadata.run_id
        if run_dir.exists():
            raise PerceptionResultStoreError(
                f"Benchmark run directory already exists: {run_dir}"
            )
        run_dir.mkdir(parents=True)

        _write_json(run_dir / "metadata.json", to_jsonable(run_metadata))
        _write_json(
            run_dir / "depth_metrics.json",
            {name: to_jsonable(metric) for name, metric in depth_metrics.items()},
        )
        _write_json(
            run_dir / "tracking_metrics.json",
            {name: to_jsonable(metric) for name, metric in tracking_metrics.items()},
        )
        _write_json(
            run_dir / "summary.json",
            self._build_summary(run_metadata, depth_metrics, tracking_metrics),
        )

        return run_dir

    @staticmethod
    def _build_summary(
        run_metadata: RunMetadata,
        depth_metrics: Dict[str, MetricValue],
        tracking_metrics: Dict[str, MetricValue],
    ) -> Any:
        return {
            "run_id": run_metadata.run_id,
            "timestamp": run_metadata.timestamp,
            "evaluation_version": run_metadata.evaluation_version,
            "dataset_version": run_metadata.dataset_version,
            "depth_source": run_metadata.depth_source,
            "depth": {name: metric.value for name, metric in depth_metrics.items()},
            "tracking": {
                name: metric.value for name, metric in tracking_metrics.items()
            },
        }
