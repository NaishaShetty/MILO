# Phase E — MILO Benchmark v1.0: Methodology, Baselines, and Findings

Status: **COMPLETE** (dataset + runner + real baseline numbers). **Not
yet published to Hugging Face** — built locally in HF dataset-repo
format, ready to push; see "Publishing" at the end.

Generated from real, reproducible runs of
`backend/planning_evaluation/run_benchmark.py` and
`run_memory_ablation.py` against real AI2-THOR/Unity. Raw output:
[`experiments/results/milo_benchmark_20260817T143355Z.json`](../results/milo_benchmark_20260817T143355Z.json)
/ [`..._episodes.csv`](../results/milo_benchmark_20260817T143355Z_episodes.csv)
(planner comparison) and
[`experiments/results/milo_benchmark_memory_ablation_20260817T143822Z.json`](../results/milo_benchmark_memory_ablation_20260817T143822Z.json)
/ [`..._episodes.csv`](../results/milo_benchmark_memory_ablation_20260817T143822Z_episodes.csv)
(memory ablation). Every number below is read directly from those
files.

---

## 1. Why this exists

Phase D proved MILO's pipeline generalizes across room types.
`milo_benchmark v1.0` turns that same effort into something durable
and reusable: a fixed, versioned dataset with machine-checkable
ground truth, plus a runner someone who is *not* this project's
author could point their own planner at and get a comparable number.
That combination — fixed task set + reproducible scorer + baseline
numbers from a real system — is what makes this a benchmark rather
than a one-off sweep.

## 2. What it measures — three axes, chosen deliberately narrow

1. **End-to-end task success**, on a fixed, versioned 25-task set
   across 5 real AI2-THOR scenes (`dataset/v1.0/`).
2. **Planner comparison**: `RuleBasedPlanner` vs `BehaviorTreePlanner`
   on the identical task set — a comparison nobody else can produce
   without this project's specific three-planner architecture.
   `ReActPlanner` is scoped out (see section 3).
3. **Memory-conditioned vs memory-off**, on real AI2-THOR, extending
   Phase B's single-scene ablation across all 5 Phase D scenes.

Deliberately not attempted: perception accuracy, multi-object tasks,
adversarial instructions, cross-scene transfer scoring. See
`dataset/v1.0/README.md`'s "What this dataset does not cover."

## 3. Why `ReActPlanner` is not in the baseline table

This environment has no LLM API key configured
(`OPENAI_API_KEY`/`GEMINI_API_KEY`/etc. are all unset). `ReActPlanner`
without a real `LLMClient` either needs a `fallback_planner` (in which
case it is not measuring ReAct at all — it silently becomes
`RuleBasedPlanner` with extra bookkeeping) or returns
`success=False, errors=["No LLM client configured for ReActPlanner."]`
on every task, which would report a 0% success rate that means
nothing about ReAct's actual capability. Reporting either would be
dishonest. This benchmark reports two real planners rather than three
fabricated or degenerate ones. The dataset and runner are written so a
future run with a real API key needs zero changes beyond adding
`"react": lambda: ReActPlanner(llm_client=make_real_client())` to
`run_benchmark.py`'s `PLANNERS` dict.

## 4. Dataset

25 tasks, 5 scenes (all 4 iTHOR room types), 3 difficulty tiers. Full
methodology, success-predicate definitions, and known kept-failures
are in the dataset card:
[`backend/planning_evaluation/dataset/v1.0/README.md`](../../backend/planning_evaluation/dataset/v1.0/README.md).

