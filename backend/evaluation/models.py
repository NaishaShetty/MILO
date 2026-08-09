"""
models.py

Purpose
-------
Defines every data shape the Phase 3.6 evaluation framework passes
between its stages: a loaded benchmark case, one raw execution record,
a field-level comparison, a per-case verdict, an aggregated metric, and
the versioned metadata that makes a benchmark run reproducible.

Why one shared models file
---------------------------
`dataset_loader.py`, `benchmark_runner.py`, `evaluator.py`,
`metrics.py`, `provider_comparison.py`, `prompt_comparison.py`,
`recovery_evaluation.py`, and `result_store.py` all need to agree on
these shapes without importing each other's internals -- exactly the
same rationale `backend/language/failures.py` gives for
`RuntimeMetadata`/`FailureRecord`. Keeping them here (frozen
dataclasses, matching this repository's established style for
structured-but-simple data) means every stage of the pipeline is
independently testable and the shapes can be serialized to JSON for
`results/language/benchmark_runs/` without any stage needing to know
about persistence.

What future work depends on this file
--------------------------------------
Every module in `backend/evaluation/` and every `backend/tests/
test_evaluation_*.py` file. A future Phase 4 research report or a
Phase 3.7 API endpoint that surfaces benchmark results would also read
these shapes (via `result_store.py`'s JSON output), not reimplement
them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

#: Independent version of the *evaluation framework itself* -- distinct
#: from `prompt_version` (`backend/prompts/prompt_version.md`) and
#: `schema_version` (`backend/schemas/metadata.py`), per this project's
#: explicit "do not conflate these" requirement. Bump this when the
#: scoring rules, metric definitions, or result-file shape change in a
#: way that would make two runs' numbers not directly comparable.
BENCHMARK_VERSION = "0.1.0"


def generate_run_id(prefix: str) -> str:
    """
    Shared `run_id` generator used by `result_store.py`,
    `provider_comparison.py`, and `prompt_comparison.py` -- a single
    implementation so every benchmark run identifier follows the same
    `{prefix}_{utc-timestamp}_{short-uuid}` shape (sortable by time,
    collision-resistant, and human-scannable), per the spec's "each run
    must have a unique identifier" requirement.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    safe_prefix = "".join(ch if ch.isalnum() else "-" for ch in prefix)
    return f"{safe_prefix}_{timestamp}_{suffix}"


class DatasetCategory(str, Enum):
    """
    The three benchmark datasets in `datasets/language/evaluation/`,
    kept as a closed enum (rather than a bare string) so every module
    that branches on dataset type does so against one shared
    vocabulary. Values match the JSON files' own array keys so
    `dataset_loader.py` needs no separate name-mapping table.
    """

    SUCCESS = "success_cases"
    FAILURE = "failure_cases"
    AMBIGUITY = "ambiguity_cases"


@dataclass(frozen=True)
class DatasetProvenance:
    """
    Per-file version/identity metadata read directly from a dataset
    JSON's `$schema_version`/`$prompt_version` header fields --
    recorded on every `RunMetadata` so a researcher can tell exactly
    which version of a dataset produced a given result, per this
    project's reproducibility requirement.
    """

    dataset: DatasetCategory
    source_path: str
    schema_version: str
    prompt_version: str
    case_count: int


@dataclass(frozen=True)
class BenchmarkCase:
    """
    One normalized benchmark case, regardless of which of the three
    dataset files it came from. `dataset_loader.py` is the only module
    that reads raw dataset JSON; every other module depends on this
    shape instead, so a future fourth dataset file only requires a new
    loader function, not changes throughout the framework.

    Only the fields relevant to a given case's `dataset` are populated;
    the rest stay `None`/empty -- see each field's own comment for
    which dataset(s) set it. `evaluator.py` is expected to branch on
    `dataset` and only read the fields that dataset defines.
    """

    case_id: str
    dataset: DatasetCategory
    #: The dataset's own per-case category/type label -- `category`
    #: for success/failure cases, `ambiguity_type` for ambiguity cases.
    #: Kept under one name here since every dataset has exactly one
    #: such label, even though the source JSON key differs.
    category: str
    instruction: str

    #: success_cases only: the target `SingleTask`/`MultiTask`, as the
    #: raw dict from the dataset JSON (never re-validated here --
    #: `evaluator.py` compares field-by-field against whatever the
    #: dataset actually says, even if a field name in this dict were
    #: to drift from the schema).
    expected_output: Optional[Dict[str, Any]] = None

    #: failure_cases only. `candidate_output` may be a raw string (for
    #: syntactically-invalid-JSON cases) or a dict (for schema/semantic
    #: violation cases) -- `benchmark_runner.py` serializes a dict to a
    #: JSON string before handing it to `StaticResponseLLMClient`.
    candidate_output: Optional[Any] = None
    expected_validation_result: Optional[str] = (
        None  # reject_syntactic|reject_semantic|accept
    )

    #: ambiguity_cases only.
    expected_needs_clarification: Optional[bool] = None
    ambiguity_type: Optional[str] = None
    reason_keywords: List[str] = field(default_factory=list)

    #: Free-text provenance note carried through from the dataset,
    #: never used for scoring -- only for human-readable result output.
    notes: Optional[str] = None


