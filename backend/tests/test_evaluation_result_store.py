"""
test_evaluation_result_store.py

Purpose
-------
Verifies `evaluation.result_store.BenchmarkResultStore` writes the
expected file set to a temporary directory, never overwrites an
existing run, and never leaks anything credential-shaped into the
written JSON. No network access, no LLM.
"""

from __future__ import annotations

import json

import pytest

from evaluation.exceptions import ResultStoreError
from evaluation.metrics import MetricsCalculator
from evaluation.models import DatasetCategory, RawBenchmarkRecord, RunMetadata, RunMode
from evaluation.recovery_evaluation import RecoveryEvaluator
from evaluation.result_store import BenchmarkResultStore

_RUN_METADATA = RunMetadata(
    run_id="test-run-000",
    timestamp="2026-08-08T00:00:00+00:00",
    benchmark_version="0.1.0",
    provider="openai",
    model="gpt-4o-mini",
    prompt_version="1.1.0",
    schema_version="1.0.0",
    dataset_versions={"success_cases": "1.0.0/1.1.0"},
    recovery_max_retries=2,
    decoding_temperature=0.2,
    decoding_top_p=1.0,
    decoding_max_tokens=1024,
    case_limit=None,
    num_cases=1,
    num_completed=1,
    num_failed=0,
    run_mode=RunMode.MOCKED,
)

_RECORD = RawBenchmarkRecord(
    case_id="success-001",
    dataset=DatasetCategory.SUCCESS,
    category="simple",
    succeeded=True,
    parsed_instruction={"task_type": "single", "goal": "turn_off"},
    provider="openai",
    model="gpt-4o-mini",
    attempt_number=1,
    recovered=False,
    total_latency_ms=42.0,
    run_mode=RunMode.MOCKED,
)


class TestResultPersistence:
    def test_save_writes_all_expected_files(self, tmp_path) -> None:
        store = BenchmarkResultStore(base_dir=tmp_path)
        metrics = MetricsCalculator().compute([], [])
        run_dir = store.save(_RUN_METADATA, [_RECORD], metrics)
        assert (run_dir / "metadata.json").is_file()
        assert (run_dir / "raw_results.json").is_file()
        assert (run_dir / "metrics.json").is_file()
        assert (run_dir / "summary.json").is_file()

    def test_recovery_report_is_written_when_provided(self, tmp_path) -> None:
        store = BenchmarkResultStore(base_dir=tmp_path)
        metrics = MetricsCalculator().compute([], [])
        recovery = RecoveryEvaluator().evaluate([], [])
        run_dir = store.save(_RUN_METADATA, [_RECORD], metrics, recovery=recovery)
        assert (run_dir / "recovery.json").is_file()

    def test_saved_files_are_valid_json(self, tmp_path) -> None:
        store = BenchmarkResultStore(base_dir=tmp_path)
        metrics = MetricsCalculator().compute([], [])
        run_dir = store.save(_RUN_METADATA, [_RECORD], metrics)
        for filename in (
            "metadata.json",
            "raw_results.json",
            "metrics.json",
            "summary.json",
        ):
            with (run_dir / filename).open("r", encoding="utf-8") as handle:
                json.load(handle)  # raises if not valid JSON

    def test_run_id_directory_is_never_overwritten(self, tmp_path) -> None:
        store = BenchmarkResultStore(base_dir=tmp_path)
        metrics = MetricsCalculator().compute([], [])
        store.save(_RUN_METADATA, [_RECORD], metrics)
        with pytest.raises(ResultStoreError):
            store.save(_RUN_METADATA, [_RECORD], metrics)

    def test_no_credential_shaped_content_appears_anywhere(self, tmp_path) -> None:
        store = BenchmarkResultStore(base_dir=tmp_path)
        metrics = MetricsCalculator().compute([], [])
        run_dir = store.save(_RUN_METADATA, [_RECORD], metrics)
        forbidden = ("api_key", "apikey", "authorization", "bearer", "secret")
        for filename in (
            "metadata.json",
            "raw_results.json",
            "metrics.json",
            "summary.json",
        ):
            content = (run_dir / filename).read_text(encoding="utf-8").lower()
            for term in forbidden:
                assert term not in content
