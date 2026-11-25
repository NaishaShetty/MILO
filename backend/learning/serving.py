"""
serving.py (backend/learning)

Serving side of the step outcome predictor, built so it can never hurt MILO:

- **Missing/broken model file** -> `load_predictor()` returns `None`; callers
  fall back to the rule-based behaviour.
- **Latency**: every call is timed; a call over `budget_ms` counts as slow and
  after `max_slow` slow calls in a row the predictor disables itself
  (`.disabled_reason`). Inference is a handful of tree predictions (~ms).
- **Drift**: each context's features are compared with the training
  distribution (mean |z|); a rolling average above `drift_threshold` marks the
  predictor `drifted`, and callers must not trust it then.
- **Uncertainty**: `confident` is False when the success probability sits in
  the grey zone around 0.5.

`Prediction.top_factors` is a cheap local explanation: how much P(success)
changes when a feature group is replaced with a typical value.
"""

from __future__ import annotations

import json
import logging
import pickle
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Mapping, Optional

import numpy as np

from learning.predictor_features import FEATURE_NAMES, FRIENDLY, featurize

logger = logging.getLogger(__name__)

# Feature groups used for the explanation (name -> feature names to neutralise).
_GROUPS = {
    "reachable": ["reachable"],
    "visible": ["visible"],
    "distance": ["distance"],
    "target_found": ["target_found"],
    "retries_so_far": ["retries_so_far", "replans_so_far"],
    "memory_prior_success": [
        "memory_hits",
        "memory_sim_max",
        "memory_sim_mean",
        "memory_prior_success",
    ],
    "is_open": ["is_open"],
}


@dataclass
class Prediction:
    p_success: float
    p_retry_success: float
    duration_ms: float
    failure_probs: Dict[str, float]
    latency_ms: float
    version: str
    confident: bool = True
    top_factors: List[str] = field(default_factory=list)

    @property
    def failure_type(self) -> str:
        return (
            max(self.failure_probs, key=lambda k: self.failure_probs[k])
            if self.failure_probs
            else "other"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "p_success": round(self.p_success, 4),
            "p_retry_success": round(self.p_retry_success, 4),
            "duration_ms": round(self.duration_ms, 1),
            "failure_type": self.failure_type,
            "latency_ms": round(self.latency_ms, 3),
            "version": self.version,
            "confident": self.confident,
            "top_factors": self.top_factors,
        }