class RunMode(str, Enum):
    """
    Whether a benchmark run used a real `LLMClient` (a genuine research
    measurement, gated behind `RUN_LLM_BENCHMARK=true`) or a
    deterministic fixture `LLMClient` (framework/CI validation only --
    see `run_benchmark.py`'s module docstring for why this distinction
    must never be blurred in a stored result).
    """

    MOCKED = "mocked"
    REAL = "real"


@dataclass(frozen=True)
class RawBenchmarkRecord:
    """
    The unscored output of running one `BenchmarkCase` through the
    Language Agent -- `benchmark_runner.py`'s sole product. Deliberately
    carries no verdict/score of its own (per the spec's "the benchmark
    runner must NOT calculate complex metrics itself" requirement) --
    `evaluator.py` is what turns this into a `CaseEvaluation`.

    Security note: `error_message` is always the already-redacted
    string from a `LanguageRuntimeError` (see `llm_client.py`'s
    credential-redaction policy, which every message in this pipeline
    already passes through) -- never a raw request/response dump.
    """

    case_id: str
    dataset: DatasetCategory
    category: str

    #: True iff `parse_with_diagnostics` returned instead of raising.
    succeeded: bool

    #: Present iff `succeeded` -- the resulting `SingleTask`/`MultiTask`
    #: as a plain dict (`Task.model_dump(mode="json")`), so
    #: `evaluator.py` never needs to import `schemas.task` itself.
    parsed_instruction: Optional[Dict[str, Any]] = None

    #: Present iff `succeeded` -- `RuntimeMetadata` fields flattened
    #: into a dict (enums as their `.value`), never the dataclass
    #: itself, so this record has no dependency on `backend/language/`
    #: types outside this one construction site.
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    schema_version: Optional[str] = None
    attempt_number: Optional[int] = None
    llm_latency_ms: Optional[float] = None
    recovered: Optional[bool] = None
    last_failure_category: Optional[str] = None

    #: Present iff not `succeeded`.
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    #: Every `FailureRecord` seen during the attempt loop, flattened to
    #: dicts -- populated even on the single-attempt-unwrapped-exception
    #: path (`benchmark_runner.py` synthesizes a one-element list there
    #: so callers never need to special-case "was this wrapped in
    #: `RetryExhaustedError` or not").
    failure_records: List[Dict[str, Any]] = field(default_factory=list)

    #: Wall-clock time of the *entire* `parse_with_diagnostics()` call,
    #: measured by the runner itself with `time.perf_counter()` -- unlike
    #: `llm_latency_ms` (only the final successful LLM call), this
    #: covers every attempt, every repair, every retry, so
    #: `recovery_evaluation.py` can compute a real recovery latency
    #: overhead.
    total_latency_ms: float = 0.0

    #: Which `LLMClient` implementation produced this record -- `"real"`
    #: for a live provider call, `"static"` for `StaticResponseLLMClient`
    #: (always true for `failure_cases`, see `benchmark_runner.py`).
    run_mode: RunMode = RunMode.MOCKED


