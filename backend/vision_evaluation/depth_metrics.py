"""
depth_metrics.py

Purpose
-------
Depth accuracy metrics: MAE, RMSE, relative absolute error, and
threshold accuracy, computed over paired `(predicted, ground_truth)`
depth values -- works identically for per-pixel arrays or object-level
scalars, since the underlying formulas don't care which. Also provides
`align_scale`, the median-ratio scale alignment required before
comparing a relative-depth prediction (Depth Anything) against metric
ground truth (AI2-THOR) -- see `vision/depth/depth_anything_estimator
.py`'s docstring for why raw, unaligned comparison would be meaningless.

Metric definitions (every metric documented per the project's
"Name/Definition/Formula/Units/Interpretation/Edge-case handling"
requirement)
--------------------------------------------------------------------------
- MAE (Mean Absolute Error): `mean(|predicted - ground_truth|)`. Units:
  meters (only meaningful for metric, i.e. `"ground_truth"`-sourced or
  scale-aligned, depth). Interpretation: average absolute deviation;
  lower is better; sensitive to outliers less than RMSE.
- RMSE (Root Mean Squared Error): `sqrt(mean((predicted -
  ground_truth)^2))`. Units: meters. Interpretation: like MAE but
  penalizes large individual errors more heavily -- a large RMSE
  relative to MAE indicates a few big misses rather than uniform noise.
- Relative Absolute Error: `mean(|predicted - ground_truth| /
  ground_truth)`. Unitless (a fraction). Interpretation: error
  normalized by distance -- makes a 0.1m error at 1m (10%) and a 0.1m
  error at 10m (1%) comparable, which raw MAE cannot.
- Threshold accuracy (`delta < threshold`): fraction of samples where
  `max(predicted/ground_truth, ground_truth/predicted) < threshold`
  (the standard monocular-depth-estimation "δ accuracy" metric).
  Unitless (a fraction). Interpretation: robust to a few very wrong
  outliers dominating an average-based metric like MAE/RMSE; the
  default `threshold=1.25` (`δ1`) is the standard value used across the
  monocular depth estimation literature (e.g. Eigen et al. 2014),
  chosen for exactly that comparability, not derived from this
  project's data.

Edge cases
----------
- Empty input -> every metric's denominator is `0`, so `MetricValue
  .value` is `None` ("not applicable"), never `0.0` or a divide error.
- `ground_truth` values `<= 0` are excluded from Relative Absolute
  Error and threshold accuracy (division by a non-positive distance is
  undefined) -- MAE/RMSE still include them, since those don't divide
  by `ground_truth`.
"""

from __future__ import annotations

import math
from typing import Dict, Sequence, Tuple

from vision_evaluation.models import MetricValue


def align_scale(
    predicted: Sequence[float], ground_truth: Sequence[float]
) -> Tuple[float, ...]:
    """Median-ratio scale alignment for relative depth predictions.

    Depth Anything's output has no fixed physical scale (see
    `depth_anything_estimator.py`); before any error metric that treats
    values as meters can be computed, `predicted` must be rescaled by
    a single global factor. The median ratio (rather than the mean) is
    used because it is robust to a handful of grossly mismatched pairs
    dominating a mean-based scale factor.

    Args:
        predicted: Relative depth values.
        ground_truth: Corresponding metric depth values (meters).

    Returns:
        `predicted`, rescaled by `median(ground_truth[i] /
        predicted[i])` for all pairs where both values are positive and
        finite. Returns `predicted` unchanged if no such pair exists
        (nothing to align against).
    """

    ratios = [
        gt / pred
        for pred, gt in zip(predicted, ground_truth)
        if math.isfinite(pred) and math.isfinite(gt) and pred > 0 and gt > 0
    ]

    if not ratios:
        return tuple(predicted)

    ratios.sort()
    mid = len(ratios) // 2
    median_ratio = (
        ratios[mid] if len(ratios) % 2 == 1 else (ratios[mid - 1] + ratios[mid]) / 2.0
    )

    return tuple(p * median_ratio for p in predicted)


def _metric(
    name: str,
    definition: str,
    units: str,
    numerator: float,
    denominator: float,
    interpretation: str,
) -> MetricValue:
    return MetricValue(
        name=name,
        definition=definition,
        units=units,
        numerator=float(numerator),
        denominator=float(denominator),
        interpretation=interpretation,
    )


def compute_depth_metrics(
    predicted: Sequence[float],
    ground_truth: Sequence[float],
    threshold: float = 1.25,
) -> Dict[str, MetricValue]:
    """Computes MAE, RMSE, relative absolute error, and threshold
    accuracy over paired `(predicted, ground_truth)` depth values.

    Args:
        predicted: Predicted depth values (must already be in the same
            units/scale as `ground_truth` -- run `align_scale` first
            for a relative-depth source).
        ground_truth: Ground-truth depth values, same length as
            `predicted`.
        threshold: `delta` threshold for threshold accuracy (default
            `1.25`, the standard `delta1` literature value).

    Returns:
        `{"mae", "rmse", "relative_absolute_error",
        "threshold_accuracy_delta1"}` mapped to `MetricValue`s. See
        module docstring for definitions and edge-case handling.
    """

    assert len(predicted) == len(ground_truth), (
        "predicted and ground_truth must be the same length -- "
        f"got {len(predicted)} and {len(ground_truth)}."
    )

    n = len(predicted)

    abs_errors = [abs(p - g) for p, g in zip(predicted, ground_truth)]
    rmse = math.sqrt(sum(e * e for e in abs_errors) / n) if n else 0.0

    positive_pairs = [
        (p, g) for p, g in zip(predicted, ground_truth) if g > 0 and p > 0
    ]

    rel_errors = [abs(p - g) / g for p, g in positive_pairs]
    rel_abs_error_sum = sum(rel_errors)

    within_threshold = sum(
        1 for p, g in positive_pairs if max(p / g, g / p) < threshold
    )

    return {
        "mae": _metric(
            "mae",
            "Mean absolute error between predicted and ground-truth depth.",
            "meters",
            sum(abs_errors),
            n,
            "Lower is better; average absolute deviation across all samples.",
        ),
        "rmse": _metric(
            "rmse",
            "Root mean squared error between predicted and ground-truth depth.",
            "meters",
            # RMSE involves a sqrt, so unlike every other metric here it is
            # not itself a sum/count ratio -- represented as
            # numerator=rmse, denominator=1 (0 when n=0) so
            # `MetricValue.value` still returns the correct number, while
            # denominator=0 still correctly signals "not applicable" for
            # an empty input.
            rmse,
            1 if n else 0,
            "Lower is better; penalizes large individual errors more than MAE.",
        ),
        "relative_absolute_error": _metric(
            "relative_absolute_error",
            "Mean of |predicted - ground_truth| / ground_truth, over samples "
            "with positive ground-truth depth.",
            "unitless (fraction)",
            rel_abs_error_sum,
            len(positive_pairs),
            "Lower is better; normalizes error by distance so near/far errors "
            "are comparable.",
        ),
        "threshold_accuracy": _metric(
            f"threshold_accuracy_delta_{threshold}",
            f"Fraction of samples where max(pred/gt, gt/pred) < {threshold}.",
            "unitless (fraction)",
            within_threshold,
            len(positive_pairs),
            "Higher is better; robust to a few outliers dominating MAE/RMSE.",
        ),
    }
