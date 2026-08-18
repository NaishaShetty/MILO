"""
app.py -- MILO Benchmark Companion (Gradio Space)

A static replay of real benchmark results already published to
huggingface.co/datasets/naishashetty/milo_benchmark. There is no live
AI2-THOR/Unity execution here -- see README.md for why (AI2-THOR needs a
real GPU-backed Unity process; HF Spaces' free CPU tier can't run it).
Everything rendered below is loaded from a results JSON produced by a
real run of this project's benchmark runner
(`backend/planning_evaluation/run_benchmark.py`) against real AI2-THOR
scenes -- see data.py / episodes.py for exactly what's logged data vs.
illustrative reconstruction.
"""

from __future__ import annotations

import os

import gradio as gr

from data import (
    LEADERBOARD_COLUMNS,
    LEADERBOARD_HEADERS,
    build_leaderboard_rows,
    load_benchmark_data,
)
from episodes import build_episode_displays

SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")

DATA = load_benchmark_data()
LEADERBOARD_ROWS = build_leaderboard_rows(DATA)
EPISODE_DISPLAYS = build_episode_displays(DATA)
EPISODE_CHOICES = [ep.title for ep in EPISODE_DISPLAYS]
EPISODE_BY_TITLE = {ep.title: ep for ep in EPISODE_DISPLAYS}


def leaderboard_table():
    rows = [[row.get(col, "—") for col in LEADERBOARD_COLUMNS] for row in LEADERBOARD_ROWS]
    headers = [LEADERBOARD_HEADERS[c] for c in LEADERBOARD_COLUMNS]
    return rows, headers


def source_caption() -> str:
    repro = DATA.reproducibility
    react_model = repro.get("react_llm_model", "unknown")
    react_provider = repro.get("react_llm_provider", "unknown")
    return (
        f"Source: `{DATA.source_filename}` — {repro.get('simulator', 'unknown simulator')}, "
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


def render_episode(title: str):
    ep = EPISODE_BY_TITLE.get(title)
    if ep is None:
        return "No episode selected.", "", []

    outcome_line = (
        f"**Outcome**: goal_success=`{ep.goal_success}`, execution_success=`{ep.execution_success}`, "
        f"plan_success=`{ep.plan_success}`"
    )
    failure_line = f"\n**Failure cause (logged)**: {ep.failure_cause}" if ep.failure_cause else ""
    retry_line = (
        f"\n**LLM retry attempts (logged)**: {ep.llm_retry_attempts}"
        if ep.planner == "react"
        else ""
    )

    md = f"""
### {ep.instruction}

**Why this episode was picked**: {ep.reason_picked}

**Planner / model**: {ep.model_label}
**Scene**: {ep.scene} ({ep.room_type}) | **Tier**: {ep.difficulty_tier}
**Task spec (logged)**: goal=`{ep.goal}`, object=`{ep.object_}`, target=`{ep.target}`
**Task ID**: `{ep.task_id}`

{outcome_line}{failure_line}{retry_line}
**Wall-clock time (logged)**: {ep.wall_clock_ms:.0f} ms

---

#### Reconstructed plan trace *(illustration only — not a literal log)*

The source results JSON records aggregate counts per episode
(`action_count`, `plan_step_count`), not a literal per-step action log.
The steps below are reconstructed from this task's `goal`/`object`/`target`
and this project's documented, deterministic planner behavior (see the
Space README and `phase_e_milo_benchmark_report.md`) — they illustrate the
*shape* of what ran, not a captured trace.

```
{os.linesep.join(ep.plan_trace)}
```
"""
    if ep.screenshots:
        shot_note = (
            "**Screenshots below are generic, illustrative product UI captures** from "
            "`docs/screenshots/demo/` in the origin repository — a single walkthrough, not "
            "per-episode captures. They are shown alongside this episode as an example of what "
            "the live UI looks like during an instruction/task-in-progress/task-complete flow, "
            "**not** a screenshot of this literal episode's run."
        )
    else:
        shot_note = ""
    gallery = [os.path.join(SCREENSHOT_DIR, f) for f in ep.screenshots]
    return md, shot_note, gallery


with gr.Blocks(title="MILO Benchmark Companion") as demo:
    gr.Markdown(
        """
# MILO Benchmark Companion

A read-only, pre-recorded companion to
[`naishashetty/milo_benchmark`](https://huggingface.co/datasets/naishashetty/milo_benchmark)
on the Hugging Face Hub. Everything on this page is loaded from a real
benchmark results JSON produced by a real run against real AI2-THOR
scenes — **there is no live simulator running behind this page.**
AI2-THOR needs a GPU-backed Unity process it cannot run on HF Spaces'
free CPU tier, which is exactly why this is a static replay rather than
an interactive demo. See the README tab / repo README for full detail.
        """
    )

    with gr.Tab("Leaderboard"):
        rows, headers = leaderboard_table()
        gr.Dataframe(
            value=rows,
            headers=headers,
            interactive=False,
            wrap=True,
        )
        gr.Markdown(source_caption())
        gr.Markdown(
            "Methodology: `goal_success` checks live post-execution AI2-THOR object state "
            "(`check_goal_live()`), not just \"did every step dispatch without error\" "
            "(`execution_success`). Full predicate table in "
            "`backend/planning_evaluation/dataset/v1.0/README.md` and "
            "`backend/planning_evaluation/live_state.py` in the origin repository. "
            "`tier1_locate`'s live predicate only checks that an object of the named type "
            "exists in the scene — a known, documented simplification, not a perception check."
        )

    with gr.Tab("Episode replay"):
        gr.Markdown(
            "A handful of real, logged episodes — at least one success per planner, plus the "
            "known still-failing `FloorPlan301` book→drawer geometry-limit case. Pick one below."
        )
        dropdown = gr.Dropdown(choices=EPISODE_CHOICES, value=EPISODE_CHOICES[0], label="Episode")
        detail_md = gr.Markdown()
        shot_note_md = gr.Markdown()
        gallery = gr.Gallery(label="Illustrative product screenshots (see caption)", columns=3)
        dropdown.change(fn=render_episode, inputs=dropdown, outputs=[detail_md, shot_note_md, gallery])
        demo.load(fn=render_episode, inputs=dropdown, outputs=[detail_md, shot_note_md, gallery])

    with gr.Tab("About"):
        gr.Markdown(
            """
This Space is a companion to the
[`naishashetty/milo_benchmark`](https://huggingface.co/datasets/naishashetty/milo_benchmark)
dataset and the
[MILO vision-language-robotics project](https://github.com/NaishaShetty/MILO)
(origin repository). It shows real, already-computed benchmark results
for three planners (`rule_based`, `behavior_tree`, `react` on a local
`qwen2.5:7b` model via Ollama) against a fixed 25-task, 5-scene, 3-tier
AI2-THOR benchmark.

**Why not a live demo?** AI2-THOR requires a GPU-backed Unity process.
HF Spaces' free CPU tier has neither a GPU nor Unity, so live execution
is not possible here — this Space intentionally does not pretend
otherwise. What you see is a static replay of one specific, timestamped,
reproducible run's output (see the leaderboard's source caption for
exactly which file).

Full methodology, honesty notes about known predicate limitations, and
this project's benchmark report are linked from the Space README.
            """
        )


if __name__ == "__main__":
    demo.launch()
