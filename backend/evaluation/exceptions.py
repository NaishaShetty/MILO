"""
exceptions.py

Purpose
-------
Closed exception vocabulary for the Phase 3.6 evaluation framework,
mirroring `backend/language/exceptions.py`'s rationale: every module in
`backend/evaluation/` raises one of these instead of letting a bare
`KeyError`/`OSError`/`json.JSONDecodeError` leak out, so a caller (a
test, `run_benchmark.py`, or a future Phase 3.7 API layer surfacing
benchmark results) has one hierarchy to catch.

These are evaluation-framework failures, never runtime-under-test
failures -- a `LanguageRuntimeError` raised by `LanguageAgent` during a
benchmark run is expected, captured data (see
`models.RawBenchmarkRecord`), not something this module wraps.
"""

from __future__ import annotations


class EvaluationError(Exception):
    """Base class for every exception raised anywhere in `backend/evaluation/`."""


class DatasetLoadError(EvaluationError):
    """
    Raised by `dataset_loader.py` when a benchmark dataset file is
    missing, is not valid JSON, or is missing a field this framework
    requires (e.g. a case with no `id`). Never raised for a case that
    is merely benchmark-hard (e.g. a genuinely ambiguous instruction) --
    only for malformed *data*, which the spec explicitly forbids
    silently working around ("do not silently modify the benchmark
    cases to make results better").
    """


class BenchmarkConfigurationError(EvaluationError):
    """
    Raised when a benchmark run is misconfigured -- most importantly by
    `run_benchmark.py` when real-provider execution is requested
    without `RUN_LLM_BENCHMARK=true` explicitly set (spec's "Real
    evaluation must be explicitly enabled" / "Cost and Safety"
    requirement), or when an unsupported provider/dataset name is
    given.
    """


class ResultStoreError(EvaluationError):
    """
    Raised by `result_store.py` when a benchmark run's results cannot
    be persisted -- most importantly when a `run_id` directory already
    exists (this framework never overwrites a previous run, per the
    spec's "each run must have a unique identifier" requirement).
    """
