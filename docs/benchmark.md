# Benchmark, ablations, fault recovery and CI (roadmap 2, Phase 6)

Code: `backend/benchmark/` (`suite.py`, `run.py`, `ci.py`). Results: `benchmarks/latest.{json,md}`, with one line per run in `benchmarks/history.jsonl`. UI: **Leaderboard** in the gear menu.

```
make benchmark        # full suite, every planner, ablations, fault recovery (about 10 s)
make benchmark-ci     # the CI gate: fast subset vs benchmarks/ci_baseline.json
```

## The suite

A fixed synthetic home with fixed tasks, faults and seeds, so repeated runs give identical numbers (a test checks this). A mission counts only if it ends "succeeded" **and** the world-state goal checks pass (`MILO_GOAL_CHECK=enforce` for the run).

- **Known tasks:** 23 task-library missions (fetch, place, store, open, switch on/off, find).
- **New tasks:** 8 commands with no recipe ("chill the apple", "make the room dark"...).
- **Faults:** each known task again under each injected fault that happens once and then clears: blocked path, out of reach, stuck door, timeout, wrong detection, missing object.
- **Planners:** rule-based, ReAct, behaviour tree, HTN, and the language-model ("novel") planner. Without credentials the language-model planner uses the reference plans of the novel-task benchmark and runs on the new tasks only; `--provider claude` uses the real model on everything.

## Results (`benchmarks/latest.md`; every run is also a dated line in `benchmarks/history.jsonl`)

| Planner | Known | New tasks | Under faults | Steps | Sim time (s) | Replans |
|---|---|---|---|---|---|---|
| rule-based | 100% | 0% | 78% | 7.52 | 12.5 | 0.144 |
| ReAct, qwen2.5:7b via Ollama ¹ | 100% | 0% | 80% | 7.39 | 10.66 | 0.124 |
| behaviour tree | 100% | 0% | 78% | 5.63 | 9.88 | 0.144 |
| HTN | 100% | 0% | 78% | 5.63 | 9.88 | 0.144 |
| language model (reference plans) | not run | 100% | not run | 5.25 | 9.38 | 0 |

- ¹ **ReAct** was measured separately with a local model: `qwen2.5:7b` (Q4_K_M) through
  Ollama, temperature 0, one run, 2026-11-26, 8,694 s (`results/react_local/benchmark.md`).
  1,558 real model calls, 25 transport errors. **Most of its row is not the model.** When the
  model's answer is unusable, or it hits ReAct's 12-step limit, ReAct hands the plan to the
  rule-based planner. That happened in 99 of the 179 cases. Counting only cases the model planned
  on its own:

  | | Known | New tasks | Under faults | memory | memory_synonyms | long | routes |
  |---|---|---|---|---|---|---|---|
  | success, fallback included | 23/23 | 0/8 | 98/122 | 6/8 | 4/8 | 6/6 | 3/4 |
  | model alone | 13/23 | 0/8 | 53/122 | 0/8 | 0/8 | 0/6 | 0/4 |

  The model handles one-step tasks (open, switch on, find something in view) and short fetches.
  It fails on everything with three or more actions, every new task, and every harder-tier case.
  Without a model, `make benchmark` reports ReAct as "not measured" instead of repeating the
  rule-based numbers under its name.
- **Behaviour tree and HTN are identical for a real reason.** Checked plan by plan, all three
  classical planners produce exactly the same first plan for all 23 known tasks. Rule-based
  still executes more steps per mission (5.83 vs 4.43 on known tasks, 8.33 vs 6.23 under
  faults), so the difference arises during execution; the cause has not been traced yet.

Recovery by fault kind (all four classical planners are identical), before → after in-mission recovery:

| Blocked path | Out of reach | Stuck door | Timeout | Wrong detection | Missing object |
|---|---|---|---|---|---|
| 100% | 22% → **100%** | 100% | 100% | 4% → **83%** | 0% |

What each part is worth (rule-based on known + fault cases; the novel planner on a second pass over the new tasks):

