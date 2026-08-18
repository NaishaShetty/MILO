---
title: MILO Benchmark Companion
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 6.24.0
app_file: app.py
pinned: false
license: mit
---

# MILO Benchmark Companion

A read-only companion demo to
[`naishashetty/milo_benchmark`](https://huggingface.co/datasets/naishashetty/milo_benchmark)
on the Hugging Face Hub, and to the
[MILO vision-language-robotics project](https://github.com/NaishaShetty/MILO)
(origin repository). It shows a **leaderboard** and an **episode replay
browser** built entirely from a real benchmark results JSON — three
planners (`rule_based`, `behavior_tree`, `react` on a local `qwen2.5:7b`
model via Ollama) scored against a fixed 25-task, 5-scene, 3-tier AI2-THOR
benchmark.

## This is not a live demo, and that's deliberate

AI2-THOR requires a GPU-backed Unity subprocess to actually simulate a
scene. **HF Spaces' free CPU tier has no GPU and cannot run Unity**, so
this Space cannot execute a real episode interactively, full stop. Rather
than fake it (e.g. replaying a canned animation and implying it's live),
this Space is explicit about being a **static replay** of one specific,
timestamped, already-completed, reproducible benchmark run. If you want
to run the benchmark for real, clone the origin repository and run
`backend/planning_evaluation/run_benchmark.py` yourself against a real
AI2-THOR installation (needs a GPU).

## What's real vs. reconstructed here

This project's own writing convention (see
`experiments/reports/phase_e_milo_benchmark_report.md` in the origin
repo) is to say plainly what's measured vs. illustrative. Applied here:

- **Leaderboard numbers**: real. Read directly from the source results
  JSON's `summary_by_planner` block (never re-derived from `episodes`,
  except for a couple of cost/latency columns not present in
  `summary_by_planner` at all, which are averaged from `episodes`
  instead — see `data.py`).
- **Episode replay's logged fields** (planner, scene, instruction,
  goal/object/target, tier, plan_success/execution_success/goal_success,
  wall_clock_ms, failure_cause, llm_retry_attempts): real, read directly
  from that episode's row in the source JSON.
- **Episode replay's "reconstructed plan trace"**: **not** real logged
  data. The source JSON only has aggregate per-episode counts
  (`action_count`, `plan_step_count`) — there is no literal per-step
  action log to replay. The step lists shown are built from each task's
  `goal`/`object`/`target` plus this project's documented, deterministic
  planner behavior (`tier3_store` = locate → navigate → pick_up →
  navigate → open if openable → place → close if opened, per
  `_deposit()`'s documented behavior in the dataset README and benchmark
  report). Every trace is labeled **"reconstructed plan trace for
  illustration"** in the UI. We chose to build these (rather than the
  simpler, arguably more conservative option of only showing logged
  fields) because a bare goal/object/target/outcome table alone doesn't
  give a reader unfamiliar with the codebase any sense of what a
  planner's "shape" of behavior actually looks like — but we did not want
  to under-label them as real trace data, since they aren't.
- **Screenshots**: real UI screenshots from the live MILO product
  (`docs/screenshots/demo/` in the origin repo — 3 generic images:
  instruction typed, task in progress, task complete), **not** captured
  per-episode. There is no screenshot for each of the 25 dataset tasks.
  Where shown alongside an episode, the caption says explicitly that it's
  an illustrative example of the UI, not a capture of that literal
  episode's run.

## Why Gradio, not static HTML or Streamlit

A `Dataframe` for the leaderboard plus a dropdown-driven detail view for
episode replay is a small, well-trodden Gradio `Blocks` pattern, and
Gradio Spaces on the free CPU tier are the simplest, most common path for
exactly this shape of "table + browsable detail" demo — no separate
frontend build step, and Python end-to-end matches the rest of this
project. Static HTML+JS was also seriously considered (and would have
worked, avoiding a Python runtime dependency entirely) but was passed
over only because Gradio's `Dataframe`/`Gallery`/`Dropdown` widgets get
the same result with less hand-rolled layout code.

