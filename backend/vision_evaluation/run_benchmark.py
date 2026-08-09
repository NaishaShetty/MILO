"""
run_benchmark.py

Purpose
-------
CLI entry point for the perception benchmark: runs the synthetic depth
and tracking benchmarks (`benchmark_runner.py`) and persists the result
via `PerceptionResultStore`.

Why this needs no `RUN_..._BENCHMARK` opt-in gate (unlike the language
benchmark)
------------------------------------------------------------------------------
`backend/evaluation/run_benchmark.py` requires `RUN_LLM_BENCHMARK=true`
because it can make real, costly network calls to an LLM provider. This
benchmark only ever runs deterministic, synthetic, in-process code (no
network, no model weights, no GPU) -- there is no cost or non-determinism
to gate behind an explicit opt-in, so it runs directly. This also means
it's safe to exercise from `backend/tests/test_vision_evaluation.py` as
a normal, always-on CI test (writing to a `tmp_path`, never the real
`results/` directory a developer might have local runs in).

Usage
-----
    cd backend && python -m vision_evaluation.run_benchmark
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from vision_evaluation.benchmark_runner import (
    run_depth_benchmark,
    run_tracking_benchmark,
)
from vision_evaluation.models import (
    PERCEPTION_BENCHMARK_VERSION,
    MetricValue,
    RunMetadata,
    generate_run_id,
)
from vision_evaluation.result_store import DEFAULT_RESULTS_DIR, PerceptionResultStore


def run(seed: int = 0, results_dir: Optional[Path] = None) -> Path:
    """Runs the full synthetic perception benchmark and persists it.

    Args:
        seed: Seed for both the depth and tracking synthetic cases --
            same seed always reproduces the same run's raw inputs
            (though `run_id`/`timestamp` still differ per call).
        results_dir: Overrides `PerceptionResultStore`'s default output
            directory (`results/perception/benchmark_runs/`) -- used by
            tests to avoid writing into the real results tree.

    Returns:
        The path the run was written to.
    """

    depth_result = run_depth_benchmark(seed=seed)
    tracking_result = run_tracking_benchmark(seed=seed)

    depth_metrics: Dict[str, MetricValue] = {
        **{
            f"pixel_{name}": metric
            for name, metric in depth_result.pixel_metrics.items()
        },
        **{
            f"object_{name}": metric
            for name, metric in depth_result.object_metrics.items()
        },
    }

    run_metadata = RunMetadata(
        run_id=generate_run_id("perception"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        evaluation_version=PERCEPTION_BENCHMARK_VERSION,
        dataset_version="synthetic-v1",
        depth_source="synthetic",
        camera_intrinsics={},  # not applicable to the synthetic depth case --
        # object-level depth extraction only compares depth values, never
        # projects to 3D, so no intrinsics are exercised by this run.
        tracker_config={
            "iou_threshold": tracking_result.tracker_config.iou_threshold,
            "max_missed_frames": tracking_result.tracker_config.max_missed_frames,
            "use_3d_distance": tracking_result.tracker_config.use_3d_distance,
            "max_3d_distance_m": tracking_result.tracker_config.max_3d_distance_m,
        },
        num_depth_samples=depth_result.num_pixel_samples,
        num_tracking_frames=tracking_result.num_frames,
    )

    store = PerceptionResultStore(base_dir=results_dir or DEFAULT_RESULTS_DIR)
    return store.save(
        run_metadata=run_metadata,
        depth_metrics=depth_metrics,
        tracking_metrics=tracking_result.metrics,
    )


def main() -> None:
    run_dir = run()
    print(f"Perception benchmark run written to: {run_dir}")


if __name__ == "__main__":
    main()
