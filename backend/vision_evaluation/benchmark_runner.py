"""
benchmark_runner.py

Purpose
-------
Runs the real depth-extraction and tracking code (not a re-implementation
of it) against the synthetic cases in `synthetic_data.py`, and returns
the metric reports `metrics.py` module functions compute from the
result. This is the "raw case running" stage -- it does not decide what
counts as a good score, only produces the paired predicted/ground-truth
values and per-frame correspondences that `depth_metrics.py`/
`tracking_metrics.py` score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from scene.scene import Scene
from vision.depth.base_depth_estimator import BaseDepthEstimator
from vision.depth.depth_config import DepthConfig
from vision.tracking.iou_tracker import IoUTracker
from vision.tracking.tracker_config import TrackerConfig
from vision_evaluation.depth_metrics import compute_depth_metrics
from vision_evaluation.models import MetricValue
from vision_evaluation.synthetic_data import (
    SyntheticDepthCase,
    make_synthetic_depth_case,
    make_synthetic_tracking_sequence,
)
from vision_evaluation.tracking_metrics import compute_tracking_metrics


class _StaticDepthEstimator(BaseDepthEstimator):
    """Throwaway `BaseDepthEstimator` returning a fixed depth map --
    used to run the *real*, shared `_extract_object_depth` logic (median
    over mask/bbox pixels, valid-pixel-ratio gating) against synthetic
    ground-truth and predicted maps, so this benchmark measures the
    actual project code, not a reimplementation of it. Mirrors
    `backend/tests/test_vision_depth.py`'s `_FakeDepthEstimator`."""

    def __init__(self, depth_map, config: Optional[DepthConfig] = None):
        super().__init__(config=config)
        self._depth_map = depth_map

    @property
    def source_name(self) -> str:
        return "synthetic"

    def _get_depth_map(self, image, scene):
        return self._depth_map


@dataclass(frozen=True)
class DepthBenchmarkResult:
    """Output of `run_depth_benchmark`."""

    pixel_metrics: Dict[str, MetricValue]
    object_metrics: Dict[str, MetricValue]
    num_pixel_samples: int
    num_object_samples: int


def run_depth_benchmark(
    case: Optional[SyntheticDepthCase] = None, seed: int = 0
) -> DepthBenchmarkResult:
    """Runs both per-pixel and object-level depth metrics against a
    synthetic depth case.

    Per-pixel metrics compare `case.predicted_depth`/
    `case.ground_truth_depth` directly (flattened). Object-level metrics
    run the real `BaseDepthEstimator._extract_object_depth` (via
    `_StaticDepthEstimator`) over `case.detections`' bboxes against each
    map, so the benchmark exercises the same robust-median-extraction
    code path production `Detection.depth` uses.

    Args:
        case: A `SyntheticDepthCase`, or `None` to generate one with
            `make_synthetic_depth_case(seed=seed)`.
        seed: Used only when `case is None`.

    Returns:
        A `DepthBenchmarkResult`.
    """

    if case is None:
        case = make_synthetic_depth_case(seed=seed)

    pixel_predicted = case.predicted_depth.flatten().tolist()
    pixel_ground_truth = case.ground_truth_depth.flatten().tolist()
    pixel_metrics = compute_depth_metrics(pixel_predicted, pixel_ground_truth)

    gt_estimator = _StaticDepthEstimator(case.ground_truth_depth)
    predicted_estimator = _StaticDepthEstimator(case.predicted_depth)

    object_predicted: List[float] = []
    object_ground_truth: List[float] = []

    for detection in case.detections:
        gt_depth, _ = gt_estimator._extract_object_depth(
            case.ground_truth_depth, detection
        )
        pred_depth, _ = predicted_estimator._extract_object_depth(
            case.predicted_depth, detection
        )
        if gt_depth is not None and pred_depth is not None:
            object_ground_truth.append(gt_depth)
            object_predicted.append(pred_depth)

    object_metrics = compute_depth_metrics(object_predicted, object_ground_truth)

    return DepthBenchmarkResult(
        pixel_metrics=pixel_metrics,
        object_metrics=object_metrics,
        num_pixel_samples=len(pixel_predicted),
        num_object_samples=len(object_predicted),
    )


@dataclass(frozen=True)
class TrackingBenchmarkResult:
    """Output of `run_tracking_benchmark`."""

    metrics: Dict[str, MetricValue]
    num_frames: int
    tracker_config: TrackerConfig


def run_tracking_benchmark(
    seed: int = 0,
    tracker_config: Optional[TrackerConfig] = None,
    frames: Optional[List] = None,
) -> TrackingBenchmarkResult:
    """Runs the real `IoUTracker` against a synthetic detection sequence
    and computes tracking metrics from the result.

    Args:
        seed: Used only when `frames is None`, via
            `make_synthetic_tracking_sequence(seed=seed)`.
        tracker_config: Explicit `TrackerConfig` for reproducibility --
            defaults to a fixed config (not `TrackerConfig.from_env()`,
            since a benchmark run must not silently depend on whatever
            environment variables happen to be set in the process it
            runs in).
        frames: A pre-built synthetic sequence (list of lists of
            `Detection`, see `synthetic_data.py`), or `None` to generate
            one.

    Returns:
        A `TrackingBenchmarkResult`.
    """

    if frames is None:
        frames = make_synthetic_tracking_sequence(seed=seed)

    config = tracker_config or TrackerConfig(
        iou_threshold=0.3,
        max_missed_frames=3,
        use_3d_distance=False,
        max_3d_distance_m=0.5,
    )

    tracker = IoUTracker(config=config)

    correspondences: List[Dict[int, Optional[int]]] = []

    for frame_detections in frames:
        scene = Scene(detections=list(frame_detections))
        tracker.process(None, scene)

        frame_correspondence = {
            detection.attributes["ground_truth_id"]: detection.tracking_id
            for detection in scene.detections
        }
        correspondences.append(frame_correspondence)

    metrics = compute_tracking_metrics(correspondences)

    return TrackingBenchmarkResult(
        metrics=metrics, num_frames=len(frames), tracker_config=config
    )
