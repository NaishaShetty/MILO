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
| rule-based | 100% | 0% | 48% | 7.78 | 11.67 | 0.144 |
| ReAct | 100% | 0% | 48% | 7.78 | 11.67 | 0.144 |
| behaviour tree | 100% | 0% | 48% | 5.58 | 9.05 | 0.144 |
| HTN | 100% | 0% | 48% | 5.58 | 9.05 | 0.144 |
| language model (reference plans) | not run | 100% | not run | 5.25 | 9.38 | 0 |

Recovery by fault kind (all four classical planners are identical):

| Blocked path | Out of reach | Stuck door | Timeout | Wrong detection | Missing object |
|---|---|---|---|---|---|
| 100% | 22% | 100% | 100% | 4% | 0% |

What each part is worth (rule-based on known + fault cases; the novel planner on a second pass over the new tasks):

| Variant | Known + faults | New tasks, 2nd pass | Model calls per task |
|---|---|---|---|
| everything on | 57% | 100% | 0 |
| no memory | 57% | | |
| no reflection (first failure ends the mission) | 21% | | |
| no replanning | 21% | | |
| no skills | | 100% | 1 |

**Read honestly:**
- **ReAct is identical to rule-based here.** With no language model configured it falls back to the rule-based planner, by design.
- **Memory is worth nothing on this suite.** Every object is in view, so remembered locations change nothing.
- **Reflection and replanning are worth 36 points under faults** (57% vs 21%).
- **Skills don't change success** with reference plans, but they remove the model call entirely on repeat tasks.
- **Two fault kinds are barely recovered within a mission:**
  - Wrong detection (4%): replanning doesn't add a look-around. Failure memory (Phase 5) only helps on the *next* mission.
  - Out of reach (22%).
- A missing object can't be recovered, as expected.

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