| Variant | Known + faults | New tasks, 2nd pass | Model calls per task |
|---|---|---|---|
| everything on | 81% | 100% | 0 |
| no memory | 81% | | |
| no reflection (first failure ends the mission) | 21% | | |
| no replanning | 21% | | |
| no in-mission recovery (`MILO_INMISSION_RECOVERY=0`) | 57% | | |
| no skills | | 100% | 1 |

**Read honestly:**
- **ReAct with a local 7B model is mostly rule-based underneath** (see ¹ above): its own plans succeed on 13 of 23 known tasks and on none of the new ones.
- **Memory is worth nothing on this tier.** Every object is in view, so remembered locations change nothing. The memory tier below is where it counts.
- **Reflection and replanning are worth 60 points under faults** (81% vs 21%). Without the in-mission fixes below they were worth 36 (57% vs 21%).
- **Skills don't change success** with reference plans, but they remove the model call entirely on repeat tasks.
- **In-mission recovery is worth 24 points** (81% vs 57%):
  - **Why it was needed.** A retry re-runs the same plan, and the executor skips steps already marked done. So the `navigate` that left MILO unable to see or reach the object never ran again, and a replan produced the same steps.
  - **What it does now** (`backend/orchestration/recovery.py`). After a "not visible" step failure it inserts `look_around` before the next attempt. After "not reachable" it inserts a fresh `navigate` to the target. A second time for the same step, it looks around and then re-approaches. Each fix is capped at two per step per mission, and `max_replans` still bounds the attempts.
  - **What's still missing.** The remaining wrong-detection failures (4 of 23) are all **find** tasks. There, no step fails: the plan "succeeds", and only the final goal check sees the object isn't visible. Failure memory (Phase 5) still fixes those on the *next* mission.
- A missing object can't be recovered, as expected.

## Harder tiers (2026-11-26, `make benchmark`, synthetic home)

The tasks above stay as the regression tier. Five tiers were added where planners can
genuinely differ (`backend/benchmark/suite.py`):

- **memory** (8 cases): the object starts out of view. It can't be walked to directly, looking around doesn't reveal it, and it appears only when MILO goes to the place it is actually on (`"hidden": True` in `learning/synthetic.py`). MILO's memory holds true facts about where things usually are.
- **memory_synonyms** (8 cases): the same, but each object's place is remembered only under another name ("ceramic mug" for the mug, "hardcover" for the book, "flask" for the bottle). Exact-name lookup finds nothing, so the memory embedder decides.
- **long** (6 cases): two or three goals in one mission, in order, 10 to 20 steps (for example: put the apple in the fridge, switch the light off, then fetch the mug).
- **routes** (4 cases): competing routes. The nearest shelf or table is blocked for good; a second one of the same kind, further away, is clear.
- **impossible** (6 cases, added 2026-11-27): requests nothing in the home can carry out: pick up the fridge, open the apple, switch on the book, put the sofa on the table, store the mug in the apple, fetch a unicorn. Correct means MILO doesn't report success **and** takes no action at all, not even walking over. Ambiguous requests aren't a tier: MILO asks its question in the API before a mission starts, and the benchmark runs missions from structured tasks; they are measured in the [novel-task evaluation](novel_tasks.md).

| Planner | memory | memory_synonyms | long | routes | impossible |
|---|---|---|---|---|---|
| rule-based | 100% | 75% | 100% | 100% | 83% |
| behaviour tree | 0% | 0% | 100% | 100% | 83% |
| HTN | 0% | 0% | 100% | 100% | 83% |
| ReAct, qwen2.5:7b ¹ (fallback included) | 75% | 50% | 100% | 75% | not run |
| ReAct, qwen2.5:7b ¹ (model alone) | 0% | 0% | 0% | 0% | not run |

| Rule-based, ablation | memory | memory_synonyms | long | routes | impossible |
|---|---|---|---|---|---|
| everything on (hashing embedder) | 100% | 75% | 100% | 100% | 83% |
| learned memory embedder | 100% | 88% | 100% | 100% | 83% |
| no memory | **0%** | **0%** | 100% | 100% | 83% |
| no reflection | 100% | 75% | 100% | **0%** | 83% |
| no replanning | 100% | 75% | 100% | **0%** | 83% |
| no in-mission recovery | 100% | 75% | 100% | **0%** | 83% |

