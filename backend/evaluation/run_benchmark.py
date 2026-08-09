"""
run_benchmark.py

Purpose
-------
The CLI entry point for a real, research-grade benchmark run against a
live LLM provider -- and, per the spec's "Cost and Safety" / "Real
Benchmark Execution" requirements, the *only* place in this framework
that is allowed to decide "are we permitted to spend real API calls
right now". Every other module in `backend/evaluation/` is provider-
agnostic and mode-agnostic by construction (it takes whatever
`LLMClient` it is handed); this script is where that choice is finally
made, deliberately kept in one small, auditable place.

Why real execution requires `RUN_LLM_BENCHMARK=true`, not just an API key
-------------------------------------------------------------------------------
The spec is explicit: "Do not make real API calls simply because an
API key exists." A developer's shell often has `OPENAI_API_KEY`/
`GEMINI_API_KEY` set for unrelated reasons (running the actual
application, a different project). Requiring a *second*, benchmark-
specific opt-in means running this script can never be an accident of
environment state -- see `_require_real_execution_enabled` below,
which checks the env var and nothing else (never "does a key happen to
be present").

No concurrency
--------------
Every case runs sequentially through `BenchmarkRunner`, per the spec's
explicit warning against "uncontrolled parallel API requests" and this
being a deliberate v1 scope limitation, not an oversight -- a future
version could add a bounded worker pool, but that requires its own
rate-limit/cost analysis this phase does not attempt.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import yaml

from evaluation.benchmark_runner import (
    DEFAULT_MAX_RETRIES,
    BenchmarkRunner,
    LanguageAgentFactory,
)
from evaluation.dataset_loader import load_all_datasets
from evaluation.evaluator import ResultEvaluator
from evaluation.exceptions import BenchmarkConfigurationError
from evaluation.metrics import MetricsCalculator
from evaluation.models import (
    BENCHMARK_VERSION,
    BenchmarkCase,
    DatasetCategory,
    RunMetadata,
    RunMode,
    generate_run_id,
)
from evaluation.recovery_evaluation import RecoveryEvaluator
from evaluation.result_store import BenchmarkResultStore
from language.config import LLMRuntimeConfig, PromptAssetPaths
from language.prompt_builder import PromptAssetConfig, PromptBuilder
from language.provider_factory import create_llm_client

_DATASET_CHOICES = ("all", "success", "failure", "ambiguity")
_DATASET_NAME_TO_CATEGORY = {
    "success": DatasetCategory.SUCCESS,
    "failure": DatasetCategory.FAILURE,
    "ambiguity": DatasetCategory.AMBIGUITY,
}


def _require_real_execution_enabled() -> None:
    """
    The single gate every real-provider run passes through. See this
    module's docstring for why this checks one specific env var and
    nothing else.
    """
    if os.environ.get("RUN_LLM_BENCHMARK") != "true":
        raise BenchmarkConfigurationError(
            "Real benchmark execution requires RUN_LLM_BENCHMARK=true to be "
            "set explicitly. This script never calls a real LLM provider "
            "otherwise, even if a provider API key is present in the "
            "environment -- see this module's docstring."
        )


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Phase 3.6 language benchmark against a real LLM provider. "
        "Requires RUN_LLM_BENCHMARK=true."
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Overrides LANGUAGE_LLM_PROVIDER (openai|gemini).",
    )
    parser.add_argument("--model", default=None, help="Overrides LANGUAGE_LLM_MODEL.")
    parser.add_argument("--dataset", choices=_DATASET_CHOICES, default="all")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of cases to run per dataset.",
    )
    return parser.parse_args(argv)


def _select_cases(
    dataset_choice: str, limit: Optional[int]
) -> Tuple[List[BenchmarkCase], Dict[str, str]]:
    loaded = load_all_datasets()
    categories = (
        list(DatasetCategory)
        if dataset_choice == "all"
        else [_DATASET_NAME_TO_CATEGORY[dataset_choice]]
    )
    cases: List[BenchmarkCase] = []
    dataset_versions: Dict[str, str] = {}
    for category in categories:
        category_cases, provenance = loaded[category]
        cases.extend(category_cases[:limit] if limit is not None else category_cases)
        dataset_versions[category.value] = (
            f"{provenance.schema_version}/{provenance.prompt_version}"
        )
    return cases, dataset_versions


def _load_prompt_config(paths: PromptAssetPaths) -> PromptAssetConfig:
    """
    Reads `prompt_config.yaml` directly, reusing the real
    `PromptAssetConfig.from_mapping` parsing/validation logic from
    `language/prompt_builder.py` rather than duplicating it -- this
    script needs the decoding parameters for `RunMetadata` but has no
    reason to touch `PromptBuilder`'s private cache internals to get
    them.
    """
    with paths.prompt_config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return PromptAssetConfig.from_mapping(raw, source=paths.prompt_config_path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    _require_real_execution_enabled()

    llm_runtime_config = LLMRuntimeConfig.from_env()
    if args.provider or args.model:
        llm_runtime_config = LLMRuntimeConfig(
            provider=args.provider or llm_runtime_config.provider,
            model=args.model or llm_runtime_config.model,
            base_url=llm_runtime_config.base_url,
            api_key_env_var=llm_runtime_config.api_key_env_var,
            timeout_seconds=llm_runtime_config.timeout_seconds,
            max_retries=llm_runtime_config.max_retries,
        )
    llm_client = create_llm_client(llm_runtime_config)

    prompt_paths = PromptAssetPaths.from_env()
    prompt_builder = PromptBuilder(prompt_paths)
    prompt_config = _load_prompt_config(prompt_paths)

    agent_factory = LanguageAgentFactory.default(
        llm_client=llm_client, prompt_builder=prompt_builder
    )

    cases, dataset_versions = _select_cases(args.dataset, args.limit)
    runner = BenchmarkRunner(agent_factory, case_limit=None, run_mode=RunMode.REAL)
    records = runner.run(cases)

    records_by_id = {record.case_id: record for record in records}
    evaluator = ResultEvaluator()
    evaluations = [
        evaluator.evaluate(case, records_by_id[case.case_id])
        for case in cases
        if case.case_id in records_by_id
    ]

    metrics = MetricsCalculator().compute(evaluations, records)
    recovery_report = RecoveryEvaluator().evaluate(evaluations, records)

    run_metadata = RunMetadata(
        run_id=generate_run_id(
            f"real-{llm_runtime_config.provider}-{llm_runtime_config.model}"
        ),
        timestamp=datetime.now(timezone.utc).isoformat(),
        benchmark_version=BENCHMARK_VERSION,
        provider=llm_runtime_config.provider,
        model=llm_runtime_config.model,
        prompt_version=prompt_config.prompt_version,
        schema_version=prompt_config.schema_version,
        dataset_versions=dataset_versions,
        recovery_max_retries=DEFAULT_MAX_RETRIES,
        decoding_temperature=prompt_config.temperature,
        decoding_top_p=prompt_config.top_p,
        decoding_max_tokens=prompt_config.max_tokens,
        case_limit=args.limit,
        num_cases=len(cases),
        num_completed=sum(1 for record in records if record.succeeded),
        num_failed=sum(1 for record in records if not record.succeeded),
        run_mode=RunMode.REAL,
    )

    store = BenchmarkResultStore()
    run_dir = store.save(run_metadata, records, metrics, recovery=recovery_report)
    print(f"Benchmark run complete: {run_dir}")
    print(f"Task accuracy (micro): {metrics.overall.task_accuracy_micro.value}")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
