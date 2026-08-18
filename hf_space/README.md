---
title: MILO Benchmark Companion
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: static
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
scene. **HF Spaces' free tier has no GPU and cannot run Unity**, so this
Space cannot execute a real episode interactively, full stop. Rather than
fake it (e.g. replaying a canned animation and implying it's live), this
Space is explicit about being a **static replay** of one specific,
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

## Why static HTML, not Gradio

This Space started as a Gradio `Blocks` app (a `Dataframe` for the
leaderboard plus a dropdown-driven detail view) — a small, well-trodden
pattern for exactly this "table + browsable detail" shape. It was
rebuilt as static HTML/CSS/JS after discovering that **Gradio and Docker
Spaces require an HF Pro subscription for CPU hosting on this account**;
static Spaces are free. Nothing about the page's actual content or logic
needed the change: everything here was already precomputed from a
results JSON with no live Python execution per request, so a static page
loses nothing over the Gradio version for this use case — it swaps a
server-rendered `Dataframe`/`Dropdown` for the equivalent plain
HTML table and `<select>`, both populated from the same data at
page-load via `fetch("data.json")`.

## How the static site is built

Nothing here is hand-authored data — `data.json` (what `script.js`
fetches) is generated ahead of time by `generate_data.py`, which reuses
`data.py`/`episodes.py`'s exact loading, leaderboard-row, and
plan-trace-reconstruction logic unchanged (only the output target
changed, from an in-process Gradio render to a JSON file). Regenerate it
with:

```bash
python3 generate_data.py
```

whenever a newer `results/milo_benchmark_*.json` lands (see "Data
source" below) — then commit and redeploy. `index.html`/`style.css`/
`script.js` never need to change for a data refresh alone.

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

If the origin repository produces a newer full run (for example, the
perception-grounded `tier1_locate` check and LLM call/token
instrumentation for `react` landed in the origin repo's
`experiments/results/milo_benchmark_20260818T085629Z.json` after this
Space was first built), copy that JSON into `results/`, re-run
`generate_data.py`, and redeploy. The leaderboard code path is written
defensively for this: if a source JSON lacks a given column (e.g.
`react`'s LLM-call or token counts), that column renders as `—` instead
of crashing or silently showing a fabricated `0`.

## Methodology (matches the published dataset card)

`goal_success` is the primary score: it checks **live** post-execution
AI2-THOR object state (`check_goal_live()` in
`backend/planning_evaluation/live_state.py`), not just "did every
planned action dispatch without an error" (`execution_success` — a
weaker, separate signal, also shown). Full predicate table and known
limitations (including the honest caveat that `tier1_locate`'s live
check only verifies an object of the named type exists in the scene, not
that it was actually perceived — and the separate, additive
`perceived_by_agent` signal that now measures that too) are in
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

No server, no dependencies beyond Python (only needed to regenerate
`data.json`, not to view the page):

```bash
python3 -m http.server 8080
```

then open `http://127.0.0.1:8080`. No GPU, no AI2-THOR, no network
access required — everything renders from `data.json` and the images in
`screenshots/`.

## Files

```
hf_space/
├── index.html          # page markup: leaderboard / episode replay / about tabs
├── style.css            # styling (light + dark, no build step)
├── script.js             # fetches data.json, renders the leaderboard table and episode detail view
├── data.json              # generated by generate_data.py -- the only thing script.js fetches
├── generate_data.py        # build step: re-derives data.json from results/*.json (not served/run by the Space itself)
├── data.py                  # results JSON loader + leaderboard row builder (defensive re: optional columns) -- used by generate_data.py
├── episodes.py                # curated episode picks + reconstructed-plan-trace builder (clearly labeled) -- used by generate_data.py
├── README.md                   # this file (HF Space card)
├── results/
│   ├── milo_benchmark_20260817T154347Z.json   # react/Gemini run (quota-limited, kept for record)
│   └── milo_benchmark_20260818T070841Z.json   # react/qwen2.5:7b run (the one currently loaded)
└── screenshots/
    ├── live-01-instruction-typed.png
    ├── live-02-task-in-progress.png
    └── live-03-task-complete.png
```

## Status of this Space

Built and verified locally (served via `python3 -m http.server`,
confirmed the page loads, the leaderboard renders real data, and episode
replay works with no console errors) and live on the Hugging Face Hub —
see the top of the origin repository's README for the live URL.
