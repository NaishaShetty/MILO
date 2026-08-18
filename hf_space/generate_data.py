"""
generate_data.py -- builds data.json, the single data file the static
Space (index.html/script.js) fetches at page-load.

Why a build step instead of a server: HF's free tier only offers a
`static`-SDK Space without HF Pro (Gradio/Docker Spaces need Pro -- see
the README's "Why static, not Gradio" note). A static Space has no
Python runtime at all, so the leaderboard/episode-replay logic that used
to run per-request in app.py/data.py/episodes.py has to run once, ahead
of time, and its output has to be a plain file the browser can fetch.
This script is that one-time step -- it is not part of the deployed
Space (nothing on HF's infrastructure ever executes it), it is run
locally/in CI before committing data.json, exactly like a static site
generator's build step.

Reuses `data.py`/`episodes.py`'s exact loading/leaderboard/episode-trace
logic unchanged (same source-of-truth results JSON, same reconstructed-
trace honesty notes) -- only the *output* target changes, from an
in-process Gradio render to a JSON file.

Run: `python3 generate_data.py` from this directory. Re-run and commit
the new data.json whenever a newer results/milo_benchmark_*.json lands.
"""

from __future__ import annotations

import json
import os

from data import (
    LEADERBOARD_COLUMNS,
    LEADERBOARD_HEADERS,
    build_leaderboard_rows,
    load_benchmark_data,
)
from episodes import build_episode_displays

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")


def _source_caption(data) -> str:
    repro = data.reproducibility
    react_model = repro.get("react_llm_model", "unknown")
    react_provider = repro.get("react_llm_provider", "unknown")
    return (
        f"Source: `{data.source_filename}` — {repro.get('simulator', 'unknown simulator')}, "
        f"planners: {', '.join(repro.get('planners', []))}. "
        f"`react` model: `{react_model}` via `{react_provider}`"
        + (
            " (local Ollama, no external quota)."
            if react_provider == "qwen"
            else f" ({react_provider})."
        )
        + " `n/a` = not applicable to this planner (no LLM involved). "
        "`—` = field not present in this source JSON (older runs don't have every column; "
        "the loader renders what's available rather than guessing)."
    )


def main() -> None:
    data = load_benchmark_data()
    rows = build_leaderboard_rows(data)
    episodes = build_episode_displays(data)

    payload = {
        "source_filename": data.source_filename,
        "leaderboard_columns": LEADERBOARD_COLUMNS,
        "leaderboard_headers": LEADERBOARD_HEADERS,
        "leaderboard_rows": rows,
        "source_caption": _source_caption(data),
        "episodes": [
            {
                "title": ep.title,
                "planner": ep.planner,
                "task_id": ep.task_id,
                "reason_picked": ep.reason_picked,
                "scene": ep.scene,
                "room_type": ep.room_type,
                "difficulty_tier": ep.difficulty_tier,
                "instruction": ep.instruction,
                "goal": ep.goal,
                "object": ep.object_,
                "target": ep.target,
                "plan_success": ep.plan_success,
                "execution_success": ep.execution_success,
                "goal_success": ep.goal_success,
                "wall_clock_ms": ep.wall_clock_ms,
                "failure_cause": ep.failure_cause,
                "llm_retry_attempts": ep.llm_retry_attempts,
                "model_label": ep.model_label,
                "plan_trace": ep.plan_trace,
                "screenshots": ep.screenshots,
            }
            for ep in episodes
        ],
    }

    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {OUT_PATH} ({len(payload['episodes'])} episodes, {len(rows)} leaderboard rows)")


if __name__ == "__main__":
    main()
