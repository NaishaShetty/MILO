"""
models.py (vision_evaluation)

Purpose
-------
Shared data shapes for the perception benchmark, mirroring
`backend/evaluation/models.py`'s conventions (frozen dataclasses,
`MetricValue` never a bare float, a versioned run id) but redeclared
here rather than imported -- `backend/evaluation/` is scoped to the
language benchmark by its own module docstrings; see this package's
`__init__.py` for why the two frameworks stay independent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

#: Independent version of this evaluation framework -- bump when metric
#: definitions or the result-file shape change in a way that makes two
#: runs' numbers not directly comparable. Distinct from
#: `evaluation.models.BENCHMARK_VERSION` (the language benchmark's own
#: version, a different framework entirely).
PERCEPTION_BENCHMARK_VERSION = "0.1.0"


def generate_run_id(prefix: str) -> str:
    """Same `{prefix}_{utc-timestamp}_{short-uuid}` shape as
    `evaluation.models.generate_run_id` -- duplicated rather than
    imported, per this package's independence from `backend/evaluation/`
    (see `__init__.py`)."""

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    safe_prefix = "".join(ch if ch.isalnum() else "-" for ch in prefix)
    return f"{safe_prefix}_{timestamp}_{suffix}"


@dataclass(frozen=True)
class MetricValue:
    """One named, defined metric -- never a bare float, per the
    project's "every metric must have a definition/formula/units/
    interpretation" requirement. See
    `evaluation.models.MetricValue`'s docstring for the same rationale;
    duplicated here rather than imported (see this package's
    `__init__.py`).
    """

    name: str
    definition: str
    units: str
    numerator: float
    denominator: float
    interpretation: str

    @property
    def value(self) -> Optional[float]:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator


@dataclass(frozen=True)
class RunMetadata:
    """Reproducibility record for one benchmark run (spec's "Benchmark
    Reproducibility" requirement: dataset/scenario version, model,
    config, camera parameters, thresholds, timestamp, evaluation
    version). Contains no secrets -- every field is a version string,
    count, or non-secret threshold."""

    run_id: str
    timestamp: str
    evaluation_version: str
    dataset_version: str
    depth_source: str
    camera_intrinsics: Dict[str, float]
    tracker_config: Dict[str, Any]
    num_depth_samples: int
    num_tracking_frames: int


def to_jsonable(value: Any) -> Any:
    """Recursively converts a dataclass/Enum/dict/list/primitive
    structure into something `json.dump` can serialize -- identical
    approach to `evaluation.models.to_jsonable`, duplicated for the same
    independence reason as the rest of this file."""

    if is_dataclass(value) and not isinstance(value, type):
        result: Dict[str, Any] = {}
        for attr_name in value.__dataclass_fields__:
            result[attr_name] = to_jsonable(getattr(value, attr_name))
        if isinstance(value, MetricValue):
            result["value"] = value.value
        return result
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class DepthMetricsReport:
    """`depth_metrics.compute_depth_metrics`'s sole product."""

    metrics: Dict[str, MetricValue] = field(default_factory=dict)


@dataclass(frozen=True)
class TrackingMetricsReport:
    """`tracking_metrics.compute_tracking_metrics`'s sole product."""

    metrics: Dict[str, MetricValue] = field(default_factory=dict)