class EvaluationOutcome(str, Enum):
    """
    The correctness verdict `evaluator.py` assigns to one case, per the
    spec's "distinguish SUCCESS / EXPECTED_FAILURE / UNEXPECTED_FAILURE
    / EXPECTED_CLARIFICATION / UNEXPECTED_CLARIFICATION /
    RECOVERED_FAILURE / UNRECOVERED_FAILURE" requirement. Three members
    beyond that list are added, each required to satisfy a different
    part of the spec that the named seven do not by themselves cover
    (see each member's comment) -- the spec calls its own list "at
    minimum", not exhaustive.
    """

    #: Case behaved exactly as its dataset expects, on the first
    #: attempt (no recovery needed).
    SUCCESS = "success"
    #: failure_cases only: the dataset expects rejection
    #: (`reject_syntactic`/`reject_semantic`) and the pipeline correctly
    #: raised -- this is the *correct* outcome for such a case, not a
    #: framework failure.
    EXPECTED_FAILURE = "expected_failure"
    #: success_cases/ambiguity_cases: the dataset expects a successful
    #: parse and the pipeline raised instead.
    UNEXPECTED_FAILURE = "unexpected_failure"
    #: ambiguity_cases: dataset expects `needs_clarification=True` and
    #: the agent correctly set it -- a success, not a parser failure
    #: (spec's explicit clarification-handling requirement).
    EXPECTED_CLARIFICATION = "expected_clarification"
    #: ambiguity_cases: dataset expects `needs_clarification=False`
    #: (a true-negative case) but the agent asked for clarification
    #: anyway -- over-triggering.
    UNEXPECTED_CLARIFICATION = "unexpected_clarification"
    #: Any dataset: the first attempt failed but `RuntimeMetadata.recovered`
    #: is `True` and the final result still matches the case's expected
    #: behavior -- recovery is cross-cutting (see
    #: `recovery_evaluation.py`), not `failure_cases`-only.
    RECOVERED_FAILURE = "recovered_failure"
    #: Any dataset: recovery was attempted (a retry actually happened)
    #: but the pipeline still never produced the expected result.
    UNRECOVERED_FAILURE = "unrecovered_failure"
    #: ambiguity_cases: dataset expects `needs_clarification=True` and
    #: the agent set it `False` -- a missed detection. Required by the
    #: spec's own "Clarification Accuracy: ... Missed clarification"
    #: metric, which the seven named states cannot express on their own.
    MISSED_CLARIFICATION = "missed_clarification"
    #: success_cases: the pipeline returned a structurally valid result
    #: with no error, but field-level comparison found a mismatch --
    #: required by the spec's "do not reduce everything to a single
    #: pass/fail value" requirement; a wrong-but-valid answer is neither
    #: a pipeline failure nor a correct success.
    INCORRECT_OUTPUT = "incorrect_output"
    #: failure_cases: dataset expects rejection but the pipeline
    #: accepted `candidate_output` anyway -- a validation false
    #: negative, the mirror case of `EXPECTED_FAILURE`.
    INVALID_ACCEPTANCE = "invalid_acceptance"


@dataclass(frozen=True)
class FieldComparison:
    """
    One field-level comparison result, keyed by a dotted/bracketed path
    (e.g. `"attributes.color"`, `"subtasks[1].object"`) so a nested
    `MultiTask` structure can be scored without a bespoke shape per
    nesting level. `applicable=False` marks a field the case's
    `expected_output` did not define at all (skipped, per the spec's
    "only evaluate fields that are applicable" rule) -- distinct from
    `expected=None, actual=None, match=True`, which is a legitimate,
    scored null-vs-null match (spec: "do not penalize legitimate null
    values", meaning null is a checkable value, not an automatic skip).
    """

    path: str
    expected: Any
    actual: Any
    match: bool
    applicable: bool = True


@dataclass(frozen=True)
class RecoveryInfo:
    """
    Cross-cutting recovery diagnostics attached to every
    `CaseEvaluation`, independent of `EvaluationOutcome` -- so
    `recovery_evaluation.py` can analyze "did recovery help" across all
    three datasets without re-deriving it from outcome labels that
    exist for a different purpose (correctness scoring).
    """

    #: True iff a second (or later) attempt was actually made -- i.e.
    #: more than one `FailureRecord` was produced, or the case succeeded
    #: with `RuntimeMetadata.recovered=True`.
    recovery_attempted: bool
    #: True iff recovery was attempted AND the case's final state
    #: matches its dataset's expected behavior.
    recovered: bool
    #: `attempt_number - 1` on a successful record; `len(failure_records)`
    #: on a failed one (every recorded attempt, since none succeeded).
    retry_count: int
    #: Every distinct `FailureCategory.value` seen for this case, in
    #: attempt order -- feeds `recovery_evaluation.py`'s per-category
    #: breakdown.
    failure_categories: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaseEvaluation:
    """
    `evaluator.py`'s sole product: one `BenchmarkCase` + its
    `RawBenchmarkRecord`, scored. Everything `metrics.py`,
    `provider_comparison.py`, `prompt_comparison.py`, and
    `recovery_evaluation.py` compute is derived from a list of these --
    none of those modules re-inspects a raw record or re-implements
    comparison logic, per this project's "no duplicated evaluation
    rules" requirement.
    """

    case_id: str
    dataset: DatasetCategory
    category: str
    outcome: EvaluationOutcome
    #: Convenience boolean derived from `outcome` (see
    #: `evaluator.py`'s `_CORRECT_OUTCOMES`) -- every accuracy metric in
    #: `metrics.py` is a ratio over this field, so it is computed once
    #: here rather than re-checked against the outcome enum at every
    #: call site.
    correct: bool
    field_results: List[FieldComparison] = field(default_factory=list)
    recovery: Optional[RecoveryInfo] = None
    #: Only meaningful for ambiguity_cases -- whether the
    #: `needs_clarification` boolean itself matched, independent of
    #: `outcome`'s finer-grained labeling. `None` for cases where
    #: clarification is not the thing being measured.
    clarification_correct: Optional[bool] = None