ReAct was measured before the impossible tier existed, hence "not run".

What this shows, plainly:

- **Memory shows a clear effect:** 100% with it, 0% without, on the memory tier.
- **The planners separate on memory**, for a structural reason: only the rule-based planner uses remembered locations (`_apply_memory_hint`). The behaviour tree is always built with no memory context, and HTN has no memory-conditioned methods yet.
- **The embedder now matters, modestly.** When nothing is remembered under the object's exact name, the planner compares the names of remembered places' subjects with the object ("ceramic mug" vs "mug") using the memory embedder, and uses a place only if its name is clearly the closest (a per-embedder minimum and a 0.05 margin over the runner-up; otherwise no hint, rather than a wrong place). Hashing finds the 6 paraphrases that share a word with the object; the learned embedder also finds "hardcover" for the book (7 of 8). Neither finds "flask" for the bottle. The thresholds were chosen on a separate probe set ("coffee mug", "paperback", "spud"...) that this tier doesn't reuse.
- **Long missions don't separate the planners.** All three produce the same first plan for every single goal in the suite, and a long mission is those plans in sequence. Adding the tier found a real bug: the end-of-mission goal check required every goal's conditions at once, so "put the apple away, then fetch the mug" failed on the first goal's "hand empty". Only the last goal's condition for each slot (hand, object location, open, switched on) is now checked (`verification.predicates.final_state_predicates`).
- **Competing routes: 0% before, 100% now, for every planner.** Plans name a kind of place ("the shelf") and the executor picks the nearest one, so a replan used to go back to the same blocked shelf. In-mission recovery now treats a second "blocked" failure on the same place as permanent: it marks that instance as blocked and points the rest of the plan at the nearest other one ("Shelf|2"), for the rest of the mission, replans included (`orchestration/recovery.py`). Without in-mission recovery the tier is back to 0%. MILO also remembers the blocked instance (a `path_blocked` observation), so the **next** mission plans around it before acting: in a test with two missions in the same home, the first needed 2 failed attempts and the second none. "On the shelf" now means any shelf in the goal check, unless a specific one is named.
- **Impossible requests used to "succeed" in the synthetic home.** When the tier was added, every classical planner reported success on 5 of the 6: the synthetic simulator let MILO pick up a fridge, open an apple or put a mug "in" an apple, which AI2-THOR refuses. Two fixes (2026-11-27): the simulator now refuses what AI2-THOR refuses, and MILO checks a new plan against what each object in the scene can do before acting, so "pick up the fridge" ends with "I can't pick up the fridge: it can't be picked up" and no action (`backend/planner/affordances.py`, shared by both, so they can't disagree). The tier went from 0% (5 false successes) to **83%**. The one miss is the unicorn: nothing in the scene says it can't be fetched, so MILO looks for it, and the mission fails after 2 steps. No other benchmark number changed: every earlier result was rerun and compared.
- These tiers run in the synthetic home. A real AI2-THOR run of the suite is the next step (`make benchmark-thor`, see `docs/local_model.md`).

## CI

- **Every push** (`.github/workflows/ci.yml`, "Benchmark regression gate") runs the fast slice: every second known task, 4 new tasks, and one fault of each kind. It fails if any planner's success is more than 5 points below `benchmarks/ci_baseline.json`. After an intended change, run `python -m benchmark.ci --write-baseline` and commit the new baseline.
- **Weekly and on demand** (`.github/workflows/benchmark.yml`), the full suite runs and uploads the reports as an artifact.
- `scikit-learn` was added to `backend/requirements.txt`. The learned-model tests (since Phase B) need it, and CI only installs that file.

**The gate catches a broken change.** On a throwaway local branch (`ci-gate-break-test`, since deleted), reflection was deliberately broken so it never retries or replans. The gate printed:

```
REGRESSION: rule_based: success 55% < baseline 68% - 5%
REGRESSION: behavior_tree: success 55% < baseline 68% - 5%
REGRESSION: htn: success 55% < baseline 68% - 5%
benchmark gate: FAILED          (exit code 1)
```

This was run locally with the same command the CI step uses. Nothing was pushed, so the workflow itself hasn't yet run on GitHub's runners.
