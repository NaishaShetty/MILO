"""
test_vision_evaluation.py

Purpose
-------
Deterministic tests for the Phase 3.x perception benchmark
(`backend/vision_evaluation/`) -- metric math, synthetic data
generation, the benchmark runner (which exercises real
`BaseDepthEstimator`/`IoUTracker` code against synthetic inputs), and
result persistence. Entirely synthetic/in-process -- no network, no
model weights, no GPU -- so unlike the language benchmark, this suite
runs unconditionally in CI (see `run_benchmark.py`'s docstring).
"""

from pathlib import Path

import pytest

from vision_evaluation.benchmark_runner import (
    run_depth_benchmark,
    run_tracking_benchmark,
)
from vision_evaluation.depth_metrics import align_scale, compute_depth_metrics
from vision_evaluation.models import (
    MetricValue,
    RunMetadata,
    generate_run_id,
    to_jsonable,
)
from vision_evaluation.result_store import (
    PerceptionResultStore,
    PerceptionResultStoreError,
)
from vision_evaluation.run_benchmark import run
from vision_evaluation.synthetic_data import (
    make_synthetic_depth_case,
    make_synthetic_tracking_sequence,
)
from vision_evaluation.tracking_metrics import compute_tracking_metrics

# ---------------------------------------------------------------------------
# depth_metrics
# ---------------------------------------------------------------------------


def test_compute_depth_metrics_perfect_prediction():
    predicted = [1.0, 2.0, 3.0]
    ground_truth = [1.0, 2.0, 3.0]

    metrics = compute_depth_metrics(predicted, ground_truth)

    assert metrics["mae"].value == pytest.approx(0.0)
    assert metrics["rmse"].value == pytest.approx(0.0)
    assert metrics["relative_absolute_error"].value == pytest.approx(0.0)
    assert metrics["threshold_accuracy"].value == pytest.approx(1.0)


def test_compute_depth_metrics_known_error():
    predicted = [2.0, 4.0]
    ground_truth = [1.0, 2.0]

    metrics = compute_depth_metrics(predicted, ground_truth)

    # errors: |2-1|=1, |4-2|=2 -> mae = 1.5
    assert metrics["mae"].value == pytest.approx(1.5)
    # rmse = sqrt((1^2 + 2^2)/2) = sqrt(2.5)
    assert metrics["rmse"].value == pytest.approx(2.5**0.5)


def test_compute_depth_metrics_empty_input_is_not_applicable():
    metrics = compute_depth_metrics([], [])

    assert metrics["mae"].value is None
    assert metrics["rmse"].value is None
    assert metrics["relative_absolute_error"].value is None
    assert metrics["threshold_accuracy"].value is None


def test_compute_depth_metrics_rejects_mismatched_lengths():
    with pytest.raises(AssertionError):
        compute_depth_metrics([1.0], [1.0, 2.0])


def test_align_scale_recovers_known_scale_factor():
    ground_truth = [2.0, 4.0, 6.0]
    predicted = [1.0, 2.0, 3.0]  # exactly half of ground truth

    aligned = align_scale(predicted, ground_truth)

    assert aligned == pytest.approx([2.0, 4.0, 6.0])


def test_align_scale_no_valid_pairs_returns_unchanged():
    aligned = align_scale([-1.0, 0.0], [-1.0, 0.0])
    assert aligned == (-1.0, 0.0)


# ---------------------------------------------------------------------------
# tracking_metrics
# ---------------------------------------------------------------------------


def test_tracking_metrics_perfect_tracking():
    frames = [{1: 100}, {1: 100}, {1: 100}]

    metrics = compute_tracking_metrics(frames)

    assert metrics["id_switches"].numerator == 0
    assert metrics["track_fragmentation"].numerator == 0
    assert metrics["tracking_success_rate"].value == pytest.approx(1.0)
    assert metrics["recall"].value == pytest.approx(1.0)


def test_tracking_metrics_id_switch_detected():
    frames = [{1: 100}, {1: 200}]  # same gt object, different predicted id

    metrics = compute_tracking_metrics(frames)

    assert metrics["id_switches"].numerator == 1
    assert metrics["tracking_success_rate"].value == pytest.approx(0.0)


def test_tracking_metrics_missed_detection_lowers_recall():
    frames = [{1: 100}, {1: None}, {1: 100}]

    metrics = compute_tracking_metrics(frames)

    assert metrics["recall"].value == pytest.approx(2 / 3)
    assert metrics["track_fragmentation"].numerator == 2  # in/out of None