@dataclass(frozen=True)
class MetricValue:
    """
    One named, defined metric, per the spec's "every metric MUST have
    Name/Definition/Formula/Numerator/Denominator/Interpretation/
    Edge-case handling" requirement -- a metric is never a bare float
    anywhere in this framework's public output.

    Edge-case handling: `value` is `None` when `denominator == 0`
    (e.g. no multi-task cases present, no ambiguity cases in this
    dataset), which every consumer (`result_store.py`'s JSON output,
    `provider_comparison.py`'s table) must render as "not applicable",
    never as `0.0` -- a `0.0` would misleadingly claim "measured and
    scored zero" for something that was never measured at all.
    """

    name: str
    definition: str
    numerator: float
    denominator: float
    interpretation: str

    @property
    def value(self) -> Optional[float]:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator


@dataclass(frozen=True)
class RetryStats:
    """Retry statistics (spec section 3.6.3.K) over a set of cases."""

    average_retries: Optional[float]
    max_retries: int
    #: retry_count -> number of cases that needed exactly that many
    #: retries (0 included, for cases that succeeded on the first try).
    distribution: Dict[int, int]
    #: Fraction of cases that needed at least one retry.
    retry_rate: MetricValue


@dataclass(frozen=True)
class LatencyStats:
    """
    Wall-clock latency statistics (spec section 3.6.3.L), computed over
    `RawBenchmarkRecord.total_latency_ms` -- `None` fields mean no
    records were available to measure (e.g. an empty category).
    """

    average_ms: Optional[float]
    median_ms: Optional[float]
    min_ms: Optional[float]
    max_ms: Optional[float]
    p95_ms: Optional[float]
    sample_count: int


@dataclass(frozen=True)
class CategoryMetrics:
    """
    All spec section 3.6.3 metrics computed over one dataset category
    (`success_cases`/`failure_cases`/`ambiguity_cases`). `accuracy`
    holds every ratio metric (A-J), keyed by metric name (e.g.
    `"task_accuracy"`, `"goal_accuracy"`, `"clarification_correct"`) so
    the set of applicable metrics can differ per category (e.g.
    `attribute_accuracy` is meaningless for `ambiguity_cases`) without
    every category needing every field populated.
    """

    dataset: DatasetCategory
    case_count: int
    accuracy: Dict[str, MetricValue]
    retry_stats: RetryStats
    latency_stats: LatencyStats
    #: `FailureCategory.value` -> occurrence count, over every
    #: `FailureRecord` seen in this category (spec section 3.6.3.M) --
    #: only categories from `language.failures.FailureCategory` ever
    #: appear as keys, per the spec's "do not invent new categories"
    #: rule.
    failure_distribution: Dict[str, int]


@dataclass(frozen=True)
class OverallMetrics:
    """
    The cross-category rollup. `task_accuracy_micro` pools every case
    from every category into one ratio; `task_accuracy_macro` averages
    each category's own accuracy unweighted -- per the spec's
    requirement that a large category (here, `success_cases` at 15
    cases vs. `ambiguity_cases` at 10) must not silently dominate a
    single combined number. Both are always reported side by side, never
    collapsed into one "overall score".
    """

    case_count: int
    task_accuracy_micro: MetricValue
    task_accuracy_macro: MetricValue
    retry_stats: RetryStats
    latency_stats: LatencyStats
    failure_distribution: Dict[str, int]


@dataclass(frozen=True)
class MetricsReport:
    """`metrics.py`'s sole product: per-category metrics plus the overall rollup."""

    per_category: Dict[str, CategoryMetrics]
    overall: OverallMetrics


