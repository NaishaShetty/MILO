"""
test_evaluation_dataset_loader.py

Purpose
-------
Verifies `evaluation.dataset_loader` against this repository's real
`datasets/language/evaluation/*.json` files (no fixtures needed -- the
whole point of this module is to load exactly those files correctly),
plus `DatasetLoadError` behavior against deliberately malformed
temporary files. No network access, no LLM involved.
"""

from __future__ import annotations

import json

import pytest

from evaluation.dataset_loader import (
    DEFAULT_DATASET_DIR,
    load_all_datasets,
    load_dataset,
)
from evaluation.exceptions import DatasetLoadError
from evaluation.models import DatasetCategory


class TestRealDatasetLoading:
    def test_success_cases_load_with_expected_count_and_order(self) -> None:
        cases, provenance = load_dataset(DatasetCategory.SUCCESS)
        assert len(cases) == 15
        assert [case.case_id for case in cases][:3] == [
            "success-001",
            "success-002",
            "success-003",
        ]
        assert provenance.schema_version == "1.0.0"
        assert provenance.prompt_version == "1.1.0"
        assert provenance.case_count == 15
        # Case IDs are preserved verbatim -- never re-numbered.
        assert cases[0].expected_output is not None
        assert cases[0].expected_output["goal"] == "turn_off"

    def test_failure_cases_load_with_expected_count(self) -> None:
        cases, provenance = load_dataset(DatasetCategory.FAILURE)
        assert len(cases) == 12
        assert provenance.case_count == 12
        first = cases[0]
        assert first.case_id == "failure-001"
        assert first.expected_validation_result == "reject_syntactic"
        assert isinstance(first.candidate_output, str)
        # failure-003 carries a dict candidate_output, not a string.
        dict_case = next(c for c in cases if c.case_id == "failure-003")
        assert isinstance(dict_case.candidate_output, dict)

    def test_ambiguity_cases_load_with_expected_count(self) -> None:
        cases, provenance = load_dataset(DatasetCategory.AMBIGUITY)
        assert len(cases) == 10
        assert provenance.case_count == 10
        first = cases[0]
        assert first.case_id == "ambig-001"
        assert first.expected_needs_clarification is True
        assert "referent" in first.reason_keywords
        negative_case = next(c for c in cases if c.case_id == "ambig-002")
        assert negative_case.expected_needs_clarification is False

    def test_load_all_datasets_returns_all_three_categories(self) -> None:
        loaded = load_all_datasets()
        assert set(loaded.keys()) == set(DatasetCategory)
        assert len(loaded[DatasetCategory.SUCCESS][0]) == 15
        assert len(loaded[DatasetCategory.FAILURE][0]) == 12
        assert len(loaded[DatasetCategory.AMBIGUITY][0]) == 10

    def test_default_dataset_dir_points_at_real_repository_location(self) -> None:
        assert (DEFAULT_DATASET_DIR / "success_cases.json").is_file()


class TestMalformedDatasetHandling:
    def test_missing_file_raises_dataset_load_error(self, tmp_path) -> None:
        with pytest.raises(DatasetLoadError):
            load_dataset(DatasetCategory.SUCCESS, base_dir=tmp_path)

    def test_invalid_json_raises_dataset_load_error(self, tmp_path) -> None:
        (tmp_path / "success_cases.json").write_text(
            "{not valid json", encoding="utf-8"
        )
        with pytest.raises(DatasetLoadError):
            load_dataset(DatasetCategory.SUCCESS, base_dir=tmp_path)

    def test_missing_top_level_array_raises_dataset_load_error(self, tmp_path) -> None:
        (tmp_path / "success_cases.json").write_text(
            json.dumps({"$schema_version": "1.0.0"}), encoding="utf-8"
        )
        with pytest.raises(DatasetLoadError):
            load_dataset(DatasetCategory.SUCCESS, base_dir=tmp_path)

    def test_case_missing_required_field_raises_dataset_load_error(
        self, tmp_path
    ) -> None:
        payload = {
            "$schema_version": "1.0.0",
            "$prompt_version": "1.1.0",
            "success_cases": [
                {"id": "success-001", "category": "simple", "input": "test"}
            ],
        }
        (tmp_path / "success_cases.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        with pytest.raises(DatasetLoadError):
            load_dataset(DatasetCategory.SUCCESS, base_dir=tmp_path)
