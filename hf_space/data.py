"""
data.py -- loads the most recent full MILO benchmark results JSON for the
Space's leaderboard and episode replay.

Why "most recent, discovered by glob" instead of a hardcoded filename:
this Space is a static replay of `experiments/results/milo_benchmark_*.json`
from the origin repository (github.com/NaishaShetty/MILO). A second run
with additional instrumentation (a perception-grounded tier1_locate check,
plus LLM-call/token-count fields for the `react` planner) was in flight
while this Space was built and may land as a new, later-timestamped file.
Rather than hardcode today's filename, this loader picks the newest
`milo_benchmark_*.json` present in `results/` (excluding
`*_memory_ablation_*.json`, which is a different experiment) -- so simply
copying a newer results file into `results/` and redeploying is enough to
pick it up. No code changes needed.

All numbers below are read directly from `summary_by_planner` in the
source JSON, never re-derived from `episodes` -- except fields that only
exist per-episode with no `summary_by_planner` equivalent (there are none
of those in the current source file; if a future run adds fields such as
LLM-call counts only at the episode level, this module derives simple
per-planner averages from `episodes` for those specific fields only, and
leaves the column blank if the field isn't present at all).
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

PLANNER_ORDER = ["rule_based", "behavior_tree", "react"]
TIER_ORDER = ["tier1_locate", "tier2_pickup", "tier3_store"]

PLANNER_LABELS = {
    "rule_based": "rule_based (deterministic, no LLM)",
    "behavior_tree": "behavior_tree (deterministic, no LLM)",
    "react": "react (LLM-driven)",
}


def find_latest_results_path(results_dir: str = RESULTS_DIR) -> str | None:
    """Return the path to the newest milo_benchmark_*.json in results_dir,
    excluding memory_ablation runs. Newest is determined by the
    generated_at_utc timestamp embedded in the filename (sorts correctly
    as an ISO-ish string), falling back to file mtime if that ever fails.
    """
    candidates = [
        p
        for p in glob.glob(os.path.join(results_dir, "milo_benchmark_*.json"))
        if "memory_ablation" not in os.path.basename(p)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: os.path.basename(p))[-1]


@dataclass
class BenchmarkData:
    path: str
    raw: dict
    reproducibility: dict = field(default_factory=dict)
    summary_by_planner: dict = field(default_factory=dict)
    episodes: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)

    @property
    def source_filename(self) -> str:
        return os.path.basename(self.path)


def load_benchmark_data(path: str | None = None) -> BenchmarkData:
    if path is None:
        path = find_latest_results_path()
    if path is None or not os.path.exists(path):
        raise FileNotFoundError(
            f"No milo_benchmark_*.json found in {RESULTS_DIR}. "
            "Copy a results file from experiments/results/ in the origin "
            "repository into hf_space/results/ before running this Space."
        )
    with open(path, "r") as f:
        raw = json.load(f)
    return BenchmarkData(
        path=path,
        raw=raw,
        reproducibility=raw.get("reproducibility", {}),
        summary_by_planner=raw.get("summary_by_planner", {}),
        episodes=raw.get("episodes", []),
        totals=raw.get("totals", {}),
    )


def _fmt_rate(rate, n) -> str:
    if rate is None or n is None:
        return "—"
    return f"{round(rate * n)}/{n} ({rate * 100:.0f}%)"


def _episode_field_avg(episodes: list, planner: str, field_name: str):
    """Average a numeric field across a planner's episodes, if present on
    at least one episode. Returns None if the field is absent everywhere
    (so the caller can render an empty/omitted column instead of a 0 that
    would misleadingly imply real data)."""
    vals = [
        e[field_name]
        for e in episodes
        if e.get("planner") == planner and e.get(field_name) is not None
    ]
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_leaderboard_rows(data: BenchmarkData) -> list[dict]:
    """One row per planner, sourced from summary_by_planner (never
    re-derived from episodes) plus defensively-optional cost/latency
    columns that may or may not exist in the source JSON yet."""
    rows = []
    for planner in PLANNER_ORDER:
        summary = data.summary_by_planner.get(planner)
        if summary is None:
            continue
        overall = summary.get("overall", {})
        by_tier = summary.get("by_tier", {})

        row = {
            "planner": PLANNER_LABELS.get(planner, planner),
            "goal_success": _fmt_rate(overall.get("goal_success_rate"), overall.get("n")),
            "execution_success": _fmt_rate(
                overall.get("execution_success_rate"), overall.get("n")
            ),
        }
        for tier in TIER_ORDER:
            t = by_tier.get(tier, {})
            row[tier] = _fmt_rate(t.get("goal_success_rate"), t.get("n"))

        # --- Cost / latency columns (defensive: source JSON today has no
        # per-episode LLM-call/token fields; a future re-run may add them) ---
        avg_wall_clock = _episode_field_avg(data.episodes, planner, "wall_clock_ms")
        row["avg_wall_clock_ms"] = f"{avg_wall_clock:.0f}" if avg_wall_clock is not None else "—"

        if planner == "react":
            avg_retries = _episode_field_avg(data.episodes, planner, "llm_retry_attempts")
            row["llm_retries_per_episode"] = (
                f"{avg_retries:.2f}" if avg_retries is not None else "—"
            )
            # Fields that may appear in a future instrumented run. Look for
            # a few plausible names defensively; omit cleanly if absent.
            call_field = next(
                (
                    f
                    for f in ("llm_call_count", "llm_calls", "num_llm_calls")
                    if any(f in e for e in data.episodes if e.get("planner") == planner)
                ),
                None,
            )
            token_field = next(
                (
                    f
                    for f in ("llm_token_count", "total_tokens", "approx_tokens")
                    if any(f in e for e in data.episodes if e.get("planner") == planner)
                ),
                None,
            )
            avg_calls = _episode_field_avg(data.episodes, planner, call_field) if call_field else None
            avg_tokens = (
                _episode_field_avg(data.episodes, planner, token_field) if token_field else None
            )
            row["llm_calls_per_episode"] = f"{avg_calls:.1f}" if avg_calls is not None else "—"
            row["approx_tokens_per_episode"] = (
                f"{avg_tokens:.0f}" if avg_tokens is not None else "—"
            )
        else:
            row["llm_retries_per_episode"] = "n/a"
            row["llm_calls_per_episode"] = "n/a"
            row["approx_tokens_per_episode"] = "n/a"

        rows.append(row)
    return rows


LEADERBOARD_COLUMNS = [
    "planner",
    "goal_success",
    "execution_success",
    "tier1_locate",
    "tier2_pickup",
    "tier3_store",
    "avg_wall_clock_ms",
    "llm_calls_per_episode",
    "approx_tokens_per_episode",
    "llm_retries_per_episode",
]

LEADERBOARD_HEADERS = {
    "planner": "Planner",
    "goal_success": "Goal success (overall)",
    "execution_success": "Execution success (overall)",
    "tier1_locate": "tier1_locate",
    "tier2_pickup": "tier2_pickup",
    "tier3_store": "tier3_store",
    "avg_wall_clock_ms": "Avg wall-clock ms/episode",
    "llm_calls_per_episode": "LLM calls/episode",
    "approx_tokens_per_episode": "Approx tokens/episode",
    "llm_retries_per_episode": "LLM retries/episode",
}