@dataclass(frozen=True)
class RunMetadata:
    """
    Everything the spec's "Run Metadata"/"Reproducibility" sections
    require to be recorded for a benchmark run -- deliberately excludes
    API keys/credentials/headers (spec's "No Data Leakage" requirement);
    every field here is either a version string, a count, or a
    non-secret decoding parameter.
    """

    run_id: str
    timestamp: str
    benchmark_version: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    #: `DatasetCategory.value` -> `"{schema_version}/{prompt_version}"`,
    #: from each dataset file's own header -- lets a researcher confirm
    #: which exact dataset revision produced this run's numbers.
    dataset_versions: Dict[str, str]
    recovery_max_retries: int
    decoding_temperature: Optional[float]
    decoding_top_p: Optional[float]
    decoding_max_tokens: Optional[int]
    case_limit: Optional[int]
    num_cases: int
    num_completed: int
    num_failed: int
    run_mode: RunMode


@dataclass(frozen=True)
class ProviderComparisonRow:
    """One row of the spec's "Provider Comparison Output" table."""

    provider: str
    model: str
    run_id: str
    task_accuracy: Optional[float]
    goal_accuracy: Optional[float]
    object_accuracy: Optional[float]
    clarification_accuracy: Optional[float]
    recovery_rate: Optional[float]
    average_latency_ms: Optional[float]


@dataclass(frozen=True)
class ProviderComparisonReport:
    """`provider_comparison.py`'s sole product -- the generated table, never hardcoded."""

    rows: List[ProviderComparisonRow]


@dataclass(frozen=True)
class PromptComparisonRow:
    """One row of a prompt-version comparison table -- mirrors `ProviderComparisonRow`."""

    prompt_version: str
    provider: str
    model: str
    run_id: str
    task_accuracy: Optional[float]
    goal_accuracy: Optional[float]
    object_accuracy: Optional[float]
    clarification_accuracy: Optional[float]
    recovery_rate: Optional[float]
    average_latency_ms: Optional[float]


@dataclass(frozen=True)
class PromptComparisonReport:
    """`prompt_comparison.py`'s sole product."""

    rows: List[PromptComparisonRow]


@dataclass(frozen=True)
class RecoveryCategoryBreakdown:
    """
    Recovered/unrecovered counts for one `FailureCategory`, per the
    spec's "Recovery Analysis" tree (INVALID_JSON -> recovered/
    unrecovered, SCHEMA_VALIDATION_ERROR -> ..., ...).
    """

    category: str
    recovered: int
    unrecovered: int


@dataclass(frozen=True)
class RecoveryReport:
    """`recovery_evaluation.py`'s sole product -- spec section 3.6.6's full metric set."""

    total_cases: int
    initial_success_rate: MetricValue
    initial_failure_rate: MetricValue
    recovery_attempt_rate: MetricValue
    recovery_success_rate: MetricValue
    final_success_rate: MetricValue
    unrecovered_failure_rate: MetricValue
    #: `None` when no case was ever recovered (nothing to average).
    average_retries_for_recovered: Optional[float]
    #: Mean `total_latency_ms` of recovered cases minus mean
    #: `total_latency_ms` of clean-first-attempt cases -- an
    #: approximation of recovery's wall-clock cost, documented as such
    #: since only whole-call timing (not a per-attempt breakdown) is
    #: available (see `RawBenchmarkRecord.total_latency_ms`). `None`
    #: when either group is empty.
    recovery_latency_overhead_ms: Optional[float]
    breakdown_by_category: List[RecoveryCategoryBreakdown]


def to_jsonable(value: Any) -> Any:
    """
    Recursively converts a value built from this module's dataclasses
    (plus plain dict/list/Enum/primitive contents) into a structure
    `json.dump` can serialize directly -- `result_store.py`'s only
    conversion step, so every other module can keep passing around
    typed dataclasses instead of pre-serialized dicts.

    Deliberately generic (dataclass/Enum/dict/list/primitive) rather
    than one hand-written `to_dict()` per model: this file already
    dedicates one dataclass per concept specifically so a generic
    walker is sufficient and no per-class serialization logic needs to
    be kept in sync as fields are added.
    """
    if is_dataclass(value) and not isinstance(value, type):
        result: Dict[str, Any] = {}
        for attr_name in value.__dataclass_fields__:
            result[attr_name] = to_jsonable(getattr(value, attr_name))
        # `MetricValue.value` is a computed property, not a dataclass
        # field -- included explicitly so the stored JSON always shows
        # the resolved ratio (or `null` when not applicable) alongside
        # its numerator/denominator, rather than requiring a reader to
        # recompute it.
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