def test_tracking_metrics_empty_input_is_not_applicable():
    metrics = compute_tracking_metrics([])

    assert metrics["tracking_success_rate"].value is None
    assert metrics["recall"].value is None


# ---------------------------------------------------------------------------
# synthetic_data
# ---------------------------------------------------------------------------


def test_synthetic_depth_case_is_deterministic():
    case_a = make_synthetic_depth_case(seed=42)
    case_b = make_synthetic_depth_case(seed=42)

    assert (case_a.ground_truth_depth == case_b.ground_truth_depth).all()
    assert (case_a.predicted_depth == case_b.predicted_depth).all()


def test_synthetic_depth_case_has_requested_object_count():
    case = make_synthetic_depth_case(seed=0, num_objects=3)
    assert len(case.detections) <= 3
    assert len(case.detections) > 0


def test_synthetic_tracking_sequence_is_deterministic():
    seq_a = make_synthetic_tracking_sequence(seed=7, num_frames=5)
    seq_b = make_synthetic_tracking_sequence(seed=7, num_frames=5)

    assert len(seq_a) == len(seq_b) == 5
    for frame_a, frame_b in zip(seq_a, seq_b):
        assert [d.bbox for d in frame_a] == [d.bbox for d in frame_b]


def test_synthetic_tracking_sequence_carries_ground_truth_id():
    frames = make_synthetic_tracking_sequence(seed=1, num_frames=3, num_objects=2)

    for frame in frames:
        for detection in frame:
            assert "ground_truth_id" in detection.attributes
            assert detection.tracking_id is None  # not yet tracked


# ---------------------------------------------------------------------------
# benchmark_runner (exercises real BaseDepthEstimator / IoUTracker code)
# ---------------------------------------------------------------------------


def test_run_depth_benchmark_produces_low_error_for_low_noise():
    case = make_synthetic_depth_case(seed=0, noise_std_m=0.01)

    result = run_depth_benchmark(case=case)

    assert result.pixel_metrics["mae"].value < 0.1
    assert result.num_object_samples > 0


def test_run_tracking_benchmark_produces_metrics():
    result = run_tracking_benchmark(seed=0)

    assert result.num_frames > 0
    assert "tracking_success_rate" in result.metrics
    assert result.metrics["tracking_success_rate"].value is not None


# ---------------------------------------------------------------------------
# result_store / run_benchmark end-to-end
# ---------------------------------------------------------------------------


def test_result_store_writes_expected_files(tmp_path: Path):
    store = PerceptionResultStore(base_dir=tmp_path)
    run_metadata = RunMetadata(
        run_id=generate_run_id("test"),
        timestamp="2026-01-01T00:00:00+00:00",
        evaluation_version="0.1.0",
        dataset_version="synthetic-v1",
        depth_source="synthetic",
        camera_intrinsics={},
        tracker_config={},
        num_depth_samples=10,
        num_tracking_frames=5,
    )
    metric = MetricValue(
        name="mae",
        definition="d",
        units="meters",
        numerator=1.0,
        denominator=2.0,
        interpretation="i",
    )

    run_dir = store.save(run_metadata, {"mae": metric}, {"recall": metric})

    assert (run_dir / "metadata.json").exists()
    assert (run_dir / "depth_metrics.json").exists()
    assert (run_dir / "tracking_metrics.json").exists()
    assert (run_dir / "summary.json").exists()


def test_result_store_refuses_to_overwrite(tmp_path: Path):
    store = PerceptionResultStore(base_dir=tmp_path)
    run_metadata = RunMetadata(
        run_id="fixed_id",
        timestamp="2026-01-01T00:00:00+00:00",
        evaluation_version="0.1.0",
        dataset_version="synthetic-v1",
        depth_source="synthetic",
        camera_intrinsics={},
        tracker_config={},
        num_depth_samples=1,
        num_tracking_frames=1,
    )

    store.save(run_metadata, {}, {})

    with pytest.raises(PerceptionResultStoreError):
        store.save(run_metadata, {}, {})


def test_to_jsonable_handles_metric_value():
    metric = MetricValue(
        name="mae",
        definition="d",
        units="meters",
        numerator=1.0,
        denominator=2.0,
        interpretation="i",
    )
    result = to_jsonable(metric)
    assert result["value"] == 0.5


def test_run_benchmark_end_to_end_writes_results(tmp_path: Path):
    run_dir = run(seed=0, results_dir=tmp_path)

    assert run_dir.exists()
    assert (run_dir / "summary.json").exists()
