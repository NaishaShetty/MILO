"""
dataset_loader.py

Purpose
-------
The single place that reads the Phase 3.3 benchmark datasets
(`datasets/language/evaluation/success_cases.json`, `failure_cases.json`,
`ambiguity_cases.json`) and normalizes their three distinct JSON shapes
into one common `models.BenchmarkCase` per entry. No other module in
`backend/evaluation/` parses dataset JSON directly -- this is what lets
a future fourth dataset file be added by writing one new loader
function here, without touching `benchmark_runner.py`, `evaluator.py`,
or any test that already depends on `BenchmarkCase`.

Why case IDs and ordering are preserved verbatim
--------------------------------------------------
The spec requires "the benchmark runner should preserve the original
case ID so results can always be traced back to the exact benchmark
case" and forbids "silently modify the benchmark cases". This module
therefore never re-sorts, re-numbers, deduplicates, or drops a case --
if a file is malformed, it raises `DatasetLoadError` rather than
skipping the offending entry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from evaluation.exceptions import DatasetLoadError
from evaluation.models import BenchmarkCase, DatasetCategory, DatasetProvenance

#: `backend/evaluation/dataset_loader.py` -> parent is `backend/
#: evaluation/`, parent's parent is `backend/`, parent's parent's
#: parent is the repository root -- mirrors the same
#: `.resolve().parents` pattern `backend/language/config.py` uses so
#: dataset paths are correct regardless of the process's working
#: directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATASET_DIR = _REPO_ROOT / "datasets" / "language" / "evaluation"

_FILENAMES: Dict[DatasetCategory, str] = {
    DatasetCategory.SUCCESS: "success_cases.json",
    DatasetCategory.FAILURE: "failure_cases.json",
    DatasetCategory.AMBIGUITY: "ambiguity_cases.json",
}


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise DatasetLoadError(f"Benchmark dataset file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise DatasetLoadError(
            f"Benchmark dataset file is not valid JSON: {path}"
        ) from exc


def _require(entry: Dict[str, Any], key: str, case_index: int, path: Path) -> Any:
    if key not in entry:
        raise DatasetLoadError(
            f"{path}: case at index {case_index} is missing required field {key!r}"
        )
    return entry[key]


def _require_top_level(raw: Dict[str, Any], key: str, path: Path) -> List[Any]:
    if key not in raw:
        raise DatasetLoadError(f"{path}: missing required top-level array {key!r}")
    return raw[key]


def _load_success_cases(path: Path) -> List[BenchmarkCase]:
    """
    `success_cases.json` -- every case carries `expected_output`, the
    target `SingleTask`/`MultiTask` dict, used by `evaluator.py`'s
    field-level comparison.
    """
    raw = _read_json(path)
    cases: List[BenchmarkCase] = []
    for index, entry in enumerate(_require_top_level(raw, "success_cases", path)):
        cases.append(
            BenchmarkCase(
                case_id=_require(entry, "id", index, path),
                dataset=DatasetCategory.SUCCESS,
                category=_require(entry, "category", index, path),
                instruction=_require(entry, "input", index, path),
                expected_output=_require(entry, "expected_output", index, path),
            )
        )
    return cases


def _load_failure_cases(path: Path) -> List[BenchmarkCase]:
    """
    `failure_cases.json` -- every case pairs an instruction with a
    hypothetical `candidate_output` (string or dict) and an
    `expected_validation_result`. See `benchmark_runner.py` for why
    these cases are always driven through a deterministic fixture
    `LLMClient` rather than a real model.
    """
    raw = _read_json(path)
    cases: List[BenchmarkCase] = []
    for index, entry in enumerate(_require_top_level(raw, "failure_cases", path)):
        cases.append(
            BenchmarkCase(
                case_id=_require(entry, "id", index, path),
                dataset=DatasetCategory.FAILURE,
                category=_require(entry, "category", index, path),
                instruction=_require(entry, "input", index, path),
                candidate_output=_require(entry, "candidate_output", index, path),
                expected_validation_result=_require(
                    entry, "expected_validation_result", index, path
                ),
                notes=entry.get("notes"),
            )
        )
    return cases


def _load_ambiguity_cases(path: Path) -> List[BenchmarkCase]:
    """
    `ambiguity_cases.json` -- every case carries a boolean
    `expected_needs_clarification` label (both true- and false-labeled
    cases are present, per the dataset's own true-positive/true-negative
    design).
    """
    raw = _read_json(path)
    cases: List[BenchmarkCase] = []
    for index, entry in enumerate(_require_top_level(raw, "ambiguity_cases", path)):
        cases.append(
            BenchmarkCase(
                case_id=_require(entry, "id", index, path),
                dataset=DatasetCategory.AMBIGUITY,
                category=_require(entry, "ambiguity_type", index, path),
                instruction=_require(entry, "input", index, path),
                expected_needs_clarification=_require(
                    entry, "expected_needs_clarification", index, path
                ),
                ambiguity_type=_require(entry, "ambiguity_type", index, path),
                reason_keywords=list(entry.get("reason_keywords", [])),
                notes=entry.get("notes"),
            )
        )
    return cases


_LOADERS = {
    DatasetCategory.SUCCESS: _load_success_cases,
    DatasetCategory.FAILURE: _load_failure_cases,
    DatasetCategory.AMBIGUITY: _load_ambiguity_cases,
}


def load_dataset(
    dataset: DatasetCategory, *, base_dir: Path = DEFAULT_DATASET_DIR
) -> Tuple[List[BenchmarkCase], DatasetProvenance]:
    """
    Loads one dataset file, returning its cases (in file order) plus
    the `DatasetProvenance` read from the file's own `$schema_version`/
    `$prompt_version` header -- the provenance is what lets
    `result_store.py` record exactly which dataset revision a run used.
    """
    path = base_dir / _FILENAMES[dataset]
    raw = _read_json(path)
    cases = _LOADERS[dataset](path)
    provenance = DatasetProvenance(
        dataset=dataset,
        source_path=str(path),
        schema_version=str(raw.get("$schema_version", "unknown")),
        prompt_version=str(raw.get("$prompt_version", "unknown")),
        case_count=len(cases),
    )
    return cases, provenance


def load_all_datasets(
    *, base_dir: Path = DEFAULT_DATASET_DIR
) -> Dict[DatasetCategory, Tuple[List[BenchmarkCase], DatasetProvenance]]:
    """
    Loads all three benchmark datasets. This is the entry point
    `run_benchmark.py` and most tests use; `load_dataset` remains
    available directly for tests/tools that want only one category
    (e.g. `recovery_evaluation.py`'s tests, which only need
    `failure_cases` to exercise recovery paths).
    """
    return {
        dataset: load_dataset(dataset, base_dir=base_dir) for dataset in DatasetCategory
    }