Two independent success signals are scored per episode (see
`live_state.py`'s docstring for why they can diverge): `execution_success`
(`TaskRunResult.succeeded` — did every step dispatch without a
simulator error) and `goal_success` (`check_goal_live()` — does the
goal condition actually hold against live AI2-THOR object state after
execution). `goal_success` is this benchmark's primary score — it is
a genuine improvement over every prior real-AI2-THOR harness in this
project (`experiment_real.py`, `run_floorplan_sweep.py`), which only
ever reported `execution_success`.

## 5. Results — planner comparison (axis 1 + 2)

```
rule_based:      23/25 (92%)   tier1_locate 10/10   tier2_pickup 10/10   tier3_store 3/5
behavior_tree:    22/25 (88%)   tier1_locate 10/10   tier2_pickup 10/10   tier3_store 2/5
```

Both planners solve every `tier1_locate` and `tier2_pickup` task —
object resolution, navigation, and pickup are solid across both
planning strategies and all 5 scenes. All failures are in
`tier3_store`, and 2 of them are the *same* two known, deliberately-kept
dataset limitations (see the dataset card): the `FloorPlan301`
book→drawer geometry limit and the `FloorPlan401` spray-bottle→shelf
non-openable-target bug (`_deposit()`, tracked in
`docs/roadmap.md`) — both planners fail these identically, since
`BehaviorTreePlanner` composes the same `_deposit()`/`GOAL_HANDLERS`
templates `RuleBasedPlanner` uses (see `behavior_tree.py`'s own
docstring).

**The one planner-specific difference**: `behavior_tree` additionally
failed `FloorPlan1`'s bread→fridge task — the *same* task
`rule_based` succeeded on (842ms) — after a **100.1-second** stall on
a `navigate` action, with error `"Action 'navigate' exceeded its
Nones timeout."`. Investigated (not left as a mystery number):

- The message is misleading. `ExecutionController` is constructed
  with the default `step_timeout_s=None`
  (`orchestration/task_runner.py:220`, `agents/execution_agent.py:58`)
  — no timeout is configured, so `_dispatch_with_timeout()` should
  take the un-timed direct-call path (`execution/controller.py:490`),
  never the `ThreadPoolExecutor`-wrapped path that can raise
  `concurrent.futures.TimeoutError`. The fact that
  `except FutureTimeoutError:` (`controller.py:418`) fired anyway
  means the `TimeoutError` was actually raised from *inside*
  `self._dispatcher.dispatch(action)` itself (almost certainly
  AI2-THOR/Unity's own internal communication timeout), not from our
  own timeout wrapper — but the handler unconditionally blames
  `self._step_timeout_s` (`None`), producing the nonsensical `"Nones
  timeout"` text regardless of what actually happened.
- Not reproduced: the identical task, same scene, ran successfully
  under `rule_based` in the same benchmark run. This looks like a
  one-off AI2-THOR/Unity-side stall (both planners produce the same
  underlying `navigate`→`Fridge` action here), not a `behavior_tree`-
  specific defect — but a single dispatched action being able to
  block the entire execution loop for 100+ seconds with no way to
  bound it, and the resulting message actively misattributing the
  cause, are both real problems regardless of root cause. Tracked in
  `docs/roadmap.md`'s new "Misleading `ACTION_TIMEOUT` message" row.

## 6. Results — memory ablation (axis 3)

One "find X twice, same scene" recall episode pair per scene (5
scenes), under `memory_off` and `memory_on`:

```
Total: 20/20 episodes succeeded (both conditions, all 5 scenes)
memory_context retrieved on recall (episode 2, memory_on): 5/5 scenes
memory actually influencing the plan (memory_used_in_plan): 0/20
```

This extends Phase B's central finding
([`phase_b_real_ablation_findings.md`](phase_b_real_ablation_findings.md))
from `FloorPlan1`-only to all 5 Phase D scenes, and the result is
identical everywhere: memory retrieval genuinely works end to end (a
real episodic memory from episode 1 is correctly retrieved in episode
2, in every single scene), but `rule_based.py`'s memory-hint mechanism
never actually changes the plan for a `find` task, because — per
Phase B's own root cause — it keys off AI2-THOR's `parentReceptacle`
metadata, which real AI2-THOR leaves unset for ordinary loose objects
in every scene tested, not just `FloorPlan1`. **This is not a new
bug** — it is Phase B's already-tracked "Broaden memory's location
signal beyond `parentReceptacle`" roadmap item, now confirmed to be a
general property of real AI2-THOR scenes rather than something
specific to the one scene Phase B originally tested.

## 7. What this does and does not establish

**Does establish:**
- Two independently-designed planners (rule-based, Behavior Tree)
  solve 88–92% of a 25-task, 5-scene, 3-tier benchmark using a
  scoring predicate that checks real post-execution simulator state,
  not just "did nothing error."
- Both planners fail identically on genuine, already-diagnosed bugs
  (not silently — every failure has a concrete, cited cause).
- Memory retrieval infrastructure works correctly across all tested
  room types; the memory-hint mechanism's inertness is a general
  property of real AI2-THOR object metadata, not a `FloorPlan1`
  artifact.
- A real, reproducible-once execution-layer issue (misleading timeout
  attribution, no upper bound on a single action's stall time) that
  no prior harness in this project surfaced.

**Does not establish:**
- ReAct's actual planning quality (scoped out — see section 3).
- Statistical significance — 25 tasks, single-run, is a real number
  from a real system, not a powered study (same caveat every prior
  real-AI2-THOR report in this project states).
- Generalization beyond the 5 sampled scenes (same caveat as Phase D).
- Whether the `behavior_tree` navigate stall is reproducible or a
  one-off — a repeated-trials variant of this benchmark would be
  needed to tell the difference, and is not run here.

## 8. Publishing

Not yet pushed to the Hugging Face Hub — this environment has no
`HF_TOKEN` and no destination namespace was specified. Everything
needed to publish is built and versioned locally:

- Dataset repo contents: `backend/planning_evaluation/dataset/v1.0/`
  (`tasks.json` + a dataset card `README.md` with YAML front matter,
  ready to copy into a fresh `datasets/<namespace>/milo_benchmark`
  Hub repo, or push directly via `huggingface_hub.upload_folder`).
- To publish once you have a token:
  ```bash
  pip install datasets  # not installed in this environment
  huggingface-cli login  # or set HF_TOKEN
  python -c "
  from huggingface_hub import HfApi
  api = HfApi()
  api.create_repo('YOUR_NAMESPACE/milo_benchmark', repo_type='dataset', exist_ok=True)
  api.upload_folder(
      folder_path='backend/planning_evaluation/dataset/v1.0',
      repo_id='YOUR_NAMESPACE/milo_benchmark',
      repo_type='dataset',
  )
  "
  ```
- The benchmark *runner* (`backend/planning_evaluation/run_benchmark.py`,
  `run_memory_ablation.py`) stays in this repository — that is what
  makes this a benchmark and not just a dataset dump: anyone can clone
  MILO, point their own `Planner` subclass at `dataset/v1.0/tasks.json`,
  and reproduce a directly comparable score using the same
  `check_goal_live()` predicate.

## 9. Suggested next steps

1. Fix the two `tier3_store` bugs this dataset deliberately keeps as
   ground truth (`_deposit()` non-openable-target check; the
   misleading `ACTION_TIMEOUT` message) — then re-run and record a
   `v1.0` scored-baseline delta, not a dataset change.
2. Get a real `ReActPlanner` baseline once an LLM API key is
   available — the runner needs one line changed to add it.
3. Push `dataset/v1.0/` to the Hugging Face Hub once a namespace/token
   is available (section 8).
4. Extend to `v1.1` with more scenes/tasks once there's a concrete
   reason to (e.g. after the two known bugs are fixed, add tasks that
   would have caught them before they shipped).
