"""Calibration and classification metrics shared by every learned model."""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def reliability_curve(
    y: np.ndarray, p: np.ndarray, bins: int = 10
) -> List[Dict[str, float]]:
    """Per-bin (mean predicted, observed rate, count) -- the reliability diagram."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & ((p < hi) if hi < 1.0 else (p <= hi))
        if mask.any():
            out.append(
                {
                    "mean_pred": float(p[mask].mean()),
                    "observed": float(y[mask].mean()),
                    "count": int(mask.sum()),
                }
            )
    return out


def ece(y: np.ndarray, p: np.ndarray, bins: int = 15) -> float:
    """Expected calibration error: count-weighted |observed - predicted| over bins."""
    curve = reliability_curve(y, p, bins)
    total = sum(b["count"] for b in curve)
    return float(
        sum(b["count"] * abs(b["observed"] - b["mean_pred"]) for b in curve)
        / max(total, 1)
    )


def binary_report(y: np.ndarray, p: np.ndarray) -> Dict[str, Any]:
    y = np.asarray(y).astype(int)
    p = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
    has_both = len(set(y.tolist())) == 2
    return {
        "n": int(len(y)),
        "positive_rate": float(y.mean()) if len(y) else 0.0,
        "auroc": float(roc_auc_score(y, p)) if has_both else None,
        "pr_auc": float(average_precision_score(y, p)) if has_both else None,
        "brier": float(brier_score_loss(y, p)) if len(y) else None,
        "ece": ece(y, p),
        "reliability": reliability_curve(y, p),
    }