## Data source and how it stays current

`data.py`'s loader does **not** hardcode a filename — it globs
`results/milo_benchmark_*.json` (excluding `*_memory_ablation_*.json`,
a different experiment) and picks the lexicographically-latest
`generated_at_utc`-stamped filename. `results/` currently ships two real
runs from the origin repo's `experiments/results/`:

- `milo_benchmark_20260817T154347Z.json` — `react` run against Gemini's
  free tier, which hit a 20-request/day quota after 2 of 25 episodes.
  Kept here for the record, but its `react` numbers are **not** a valid
  capability baseline (see the origin repo's benchmark report, Addendum
  2, for exactly why the raw success rate from that run is misleading).
- `milo_benchmark_20260818T070841Z.json` — `react` run against a local
  `qwen2.5:7b` (Ollama), zero external quota dependency, a clean 25/25
  completed run. **This is the file the leaderboard above actually
  loads**, since it's the newer of the two.

If the origin repository produces a newer full run (for example, a
re-run adding a perception-grounded `tier1_locate` check or LLM
call/token instrumentation for `react` — both were in progress and not
yet in either file above at the time this Space was built), copy that
JSON into `results/` and redeploy; no code change is required. The
leaderboard code path is written defensively for this: if a source JSON
lacks a given column (e.g. `react`'s LLM-call or token counts), that
column renders as `—` instead of crashing or silently showing a
fabricated `0`.

## Methodology (matches the published dataset card)

`goal_success` is the primary score: it checks **live** post-execution
AI2-THOR object state (`check_goal_live()` in
`backend/planning_evaluation/live_state.py`), not just "did every
planned action dispatch without an error" (`execution_success` — a
weaker, separate signal, also shown). Full predicate table and known
limitations (including the honest caveat that `tier1_locate`'s live
check only verifies an object of the named type exists in the scene, not
that it was actually perceived) are in
`backend/planning_evaluation/dataset/v1.0/README.md` in the origin
repository — read that file for the canonical methodology text; this
Space's copy is a summary, not a re-derivation.

## Links

- Dataset: [huggingface.co/datasets/naishashetty/milo_benchmark](https://huggingface.co/datasets/naishashetty/milo_benchmark)
- Origin repository: [github.com/NaishaShetty/MILO](https://github.com/NaishaShetty/MILO)
- Full benchmark report (methodology, all three planners' real numbers,
  every caveat this README summarizes): `experiments/reports/phase_e_milo_benchmark_report.md`
  in the origin repository.

## Running locally

```bash
pip install -r requirements.txt
python app.py
```

Opens a local Gradio server (default `http://127.0.0.1:7860`). No GPU,
no AI2-THOR, no network access required — everything renders from the
JSON files in `results/` and the images in `screenshots/`.

## Files

```
hf_space/
├── app.py            # Gradio Blocks app: leaderboard + episode replay + about tab
├── data.py            # results JSON loader + leaderboard row builder (defensive re: optional columns)
├── episodes.py         # curated episode picks + reconstructed-plan-trace builder (clearly labeled)
├── requirements.txt
├── README.md           # this file (HF Space card)
├── results/
│   ├── milo_benchmark_20260817T154347Z.json   # react/Gemini run (quota-limited, kept for record)
│   └── milo_benchmark_20260818T070841Z.json   # react/qwen2.5:7b run (the one currently loaded)
└── screenshots/
    ├── live-01-instruction-typed.png
    ├── live-02-task-in-progress.png
    └── live-03-task-complete.png
```

## Status of this Space

Built and verified locally (`python app.py`, confirmed the Gradio server
starts and serves the leaderboard and episode data with no errors). **Not
pushed to the Hugging Face Hub** — this directory is a local, reviewable
build; publishing (via `huggingface_hub` or `huggingface-cli`) is a
separate, deliberate step not taken here.