class OutcomePredictor:
    def __init__(
        self,
        artifact: Mapping[str, Any],
        *,
        budget_ms: float = 20.0,
        max_slow: int = 3,
        drift_threshold: float = 2.5,
        grey_zone: float = 0.1,
    ) -> None:
        self._a = artifact
        self.version: str = artifact["version"]
        self.thresholds: Dict[str, float] = dict(artifact["thresholds"])
        self._mean = artifact["train_mean"]
        self._std = artifact["train_std"]
        self._budget_ms = budget_ms
        self._max_slow = max_slow
        self._slow_streak = 0
        self._drift: Deque[float] = deque(maxlen=50)
        self._drift_threshold = drift_threshold
        self._grey = grey_zone
        self.disabled_reason: Optional[str] = None
        self.calls = 0
        self.latencies_ms: Deque[float] = deque(maxlen=500)
        self._warm_up()

    def _warm_up(self) -> None:
        """One throwaway prediction so the first live call isn't slow (not counted)."""
        try:
            self.predict({"action": "locate"}, explain=True)
        finally:
            self.calls, self._slow_streak = 0, 0
            self.latencies_ms.clear()
            self._drift.clear()
            self.disabled_reason = None

    # -- state ---------------------------------------------------------------
    @property
    def drift_score(self) -> float:
        return float(np.mean(self._drift)) if self._drift else 0.0

    @property
    def drifted(self) -> bool:
        return len(self._drift) >= 10 and self.drift_score > self._drift_threshold

    @property
    def usable(self) -> bool:
        return self.disabled_reason is None and not self.drifted

    # -- inference -------------------------------------------------------------
    def _p_success(self, x: np.ndarray) -> float:
        raw = self._a["success_clf"].predict_proba(x)[:, 1]
        return float(self._a["success_iso"].predict(raw)[0])

    def predict(self, ctx: Mapping[str, Any], explain: bool = False) -> Prediction:
        started = time.perf_counter()
        x = np.array([featurize(ctx)], dtype=np.float64)
        p = self._p_success(x)
        p_retry = float(
            self._a["retry_iso"].predict(self._a["retry_clf"].predict_proba(x)[:, 1])[0]
        )
        duration = float(self._a["duration_reg"].predict(x)[0])
        probs = self._a["type_clf"].predict_proba(x)[0]
        classes = self._a["type_clf"].classes_
        failure = {
            self._a["fail_types"][int(c)]: float(pr) for c, pr in zip(classes, probs)
        }
        z = float(np.mean(np.abs((x[0] - self._mean) / self._std)))
        self._drift.append(min(z, 20.0))
        pred = Prediction(
            p_success=p,
            p_retry_success=p_retry,
            duration_ms=max(duration, 0.0),
            failure_probs=failure,
            latency_ms=0.0,
            version=self.version,
            confident=abs(p - 0.5) > self._grey,
        )
        if explain:
            pred.top_factors = self._explain(ctx, x, p)
        pred.latency_ms = (time.perf_counter() - started) * 1000.0
        self._record_latency(pred.latency_ms)
        return pred

    def _record_latency(self, ms: float) -> None:
        self.calls += 1
        self.latencies_ms.append(ms)
        self._slow_streak = self._slow_streak + 1 if ms > self._budget_ms else 0
        if self._slow_streak >= self._max_slow and self.disabled_reason is None:
            self.disabled_reason = (
                f"too slow ({ms:.0f} ms > {self._budget_ms:.0f} ms budget)"
            )
            logger.warning(
                "outcome_predictor.disabled", extra={"reason": self.disabled_reason}
            )

    def _explain(self, ctx: Mapping[str, Any], x: np.ndarray, p: float) -> List[str]:
        """Top-2 factors: one batched tree call over `x` with each feature group
        replaced by its training mean (so explaining costs one extra predict)."""
        index = {n: i for i, n in enumerate(FEATURE_NAMES)}
        obj = str(ctx.get("object_class", "thing"))
        labels = list(_GROUPS)
        variants = np.repeat(x, len(labels), axis=0)
        for row, label in enumerate(labels):
            for n in _GROUPS[label]:
                variants[row, index[n]] = self._mean[index[n]]
        neutral = self._a["success_iso"].predict(
            self._a["success_clf"].predict_proba(variants)[:, 1]
        )
        effects = sorted(
            ((abs(p - q), label, p - q) for label, q in zip(labels, neutral)),
            reverse=True,
        )
        out = []
        for size, label, delta in effects[:2]:
            if size < 0.02:
                continue
            what = FRIENDLY.get(label, label).format(obj=obj)
            out.append(f"{what} ({'helps' if delta > 0 else 'hurts'})")
        return out

    def latency_summary(self) -> Dict[str, float]:
        if not self.latencies_ms:
            return {"p50_ms": 0.0, "p95_ms": 0.0}
        arr = np.array(self.latencies_ms)
        return {
            "p50_ms": float(np.percentile(arr, 50)),
            "p95_ms": float(np.percentile(arr, 95)),
        }


def load_predictor(path: Optional[Path], **kwargs: Any) -> Optional[OutcomePredictor]:
    """The predictor at `path` (a `model.pkl`, or a directory containing the
    newest version), or `None` if there is no usable model -- never raises."""
    try:
        if path is None:
            return None
        path = Path(path)
        if path.is_dir():
            pointer = path / "current.json"  # written by `learning.promote`
            if pointer.exists():
                chosen = path / json.loads(pointer.read_text())["version"] / "model.pkl"
                if chosen.exists():
                    path = chosen
            if path.is_dir():
                versions = sorted(
                    p for p in path.iterdir() if (p / "model.pkl").exists()
                )
                if not versions:
                    return None
                path = versions[-1] / "model.pkl"
        with open(path, "rb") as handle:
            return OutcomePredictor(pickle.load(handle), **kwargs)
    except Exception:
        logger.warning("outcome_predictor.load_failed", exc_info=True)
        return None
