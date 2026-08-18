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

**Update**: a Gemini free-tier key was later provided and a real
`react` run was attempted — see Addendum 2. That run's own numbers
turned out to make this section's concern *more* relevant, not less:
see Addendum 2 for exactly why a raw success-rate number from that run
would itself have been misleading without the same care this section
already argued for. A clean, complete, quota-free baseline was later
obtained via a local model — see Addendum 3.

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

---

## Addendum (resolved/investigated) — the two bugs section 5 flagged

**This section documents follow-up work done after the original report
above; that text is left unchanged as the honest record of the
original benchmark run.**

### `_deposit()` non-openable-target bug — fixed

See `experiments/reports/phase_d_floorplan_generalization_findings.md`'s
own addendum for the full fix detail (`ObjectState.is_openable`,
`_deposit()`'s carve-out, live-metadata seeding). Re-running
`milo-v1-fp401-t3a` (the one `tier3_store` failure in this report's
baseline that wasn't the `FloorPlan301` geometry limit) against real
AI2-THOR now succeeds: `goal_success=True`. This changes the
**expected** `rule_based`/`behavior_tree` baseline from 23/25 and
22/25 to **24/25 and 23/25** respectively (one more `tier3_store` pass
each) on a re-run — not re-run in full here to avoid re-litigating
numbers already reported honestly above; a fresh full benchmark run
after this fix (and the ReAct addition, once available) is the right
place to record the new baseline as `v1.0`'s scored delta, per
suggested next step 1.

### The ~100s `navigate` stall — root cause found, message fixed, root stall itself not "fixable"

Investigated properly rather than left as a mystery number. Root
cause: `ai2thor.fifo_server.FifoServer` (the AI2-THOR client's own
IPC layer, `ai2thor/fifo_server.py:57,134`) has its own internal pipe-read
timeout, **defaulting to 100.0 seconds**, completely independent of
and invisible to this project's `ExecutionController.step_timeout_s`.
When Unity fails to respond within that window, AI2-THOR itself raises
Python's builtin `TimeoutError(f"Reading from AI2-THOR backend timed
out (using {timeout}s) timeout.")`. Since Python 3.11,
`concurrent.futures.TimeoutError is TimeoutError` (confirmed directly
in this environment's Python 3.14) — so this AI2-THOR-internal
exception is caught by `execution/controller.py`'s
`except FutureTimeoutError:` clause, which previously assumed any
`FutureTimeoutError` it saw could only come from *our own*
`step_timeout_s`-configured `ThreadPoolExecutor` wrapper and blamed
`self._step_timeout_s` unconditionally — wrong whenever
`step_timeout_s` is `None` (the default `TaskRunner`/
`ExecutionAgentWrapper` both use), which is exactly the case that
produced `"exceeded its Nones timeout"`.

**One correction to this report's original text above**: section 5
said "there is currently no way to bound how long a single action can
hang" when no `step_timeout_s` is configured. That was inaccurate —
there *is* a bound, AI2-THOR's own ~100s one; this project's own
`ExecutionController` just wasn't the thing enforcing it, and its
error message didn't know that. Correcting the record here rather than
silently editing the original claim.

**Fixed**: `execution/controller.py`'s `_dispatch_with_retries` now
distinguishes the two cases by checking `self._step_timeout_s is None`
at the point the `FutureTimeoutError` is caught — genuinely our own
configured timeout firing (`step_timeout_s` set, `ThreadPoolExecutor`
path) keeps the original `"exceeded its {step_timeout_s}s timeout"`
message; AI2-THOR's own internal timeout firing (`step_timeout_s is
None`, direct-call path) now reports `"got no response from AI2-THOR
before AI2-THOR's own internal protocol timeout fired (no
step_timeout_s is configured on this ExecutionController): {original
AI2-THOR exception text, which already states the real 100.0s
number}"`. Regression test:
`test_engine_level_timeout_with_no_step_timeout_configured_is_reported_accurately`
(`backend/tests/test_execution_controller.py`), which raises a
synthetic `TimeoutError` matching AI2-THOR's own message shape via a
`FakeSimulator` hook (no real 100s wait needed to test it).

**Not fixed, because it isn't this project's bug to fix**: the
underlying ~100s Unity stall itself. This is either (a) genuine
Unity-side flakiness for that one action in that one run (the same
task succeeded under `rule_based` moments earlier in the same
benchmark run, and was not reproduced on a subsequent re-run attempt),
or (b) an inherent AI2-THOR/Unity IPC characteristic outside this
project's control. Neither this investigation nor the fix above
attempts to make Unity respond faster or to silently retry/swallow the
failure — per the report's own honesty-first discipline, an accurate
error message for a real, occasionally-occurring stall is the correct
fix; hiding or auto-retrying it would not be. `docs/roadmap.md`
updated to reflect this as resolved (the message bug) with the
underlying stall documented as a known, understood AI2-THOR
characteristic rather than an open question.

---

## Addendum 2 — the real `ReActPlanner`/Gemini baseline

A Gemini free-tier `GEMINI_API_KEY` was later made available. Ran the
full `milo_benchmark v1.0` (all 25 tasks) with `rule_based`,
`behavior_tree`, and `react` (`LANGUAGE_LLM_PROVIDER=gemini`, model
`gemini-flash-latest`, which currently resolves to `gemini-3.7-flash`
per the provider's own error responses below). `run_benchmark.py` was
extended with `react` support (`PLANNERS` is now a dict of zero-arg
factories, `_make_react_planner()` builds a real `LLMClient` via the
same `language.provider_factory.create_llm_client()` production
wiring path) and a bounded, fully-logged retry for `react` episodes
that fail with a transient-looking LLM-provider error (up to 2 extra
attempts, 3s apart, only on `503`/`429`/`RESOURCE_EXHAUSTED`/etc.
markers — see `run_benchmark.py`'s module docstring). Raw output:
[`experiments/results/milo_benchmark_20260817T154347Z.json`](../results/milo_benchmark_20260817T154347Z.json)
/ [`..._episodes.csv`](../results/milo_benchmark_20260817T154347Z_episodes.csv).

### Rule-based and Behavior Tree, re-confirmed with both roadmap fixes applied

```
rule_based:      24/25 (96%)   tier1_locate 10/10   tier2_pickup 10/10   tier3_store 4/5
behavior_tree:    24/25 (96%)   tier1_locate 10/10   tier2_pickup 10/10   tier3_store 4/5
```

Up from 23/25 and 22/25 in the original run (Addendum 1's predicted
delta, now confirmed for real): the `_deposit()` fix resolved the one
non-geometry `tier3_store` failure for both planners; the
`FloorPlan301` book→drawer geometry limit (real, not a bug) remains
the only failure for both. The `behavior_tree` navigate stall from the
original run did **not** recur — consistent with Addendum 1's
"one-off Unity-side stall, not deterministic" read.

### `react`/Gemini: the honest number is much lower than the raw success rate suggests

Raw script output: `goal_success_rate: 0.44` (11/25). **This number is
misleading on its own and should not be quoted without the context
below** — reporting it bare would be exactly the "padded/degraded
number" this report's own discipline exists to avoid.

What actually happened: Gemini's free tier returned
`429 RESOURCE_EXHAUSTED` — `"Quota exceeded for metric:
generativelanguage.googleapis.com/generate_content_free_tier_requests,
limit: 20, model: gemini-3.7-flash"` — starting partway through the
second scene (`FloorPlan5`) and on nearly every subsequent call for
the rest of the ~10+ minute run. This is a **daily quota ceiling** (20
requests), not a short per-minute rate limit: the 3-second, 2-attempt
retry policy never once recovered a call after the quota was first
hit, and it stayed exhausted through the last episode, many minutes
and dozens of attempts later. One earlier episode also hit a distinct,
unrelated failure — a local DNS resolution error
(`NameResolutionError`, `"Temporary failure in name resolution"`) —
correctly NOT retried by the transient-LLM-error policy (it matches
none of that policy's markers), since it's a local network condition,
not a Gemini-side one.

Concretely, out of 25 `react` episodes:

```
plan_success:       2/25   (a real plan was actually produced)
execution_success:  2/25   (that plan then executed without error)
goal_success:       11/25  (see below -- inflated, not a real capability number)
episodes needing >=1 retry:        23/25
total extra attempts used:         45  (of a possible 50 = 25 x 2)
episodes still failing after all retries: 22/25
```

By tier, `execution_success` (the honest "did react actually get
anything done" number, since it requires a real plan to have been
produced and dispatched):

```
tier1_locate: 1/10
tier2_pickup: 1/10
tier3_store:  0/5
```

**Why `goal_success` (11/25) is inflated**: `tier1_locate`'s live
success predicate (`live_state.check_goal_live()`) checks only "does
an object of the named type exist in the scene" — documented as a
known simplification in `dataset/v1.0/README.md` from the start,
because there is no live "was this actually located" fact to check
without a perception system wired into scoring (see that file's
"Known limitations"). That predicate is trivially true regardless of
whether `react` ever produced a plan at all, since the object was
already sitting in the scene before the episode started. 9 of
`tier1_locate`'s 10 `goal_success=True` rows have `plan_success=False`
— the LLM call failed outright and `react` never attempted anything,
yet the task is scored a "success" by this predicate. `tier2_pickup`
(1/10) and `tier3_store` (0/5) don't have this problem — their
predicates genuinely require the object to have been picked up /
placed, which needs a real executed plan — and those numbers agree
exactly with `execution_success` for those tiers, which is the
honest signal here.

**Conclusion**: this run does not establish anything about
`ReActPlanner`'s actual planning quality — 2 real plans were produced
out of 25 attempts, both against real ground truth. What it does
establish, honestly: Gemini's free tier (20 requests/day for this
model, at time of testing) is nowhere near sufficient to run a
25-task benchmark where `ReActPlanner`'s loop can issue multiple LLM
calls per task (`max_iterations=12`, `repair_attempts=2`), and this
project's benchmark harness handles that reality correctly — bounded
retries, full transparency on how many were used, and a per-tier
breakdown that surfaces the scoring predicate's own known weakness
rather than letting it quietly inflate a headline number. A real
`ReActPlanner` baseline needs either a paid Gemini tier, a different
provider with a workable free quota, or spacing 25 tasks' worth of
calls across multiple days — none of which this pass attempted, since
manufacturing a "clean" number by waiting out a quota reset would
itself not be honest about what a from-scratch free-tier run actually
looks like.

`docs/roadmap.md` and the README's planner-comparison numbers are
updated with all three planners' real, current numbers, including this
caveat.

---

## Addendum 3 — a real, clean `ReActPlanner` baseline via local Qwen/Ollama

Addendum 2's Gemini attempt hit a free-tier daily quota (20
requests/day) after 2 of 25 episodes and never produced a clean
number. This addendum replaces that gap with a real one: a local
Qwen model served via Ollama, with zero external quota/network
dependency, completing the full 25-task run cleanly.

### Setup

- **Hardware**: RTX 4050 Laptop GPU, confirmed via `nvidia-smi` — 6.0
  GiB total VRAM (not assumed; checked before picking a model), ~5.0
  GiB available at the time of the run.
- **Ollama**: v0.32.14, installed user-space (no root available in
  this environment — the official installer's systemd/root path was
  skipped; the standalone `ollama-linux-amd64.tar.zst` release archive
  was extracted directly and run as `ollama serve` under the calling
  user, with `OLLAMA_MODELS` pointed at a user-writable directory).
  Confirmed serving an OpenAI-compatible endpoint at
  `http://localhost:11434/v1` with a direct `curl` smoke test before
  wiring anything into MILO.
- **Model**: `qwen2.5:7b` (Ollama's default tag, `Q4_K_M`
  quantization, 4.7 GB on disk) — the 7B/4-bit fit the task
  description expected, confirmed to actually fit: `ollama ps` reports
  an 82%/18% GPU/CPU split (not fully GPU-resident, but comfortably
  functional — warm inference measured at <1s for a short prompt, 1.9s
  for a real single-step `ReActPlanner.plan()` call). No fallback to a
  smaller variant was needed.
- **MILO wiring**: `LANGUAGE_LLM_PROVIDER=qwen`,
  `LANGUAGE_LLM_MODEL=qwen2.5:7b`,
  `LANGUAGE_LLM_BASE_URL=http://localhost:11434/v1`,
  `QWEN_API_KEY=not-needed` (Ollama enforces no auth; `language.config.
  LLMRuntimeConfig._resolve_api_key` still requires some value to be
  set, per its own docstring — an arbitrary placeholder satisfies
  that without implying real auth exists), `LANGUAGE_LLM_TIMEOUT_SECONDS=120`
  (raised from the 30s default — local CPU-offloaded inference on a
  laptop GPU is slower than a cloud API, and 30s was cut close on the
  smoke test's `store` task). Confirmed via the exact same
  `language.provider_factory.create_llm_client(LLMRuntimeConfig.
  from_env())` production path Addendum 2's Gemini attempt used — no
  benchmark-specific client construction.
- Before committing to the full run: a single real `ReActPlanner.plan()`
  call for `find mug` (1.88s, succeeded, plan
  `[('locate', 'mug')]`) and one for `store bread -> fridge` (11.9s,
  **failed for real reasoning reasons** — `"Proposed action 'put_down'
  requires a target"` after 3 repair attempts, no fallback planner
  configured) — confirming both that the pipeline works end-to-end and
  that failures are genuine model-quality failures, not silently
  masked.

### Result: 20/25 (80%), clean and honest — no retries, no predicate artifact

```
plan_success:       20/25
execution_success:  20/25
goal_success:       20/25   (identical set to the two above -- see below)

tier1_locate: 10/10
tier2_pickup: 10/10
tier3_store:   0/5
```

Unlike Addendum 2's Gemini run, **`goal_success` and `execution_success`
agree on every single episode this time** (checked programmatically,
zero mismatches) — none of `tier1_locate`'s known "existence-only
predicate" inflation applies here, because every `tier1_locate`
success in this run also has `execution_success=True`: the plan was
genuinely produced and dispatched, not just coincidentally true
because the object already existed in the scene. This run needed the
retry wrapper zero times (`episodes_that_needed_a_retry: 0`) — a local
model has no rate limit to retry around.

**All 5 failures are `tier3_store`, and all 5 are genuine reasoning
failures**, not infrastructure:

```
FloorPlan1   bread->fridge:        'place' violates precondition(s): holding_target, container_ready
FloorPlan5   mug->cabinet:         'pickup' violates precondition(s): target_near
FloorPlan201 remotecontrol->drawer:'open' violates precondition(s): target_near
FloorPlan301 book->drawer:         'pickup' violates precondition(s): target_near
FloorPlan401 spraybottle->shelf:   'navigate' violates precondition(s): target_located
```

Every failure is the same class of mistake: `qwen2.5:7b` proposes an
action out of order relative to the plan's own precondition chain
(trying to place before confirming it's holding the object and the
container is ready; trying to pick up or open before navigating close
enough; trying to navigate before locating). `react.py`'s repair loop
(3 attempts) gives the model multiple chances to self-correct against
the validator's exact error message and it still doesn't recover
within budget on any of these 5 — a genuine capability finding: this
7B model at this quantization can handle single- and two-step
manipulation goals cleanly but consistently mis-sequences the
4-6-step `store` goal's dependency chain, unlike `rule_based`/
`behavior_tree`, which are correct by construction for the same tasks.

### Runtime

- `react` episodes' own wall-clock time (planning + execution, not
  counting Unity subprocess launch): **138.3s total** (25 episodes,
  mean 5.5s/episode — 1.7-1.9s for `tier1_locate`, ~5.4-6.3s for
  `tier2_pickup`, 7-12.2s for the `tier3_store` failures, since those
  spend their full 3-repair-attempt budget before giving up).
- Full 75-episode run (`rule_based` + `behavior_tree` + `react`),
  including Unity relaunch per episode: on the order of several
  minutes end to end, consistent with the non-`react` planners' own
  per-episode timings from Addendum 1/2 plus `react`'s 138s.
- No GPU memory pressure or OOM observed at any point in the run.

### What this does and does not establish

**Does establish**: a real, complete, quota-free `ReActPlanner`
baseline is possible entirely locally on modest laptop-GPU hardware,
and — now that all three planners have real numbers on the same 25
tasks — `rule_based`/`behavior_tree` (96% each, Addendum 1) meaningfully
outperform this particular local-LLM configuration (80%) specifically
on multi-step container tasks, while matching it exactly on
single/two-step tasks (10/10 all three planners, both tiers).

**Does not establish**: how a larger Qwen variant, a different
quantization, a different local model entirely, or a paid-tier cloud
model would perform — this is one specific model/quantization/hardware
combination, documented for reproducibility, not a claim about
`ReActPlanner`'s ceiling in general. Also does not establish
performance on the two dataset tasks that were already known-failing
for the symbolic planners (`FloorPlan301` book→drawer's geometry limit,
`FloorPlan401`'s pre-fix shelf bug). `react`'s `tier3_store` failures
are a different, independent reasoning failure mode: 4 of its 5
failures (`FloorPlan1`, `FloorPlan5`, `FloorPlan201`, `FloorPlan401`)
are on tasks `rule_based`/`behavior_tree` both succeed at in this same
run; the 5th (`FloorPlan301`) is a task the symbolic planners also
fail, but for the unrelated real-geometry reason documented in Phase D
— `react` never got far enough into that plan (`pickup` rejected before
navigation) to reach the placement step where the geometry limit would
even apply.
