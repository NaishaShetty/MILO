"""
run_benchmark.py (backend/planning_evaluation)

Purpose
-------
Phase E's planner-comparison axis: scores `RuleBasedPlanner`,
`BehaviorTreePlanner`, and `ReActPlanner` against every task in
`dataset/v1.0/tasks.json` on real AI2-THOR. Each episode restarts the
simulator (fresh Unity process per episode -- the "fresh scene per
episode" substitute `real_scenarios.py`/`run_floorplan_sweep.py`
already use, since `Simulator` has no object-teleportation
capability).

`ReActPlanner` baseline (Phase E follow-up)
--------------------------------------------------
Runs against Google's Gemini API (`LANGUAGE_LLM_PROVIDER=gemini` must
be set, `GEMINI_API_KEY` must be a real key -- see `language.config.
LLMRuntimeConfig.from_env()`) via `language.provider_factory.
create_llm_client()`, exactly the production wiring path, never a
benchmark-specific client. `REACT_MODEL_VERSION` records the exact
model string used (see `LLMRuntimeConfig.model`, default
`"gemini-flash-latest"`) for reproducibility -- Google's own
free-tier availability/eligibility for that model is controlled
entirely by Google, not this project.

Free-tier reality, handled honestly, not hidden: Gemini's API returned
intermittent `503 UNAVAILABLE` ("This model is currently experiencing
high demand") during real runs -- roughly 2 of 3 calls in an initial
3-call smoke test, with no relation to task content. `run_react_episode()`
retries an episode up to `REACT_MAX_TRANSIENT_RETRIES` additional times
ONLY when the planning failure looks like this specific transient
provider condition (`_is_transient_llm_error()` -- matches on `503`/
`UNAVAILABLE`/`429`/`RESOURCE_EXHAUSTED`/`rate limit`/`quota`, not on
any other planning failure), and every episode's `BenchmarkEpisodeResult.
llm_retry_attempts` records exactly how many extra attempts it took --
0 for every non-`react` planner and for any `react` episode that
succeeded first try. The final reported numbers are real outcomes
after this bounded, fully-logged retry policy, never a number silently
padded by unlimited retrying until something succeeds.

Two independent success signals per episode, both recorded (see
`live_state.py`'s docstring for why they can disagree):
- `execution_success`: `TaskRunResult.succeeded` -- did every
  dispatched step complete without a simulator error.
- `goal_success`: `live_state.check_goal_live()` -- does the task's
  goal condition actually hold in the live scene after execution, per
  AI2-THOR's own object fields. This is the benchmark's primary score;
  `execution_success` is reported alongside it because the two are not
  the same claim (a plan can execute every step without a dispatch
  error and still not satisfy the goal, and vice versa is not possible
  for this task set but is not assumed).

Output
------
Writes `experiments/results/milo_benchmark_<timestamp>.json` (full
per-episode detail, `reproducibility` metadata block, per-planner and
per-tier summaries) and a matching `_episodes.csv`, same convention as
`memory_evaluation/run_ablation_real.py` and `run_floorplan_sweep.py`.

How to run
-----------
Opt-in gated (launches a real Unity subprocess per episode -- 25 tasks
x 3 planners = 75 episodes, plus any transient-error retries):

    cd backend
    RUN_SIMULATOR_TESTS=true LANGUAGE_LLM_PROVIDER=gemini python -m planning_evaluation.run_benchmark

(`GEMINI_API_KEY` must already be set -- e.g. via `.env`. Without a
real key/provider configured, `react` episodes will fail immediately
with a real `ConfigurationError`/provider error, reported honestly
like any other real failure -- this script never fakes a client.)

Addendum -- local `qwen2.5:7b`/Ollama re-run (perception-grounding
follow-up)
--------------------------------------------------------------------
The Gemini free-tier path above hit a daily quota after 2 episodes
(see `experiments/reports/phase_e_milo_benchmark_report.md`'s
Addendum 2) and is no longer this project's `react` baseline;
Addendum 3 of that report replaced it with a real local run:

    cd backend
    RUN_SIMULATOR_TESTS=true LANGUAGE_LLM_PROVIDER=qwen \
      LANGUAGE_LLM_MODEL=qwen2.5:7b \
      LANGUAGE_LLM_BASE_URL=http://localhost:11434/v1 \
      QWEN_API_KEY=not-needed \
      LANGUAGE_LLM_TIMEOUT_SECONDS=120 \
      python -m planning_evaluation.run_benchmark

(Ollama, or any other OpenAI-API-compatible local server, must already
be serving `qwen2.5:7b` at that URL -- `ollama serve` +
`ollama pull qwen2.5:7b`.) This is also the run that first exercised
this module's perception-grounded `tier1_locate` dual check (see
`_build_shared_vision_stage`/`_build_vision_agent_for_episode` above
and `live_state.py`'s docstring addendum) -- `GroundingDINODetector`/
`SAM2Segmenter` are loaded once, lazily, the first time a
`tier1_locate` episode needs them, and reused (rebound to each fresh
per-episode `Simulator`) for the rest of the run. On a 6GB-VRAM laptop
GPU shared with a locally-served 7B model, this is a real VRAM-
contention risk during `react` episodes specifically -- see this
project's report for whether it was actually observed.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agents.vision_agent import VisionAgentWrapper
from language.config import LLMRuntimeConfig
from language.provider_factory import create_llm_client
from memory_evaluation.experiment_real import _seed_initial_state_from_live_metadata
from orchestration.task_runner import TaskRunner
from planner.behavior_tree import BehaviorTreePlanner
from planner.planner import Planner
from planner.react import ReActPlanner
from planner.rule_based import RuleBasedPlanner
from planning_evaluation.live_state import (
    TIER1_LOCATE_GOALS,
    check_goal_live,
    check_goal_live_grounded,
)
from planning_evaluation.loader import BenchmarkTask, load_tasks
from simulator.simulator import Simulator

RESULTS_DIR = Path(__file__).resolve().parents[2] / "experiments" / "results"

#: Set true (via `_build_shared_vision_stage()`, called once at import/
#: startup, never per-episode) once the expensive detector/segmenter
#: models have been loaded onto the GPU -- so `run_episode()` can tell
#: "vision unavailable, skip" from "vision not attempted yet" and avoid
#: rebuilding either model per episode (see module docstring's
#: "perception-grounded tier1_locate" section for why this must be
#: built once and reused, not once per episode: GPU model construction
#: is the expensive part, not inference).
_VISION_STAGE_BUILT = False
_VISION_DETECTOR = None
_VISION_SEGMENTER = None
_VISION_BUILD_ERROR: Optional[str] = None


def _build_shared_vision_stage() -> None:
    """
    Constructs `GroundingDINODetector`/`SAM2Segmenter` exactly once
    (real HuggingFace models onto CUDA -- see this module's docstring's
    VRAM-cost note) and caches them at module scope. Only called lazily,
    the first time a `tier1_locate` episode actually needs perception
    grounding -- `tier2_pickup`/`tier3_store` episodes never trigger
    this, so non-tier1 runs pay zero vision cost.

    Any construction failure (missing weights, CUDA OOM, no GPU) is
    caught and recorded in `_VISION_BUILD_ERROR` rather than raised --
    `run_episode()` then reports `perceived_by_agent=None` with that
    error attached instead of crashing the whole benchmark run over a
    perception-only signal. This mirrors `api/app.py`'s own
    "vision unavailable must degrade, never crash" policy for the same
    detector/segmenter construction.
    """
    global _VISION_STAGE_BUILT, _VISION_DETECTOR, _VISION_SEGMENTER, _VISION_BUILD_ERROR
    if _VISION_STAGE_BUILT:
        return
    _VISION_STAGE_BUILT = True
    try:
        from vision.detectors.grounding_dino_detector import GroundingDINODetector
        from vision.segmenters.sam2_segmenter import SAM2Segmenter

        _VISION_DETECTOR = GroundingDINODetector()
        _VISION_SEGMENTER = SAM2Segmenter()
    except Exception as exc:  # noqa: BLE001 -- record, never crash the benchmark
        _VISION_BUILD_ERROR = f"{type(exc).__name__}: {exc}"


def _build_vision_agent_for_episode(
    simulator: Simulator,
) -> Optional[VisionAgentWrapper]:
    """
    Rebinds the shared, already-loaded detector/segmenter (see
    `_build_shared_vision_stage`) to `simulator` -- a fresh `Simulator`
    instance per episode (this module restarts Unity every episode; see
    module docstring). `VisionAgent`/`GroundTruthDepthEstimator` both
    bind to one `Simulator` instance at construction, so a new,
    otherwise-cheap `VisionAgent`/depth-estimator/tracker/scene-graph is
    built per episode -- the expensive GPU model objects themselves are
    never rebuilt. Returns `None` (with `_VISION_BUILD_ERROR` set) if
    the shared stage failed to build.
    """
    _build_shared_vision_stage()
    if _VISION_DETECTOR is None or _VISION_SEGMENTER is None:
        return None
    from vision.scene_graph.heuristic_scene_graph import HeuristicSceneGraph
    from vision.tracking.iou_tracker import IoUTracker
    from vision.vision_agent import VisionAgent

    # Deliberately no depth stage here: `GroundTruthDepthEstimator`
    # requires the simulator to have been started with
    # `render_depth=True` (`AI2ThorEnv.get_depth()` raises otherwise --
    # discovered running this for real, see module docstring), and this
    # module's episodes never opt into that (rule_based/behavior_tree
    # episodes have no other use for depth). `ground_world_state()`'s
    # `is_located` check -- the only thing `check_goal_live_grounded()`
    # reads -- needs only `Detection.label`, never `Detection.depth`;
    # skipping the depth stage costs nothing this check needs and
    # avoids a real crash for no benefit. `is_near_robot` grounding is
    # simply left unset (`None`/default), which is fine since nothing
    # in this benchmark reads it.
    agent = VisionAgent(
        simulator,
        detector=_VISION_DETECTOR,
        segmenter=_VISION_SEGMENTER,
        depth=None,
        tracker=IoUTracker(),
        scene_graph=HeuristicSceneGraph(),
    )
    return VisionAgentWrapper(agent)


#: Bounded, fully-logged retry budget for `react` episodes that fail
#: with a transient LLM-provider condition (see module docstring) --
#: never applied to `rule_based`/`behavior_tree`, which have no LLM
#: dependency to be transient about.
REACT_MAX_TRANSIENT_RETRIES = 2

#: Substrings identifying a transient LLM-provider condition (model
#: overloaded, rate limit, quota) worth one bounded retry, as opposed
#: to a real planning/parsing failure worth reporting as-is. Matched
#: case-insensitively against `PlanningResult.errors`.
_TRANSIENT_LLM_ERROR_MARKERS = (
    "503",
    "unavailable",
    "429",
    "resource_exhausted",
    "rate limit",
    "quota",
)


def _is_transient_llm_error(errors: List[str]) -> bool:
    joined = " ".join(errors).lower()
    return any(marker in joined for marker in _TRANSIENT_LLM_ERROR_MARKERS)


class _CountingLLMClient:
    """
    Thin `LLMClient`-shaped wrapper (see `language.llm_client.LLMClient`'s
    `Protocol`, matched structurally -- no inheritance needed) that
    counts calls and accumulates token usage per episode, for
    `react`'s cost/latency instrumentation (see module docstring's
    "cost/latency" addendum). Wraps the exact same production
    `create_llm_client(LLMRuntimeConfig.from_env())` client
    `_make_react_planner` already builds -- this changes nothing about
    what gets sent to the provider, it only observes.

    `reset()` is called once per episode (`run_episode()`, before
    `runner.run()`) so `call_count`/token totals reflect exactly that
    episode's `plan()`/repair loop, not the whole benchmark run.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.call_count = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        #: True once any call this episode lacked real `usage` and had
        #: to fall back to the word/4-chars-per-token heuristic --
        #: episode-level "some or all of these tokens are estimated"
        #: flag, see `_approx_token_count`.
        self.any_approximated = False
        #: True once any call this episode returned real provider
        #: `usage`.
        self.any_real_usage = False

    def reset(self) -> None:
        self.call_count = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.any_approximated = False
        self.any_real_usage = False

    def complete(self, request):
        response = self._inner.complete(request)
        self.call_count += 1
        if response.usage is not None:
            self.prompt_tokens += response.usage.get("prompt_tokens", 0)
            self.completion_tokens += response.usage.get("completion_tokens", 0)
            self.any_real_usage = True
        else:
            self.prompt_tokens += _approx_token_count(
                request.system_prompt + request.user_message
            )
            self.completion_tokens += _approx_token_count(response.content)
            self.any_approximated = True
        return response


def _approx_token_count(text: str) -> int:
    """
    Word/4-chars-per-token heuristic, used ONLY when a provider's
    response envelope did not include real `usage` counts (see
    `language.llm_client.LLMResponse.usage`'s docstring). This is a
    rough approximation, not a real tokenizer count -- every caller of
    this function must keep it clearly labeled as approximate (see
    `BenchmarkEpisodeResult.llm_token_usage_is_approximate`), never
    presented as an exact number.
    """
    return max(1, len(text) // 4)


def _make_react_planner() -> ReActPlanner:
    client = _CountingLLMClient(create_llm_client(LLMRuntimeConfig.from_env()))
    return ReActPlanner(llm_client=client)


#: Zero-arg factories so `rule_based`/`behavior_tree` (no constructor
#: args needed) and `react` (needs a real `LLMClient`, built from the
#: environment at call time -- see `_make_react_planner`) fit the same
#: uniform shape.
PLANNERS: Dict[str, Callable[[], Planner]] = {
    "rule_based": RuleBasedPlanner,
    "behavior_tree": BehaviorTreePlanner,
    "react": _make_react_planner,
}

#: Recorded in the report's `reproducibility` block -- resolved once
#: at import time so every episode's run reflects the exact same
#: configured provider/model, whatever `LANGUAGE_LLM_PROVIDER` is set
#: to when this script runs (`gemini` for the Phase E follow-up run;
#: informational only, never used to gate `react`'s presence in
#: `PLANNERS`).
_LLM_CONFIG = LLMRuntimeConfig.from_env()
REACT_LLM_PROVIDER = _LLM_CONFIG.provider
REACT_MODEL_VERSION = _LLM_CONFIG.model


@dataclass
class BenchmarkEpisodeResult:
    planner: str
    task_id: str
    scene: str
    room_type: str
    difficulty_tier: str
    instruction: str
    goal: Optional[str]
    object: Optional[str]
    target: Optional[str]
    plan_success: bool
    execution_success: bool
    goal_success: Optional[bool]
    action_count: int
    plan_step_count: int
    failure_cause: Optional[str]
    wall_clock_ms: float
    llm_retry_attempts: int = 0

    # -- Perception-grounded tier1_locate dual check (see live_state.py's
    # docstring addendum). Both `None` for non-tier1_locate goals -- this
    # column pair is additive, it never changes what `goal_success` means
    # for tier2_pickup/tier3_store tasks.
    goal_success_exists_in_scene: Optional[bool] = None
    goal_success_perceived_by_agent: Optional[bool] = None
    perception_error: Optional[str] = None

    # -- react-only cost/latency instrumentation (see module docstring's
    # cost/latency addendum). 0 / None for rule_based/behavior_tree,
    # which never call an LLM.
    llm_call_count: int = 0
    #: Real token counts from the provider's `usage` field when the
    #: endpoint returns one; `None` when unavailable (see
    #: `llm_token_usage_is_approximate`).
    llm_prompt_tokens: Optional[int] = None
    llm_completion_tokens: Optional[int] = None
    #: True when `llm_prompt_tokens`/`llm_completion_tokens` are a
    #: word/4-chars-per-token heuristic estimate over prompt+response
    #: text rather than a real count the provider returned -- see
    #: `language.llm_client.LLMResponse`'s `usage` field docstring.
    #: `None` when no LLM call was made at all this episode.
    llm_token_usage_is_approximate: Optional[bool] = None


def run_episode(
    planner_name: str, planner: Planner, bt: BenchmarkTask
) -> BenchmarkEpisodeResult:
    task = bt.to_single_task()
    simulator = Simulator(scene=bt.scene)
    simulator.start()
    counting_client = getattr(planner, "_llm_client", None)
    if isinstance(counting_client, _CountingLLMClient):
        counting_client.reset()
    else:
        counting_client = None
    try:
        pre_metadata = simulator.get_metadata()
        initial_state = _seed_initial_state_from_live_metadata(task, pre_metadata)
        runner = TaskRunner(planner, simulator)
        started = time.perf_counter()
        run_result = runner.run(
            task,
            episode_id=str(uuid.uuid4()),
            memory_enabled=False,
            initial_state=initial_state,
        )
        wall_clock_ms = (time.perf_counter() - started) * 1000.0

        post_metadata = simulator.get_metadata()
        goal_success = check_goal_live(task, post_metadata)

        # Perception-grounded tier1_locate dual check (see
        # live_state.py's docstring addendum): only attempted for
        # tier1_locate goals -- tier2_pickup/tier3_store predicates
        # have real physical analogues and never touch vision, so this
        # never pays the vision-stack cost for them. `goal_success`
        # itself is left as `check_goal_live()`'s existing
        # existence-only answer (unchanged baseline metric, comparable
        # to every prior run) -- `perceived_by_agent` is recorded as an
        # additional, stricter, separately-visible signal, never merged
        # into `goal_success`. See module docstring's "perception-
        # grounded tier1_locate" section for the reasoning.
        goal_success_exists_in_scene: Optional[bool] = None
        goal_success_perceived_by_agent: Optional[bool] = None
        perception_error: Optional[str] = None
        if (task.goal or "").strip().lower() in TIER1_LOCATE_GOALS:
            vision_agent = _build_vision_agent_for_episode(simulator)
            grounded = check_goal_live_grounded(
                task, post_metadata, vision_agent=vision_agent
            )
            goal_success_exists_in_scene = grounded.exists_in_scene
            goal_success_perceived_by_agent = grounded.perceived_by_agent
            perception_error = grounded.perception_error
            if vision_agent is None and perception_error is None:
                perception_error = _VISION_BUILD_ERROR or "vision stack unavailable"

        plan = run_result.planning_result.plan
        plan_targets = [s.target for s in plan.steps] if plan is not None else []
        action_count = (
            len(run_result.execution_record.step_results)
            if run_result.execution_record is not None
            else 0
        )
        failure_cause = None
        if run_result.execution_record is not None:
            for step in run_result.execution_record.step_results:
                if step.error is not None:
                    failure_cause = step.error.message
                    break
        if failure_cause is None and not run_result.planning_result.success:
            failure_cause = (
                "; ".join(run_result.planning_result.errors) or "planning failed"
            )

        return BenchmarkEpisodeResult(
            planner=planner_name,
            task_id=bt.task_id,
            scene=bt.scene,
            room_type=bt.room_type,
            difficulty_tier=bt.difficulty_tier,
            instruction=bt.instruction,
            goal=task.goal,
            object=task.object,
            target=task.target,
            plan_success=run_result.planning_result.success,
            execution_success=run_result.succeeded,
            goal_success=goal_success,
            action_count=action_count,
            plan_step_count=len(plan_targets),
            failure_cause=failure_cause,
            wall_clock_ms=wall_clock_ms,
            goal_success_exists_in_scene=goal_success_exists_in_scene,
            goal_success_perceived_by_agent=goal_success_perceived_by_agent,
            perception_error=perception_error,
            llm_call_count=counting_client.call_count if counting_client else 0,
            llm_prompt_tokens=(
                counting_client.prompt_tokens if counting_client else None
            ),
            llm_completion_tokens=(
                counting_client.completion_tokens if counting_client else None
            ),
            llm_token_usage_is_approximate=(
                counting_client.any_approximated
                if counting_client and counting_client.call_count
                else None
            ),
        )
    except Exception as exc:  # noqa: BLE001 -- record, don't abort the run
        return BenchmarkEpisodeResult(
            planner=planner_name,
            task_id=bt.task_id,
            scene=bt.scene,
            room_type=bt.room_type,
            difficulty_tier=bt.difficulty_tier,
            instruction=bt.instruction,
            goal=bt.goal,
            object=bt.object,
            target=bt.target,
            plan_success=False,
            execution_success=False,
            goal_success=False,
            action_count=0,
            plan_step_count=0,
            failure_cause=f"harness_exception: {exc!r}",
            wall_clock_ms=0.0,
            llm_call_count=counting_client.call_count if counting_client else 0,
            llm_prompt_tokens=(
                counting_client.prompt_tokens if counting_client else None
            ),
            llm_completion_tokens=(
                counting_client.completion_tokens if counting_client else None
            ),
            llm_token_usage_is_approximate=(
                counting_client.any_approximated
                if counting_client and counting_client.call_count
                else None
            ),
        )
    finally:
        simulator.stop()


def run_react_episode(planner: Planner, bt: BenchmarkTask) -> BenchmarkEpisodeResult:
    """
    `run_episode` wrapped with a bounded, fully-logged retry for
    `react` only -- see module docstring's "ReActPlanner baseline"
    section for why this exists and exactly what it does and does not
    retry. Every returned result's `llm_retry_attempts` records how
    many *extra* attempts (beyond the first) were used, so the raw
    numbers are auditable, not just the final pass/fail.
    """
    attempts = 0
    while True:
        result = run_episode("react", planner, bt)
        transient = not result.plan_success and _is_transient_llm_error(
            [result.failure_cause] if result.failure_cause else []
        )
        if not transient or attempts >= REACT_MAX_TRANSIENT_RETRIES:
            result.llm_retry_attempts = attempts
            return result
        attempts += 1
        time.sleep(3.0)  # brief pause before retrying an overloaded provider


def _summarize(results: List[BenchmarkEpisodeResult]) -> Dict[str, Any]:
    def rate(rows: List[BenchmarkEpisodeResult]) -> Dict[str, Any]:
        n = len(rows)
        goal_ok = sum(1 for r in rows if r.goal_success)
        exec_ok = sum(1 for r in rows if r.execution_success)
        return {
            "n": n,
            "goal_success_rate": goal_ok / n if n else None,
            "execution_success_rate": exec_ok / n if n else None,
        }

    by_planner: Dict[str, Any] = {}
    for planner_name in PLANNERS:
        rows = [r for r in results if r.planner == planner_name]
        tier1_rows = [r for r in rows if r.goal_success_exists_in_scene is not None]
        tier1_measured = [
            r for r in tier1_rows if r.goal_success_perceived_by_agent is not None
        ]
        tier1_diverged = [
            r
            for r in tier1_measured
            if r.goal_success_exists_in_scene != r.goal_success_perceived_by_agent
        ]
        by_planner[planner_name] = {
            "overall": rate(rows),
            "by_tier": {
                tier: rate([r for r in rows if r.difficulty_tier == tier])
                for tier in sorted({r.difficulty_tier for r in rows})
            },
            "tier1_locate_grounded_check": {
                "n_tier1_tasks": len(tier1_rows),
                "n_perception_measured": len(tier1_measured),
                "exists_in_scene_ok": sum(
                    1 for r in tier1_rows if r.goal_success_exists_in_scene
                ),
                "perceived_by_agent_ok": sum(
                    1 for r in tier1_measured if r.goal_success_perceived_by_agent
                ),
                "diverged_count": len(tier1_diverged),
                "diverged_task_ids": [r.task_id for r in tier1_diverged],
                "perception_errors": [
                    {"task_id": r.task_id, "error": r.perception_error}
                    for r in tier1_rows
                    if r.perception_error
                ],
            },
        }
    return by_planner


def main() -> None:
    if os.environ.get("RUN_SIMULATOR_TESTS", "").lower() != "true":
        print(
            "Skipped: set RUN_SIMULATOR_TESTS=true to run this benchmark "
            "(it launches a real AI2-THOR/Unity subprocess per episode)."
        )
        sys.exit(0)

    tasks = load_tasks()
    all_results: List[BenchmarkEpisodeResult] = []
    for planner_name, planner_factory in PLANNERS.items():
        planner = planner_factory()
        for bt in tasks:
            if planner_name == "react":
                result = run_react_episode(planner, bt)
            else:
                result = run_episode(planner_name, planner, bt)
            all_results.append(result)
            status = "GOAL_OK" if result.goal_success else "GOAL_FAIL"
            retries = (
                f" retries={result.llm_retry_attempts}"
                if result.llm_retry_attempts
                else ""
            )
            grounded = ""
            if result.goal_success_exists_in_scene is not None:
                perceived = (
                    "?"
                    if result.goal_success_perceived_by_agent is None
                    else str(result.goal_success_perceived_by_agent)
                )
                grounded = (
                    f" [exists={result.goal_success_exists_in_scene} "
                    f"perceived={perceived}]"
                )
            print(
                f"[{planner_name:>13}] [{bt.scene:>12}] {bt.task_id:<22} "
                f"{status:<9} exec={'OK' if result.execution_success else 'FAIL'} "
                f"({result.wall_clock_ms:.0f}ms){retries}{grounded}"
                + (f"  cause={result.failure_cause}" if result.failure_cause else "")
            )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"milo_benchmark_{timestamp}.json"
    csv_path = RESULTS_DIR / f"milo_benchmark_{timestamp}_episodes.csv"

    episodes = [asdict(r) for r in all_results]
    react_results = [r for r in all_results if r.planner == "react"]
    report = {
        "reproducibility": {
            "generated_at_utc": timestamp,
            "dataset": "milo_benchmark v1.0",
            "simulator": "Simulator (real AI2-THOR/Unity, restarted between episodes)",
            "planners": list(PLANNERS.keys()),
            "react_llm_provider": REACT_LLM_PROVIDER,
            "react_llm_model": REACT_MODEL_VERSION,
            "react_transient_retry_policy": {
                "max_extra_attempts": REACT_MAX_TRANSIENT_RETRIES,
                "retry_trigger_markers": list(_TRANSIENT_LLM_ERROR_MARKERS),
                "episodes_that_needed_a_retry": sum(
                    1 for r in react_results if r.llm_retry_attempts > 0
                ),
                "total_extra_attempts_used": sum(
                    r.llm_retry_attempts for r in react_results
                ),
                "episodes_still_failing_after_all_retries": sum(
                    1
                    for r in react_results
                    if not r.plan_success
                    and r.llm_retry_attempts >= REACT_MAX_TRANSIENT_RETRIES
                ),
            },
            "memory_enabled": False,
        },
        "summary_by_planner": _summarize(all_results),
        "episodes": episodes,
        "totals": {
            "total_episodes": len(all_results),
            "goal_succeeded": sum(1 for r in all_results if r.goal_success),
            "execution_succeeded": sum(1 for r in all_results if r.execution_success),
        },
    }

    json_path.write_text(json.dumps(report, indent=2, default=str))
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(episodes[0].keys()))
        writer.writeheader()
        writer.writerows(episodes)

    print()
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(json.dumps(report["summary_by_planner"], indent=2))


if __name__ == "__main__":
    main()
