---
pretty_name: MILO Benchmark
language:
  - en
license: mit
task_categories:
  - robotics
tags:
  - embodied-ai
  - ai2thor
  - task-planning
  - robotics
  - synthetic
size_categories:
  - n<1K
---

# MILO Benchmark v1.1

`v1.1` extends [`v1.0`](../v1.0/README.md) rather than replacing it --
`v1.0` stays frozen and unchanged per its own versioning policy (see
that card's "Versioning" section, and this project's
`experiments/reports/phase_e_milo_benchmark_report.md` for the full
methodology `v1.0` was built with, which this card assumes as
background and does not repeat). Everything in `v1.0`'s card
(collection methodology, success predicates, known limitations, the
perception-grounded `tier1_locate` addendum) still applies unchanged
to every task `v1.1` carries over from `v1.0`. This card documents only
what is new.

## What's new in v1.1

- **4 more iTHOR scenes** (9 total, up from 5), chosen to extend room-type
  coverage rather than duplicate it: `v1.0` already had 2 kitchens, 1
  living room, 1 bedroom, 1 bathroom, so the 4 new scenes are 1 more
  living room, 1 more bedroom, 1 more bathroom, and 1 more living room
  again (living room ends up with 3 total; no third kitchen was added).
  This is a meaningful extension, not an exhaustive sweep of iTHOR's
  ~120 scenes -- see `v1.0`'s "What this dataset does not cover" for
  why full scene-coverage was never this dataset's goal.
- **A new `tier4_multi_step` difficulty tier** -- see below.
- **29 new tasks**: 20 flat `tier1_locate`/`tier2_pickup`/`tier3_store`
  tasks (5 per new scene, same 2/2/1 split `v1.0` uses) + 9
  `tier4_multi_step` tasks (1 per scene, all 9 scenes -- the 5 original
  `v1.0` scenes get a `tier4_multi_step` task added here too, since
  `v1.1` is additive over `v1.0`'s task set, not just its scene list).
  **Total: 54 tasks across 9 scenes** (`tasks.json`).
- Every `v1.0` task_id, scene, goal/object/target, and instruction is
  carried into `v1.1` with those **scoring-relevant fields identical**
  (regression-tested, see `backend/tests/test_planning_evaluation.py`'s
  `test_v1_1_frozen_v1_0_tasks_scoring_fields_match_v1_0`) -- a score
  on `v1.0`'s 25 tasks stays directly comparable whether computed
  against `dataset/v1.0/tasks.json` or `dataset/v1.1/tasks.json`'s
  first 25 rows. **This is not a byte-identical-JSON claim**: the
  free-text, non-scoring `notes` field was deliberately edited on 2 of
  the 25 carried-over tasks when `v1.1` was authored --
  `milo-v1-fp301-t3a`'s note gained a cosmetic "(and here, unchanged)"
  clause, and `milo-v1-fp401-t3a`'s note was **substantively
  rewritten**: `v1.0`'s text says the `_deposit()` non-openable-target
  bug is still unfixed ("expected to fail this task until that bug is
  fixed"), while `v1.1`'s text says that bug has since been fixed and
  the task is now expected to succeed. Both files' `goal`/`object`/
  `target`/`instruction`/`scene` for this task are unchanged either
  way -- only the human-readable annotation was updated to stay
  accurate.

  This scene table also reflects an honest, not a data-driven,
  balancing choice: `v1.0` had 2 kitchens and 1 each of living room/
  bedroom/bathroom; `v1.1` adds 1 more scene to living room, bedroom,
  *and* bathroom, landing on 3 living rooms rather than a 3rd kitchen.
  A 3rd kitchen (`FloorPlan7`) was live-scanned during collection and
  confirmed available/usable -- it was set aside in favor of living
  room getting the 4th new scene with no principled reason beyond
  needing to pick one room type to move toward parity with. iTHOR has
  roughly 30 scenes per room type, so this was a real choice among
  many available options, not a constraint.

| Scene | Room type | Tasks | New in v1.1? |
|---|---|---|---|
| `FloorPlan1` | kitchen | 6 (5 + 1 tier4) | tier4 task only |
| `FloorPlan5` | kitchen | 6 (5 + 1 tier4) | tier4 task only |
| `FloorPlan201` | living room | 6 (5 + 1 tier4) | tier4 task only |
| `FloorPlan301` | bedroom | 6 (5 + 1 tier4) | tier4 task only |
| `FloorPlan401` | bathroom | 6 (5 + 1 tier4) | tier4 task only |
| `FloorPlan202` | living room | 6 | scene + all 6 tasks |
| `FloorPlan302` | bedroom | 6 | scene + all 6 tasks |
| `FloorPlan402` | bathroom | 6 | scene + all 6 tasks |
| `FloorPlan203` | living room | 6 | scene + all 6 tasks |

Room-type totals: kitchen ×2, living room ×3, bedroom ×2, bathroom ×2.

## `tier4_multi_step`: what it's designed to exercise

`tier3_store`'s hardest task is still a **single-object** chain
(locate -> navigate -> pickup -> locate target -> navigate ->
(open) -> place -> (close)) -- every step serves one object reaching
one destination. `tier4_multi_step` is a different, harder axis:
**two independent single-object sub-goals in one instruction**, e.g.
*"Put the mug in the cabinet and the spoon in the drawer."* Both
sub-goals must be satisfied for the task to count as a success --
completing only one is a partial result, not a pass. This is designed
to probe **cross-object sequencing/planning depth**: does a planner
(especially an LLM-driven one) correctly treat this as two separate
goals to satisfy in sequence, or does it conflate them, drop one, or
apply one sub-goal's object/target to the other?

Concretely, each `tier4_multi_step` row's `goal`/`object`/`target`
fields are `null`; instead it carries a `subtasks` list of two
`{"goal", "object", "target"}` dicts, e.g.:

```json
{
  "task_id": "milo-v1.1-fp1-t4a",
  "scene": "FloorPlan1",
  "room_type": "kitchen",
  "difficulty_tier": "tier4_multi_step",
  "instruction": "Put the knife away in the drawer and the cup away in the cabinet.",
  "goal": null, "object": null, "target": null,
  "subtasks": [
    {"goal": "store", "object": "knife", "target": "drawer"},
    {"goal": "store", "object": "cup", "target": "cabinet"}
  ],
  "notes": "..."
}
```

**Why two independent `SingleTask`s, not a nested `MultiTask`**: this
project's schema layer (`schemas.task.MultiTask`) already models an
ordered decomposition into subtasks, but no planner in the origin
repository (`RuleBasedPlanner`, `BehaviorTreePlanner`, `ReActPlanner`)
implements a `MultiTask`-level `plan()` -- every one of them takes a
`SingleTask`. Rather than build new multi-task planning machinery
across all three planners (a materially larger, riskier change than
this dataset extension calls for), the reference runner
(`run_benchmark.py`) executes `tier4_multi_step`'s two `subtasks` as
two sequential `TaskRunner.run()` calls against the *same* live
simulator/episode (one Unity process, not restarted between
sub-goals) -- each sub-goal's `WorldState` is freshly re-seeded from
live metadata immediately before it plans, so the second sub-goal's
planner sees the real post-first-sub-goal world. This is "sequencing
across two independent sub-goals" implemented at the benchmark-harness
level, not inside any planner. See `loader.BenchmarkTask.to_single_tasks()`
and `run_benchmark._run_multi_subtask_episode()`.

## Success predicate for `tier4_multi_step`

`goal_success` is `True` iff **both** sub-goals' `check_goal_live()`
result is `True` against **one** metadata snapshot taken after both
sub-goals have been planned and executed, in order
(`live_state.check_goal_live_multi()`, `MultiGoalResult.all_succeeded`).
A planner that completes only one sub-goal, or that undoes the first
sub-goal while pursuing the second, is scored a failure -- this is a
genuinely stricter, conjunctive predicate, not an average or "best of
two." `plan_success`/`execution_success` are likewise the AND across
both sub-goals; both sub-goals are always attempted regardless of
whether the first one's plan/execution succeeded (mirroring a real
agent continuing to the next sub-goal rather than aborting the whole
instruction over one failed part), and `failure_cause` records every
sub-goal that failed, tagged by its own object/target.

## Collection methodology (identical discipline to v1.0)

Every new scene (`FloorPlan202`, `FloorPlan302`, `FloorPlan402`,
`FloorPlan203`) and every `tier4_multi_step` task's two sub-goals
(including the ones added to the 5 original `v1.0` scenes) were chosen
the same way `v1.0`'s collection methodology section describes: a live
AI2-THOR `Controller.step()`/`last_event.metadata` scan of each
candidate scene's real object inventory (`objectType`, `pickupable`,
`receptacle`, `openable`) was taken first; every task object/target
was chosen only from that confirmed live list, never guessed. The 5
original `v1.0` scenes were re-scanned for this pass (rather than
reusing `v1.0`'s own recorded inventory) specifically to confirm the
*new* `tier4_multi_step` objects/targets for those scenes actually
exist live, since `v1.0`'s own scan only ever confirmed the objects
`v1.0`'s own tasks use.

`tier4_multi_step` targets were deliberately split between confirmed
openable containers (Drawer, Cabinet, Fridge, Box, Safe) and confirmed
non-openable receptacles (Shelf, SideTable, Sofa, CoffeeTable) across
the 9 tasks -- exercising `_deposit()`'s `is_openable is False`
carve-out (see `v1.0`'s card, "Known limitations" -- this bug is now
fixed, see the origin repo's `phase_e_milo_benchmark_report.md`
addendum) on both of a `tier4_multi_step` task's independent sub-goals
in several cases (`FloorPlan202`, `FloorPlan402`'s second sub-goal,
`FloorPlan401`), not only single-object `tier3_store` tasks.

## Baselines (v1.1, real runs, all four planners)

| Planner | Goal success | tier1_locate | tier2_pickup | tier3_store | tier4_multi_step | Notes |
|---|---|---|---|---|---|---|
| `rule_based` | 50/54 (92.6%) | 18/18 | 18/18 | 7/9 | 7/9 | Both `tier3_store` failures are the same real AI2-THOR placement-geometry limit `v1.0` already documents (`FloorPlan301`, now also `FloorPlan203` -- same task shape, independently reproducing). Both `tier4_multi_step` failures are a real, newly-surfaced harness gap (not a planner defect): a failed `place` in sub-goal 1 leaves the object physically held, and `WorldState` re-seeding between sub-goals has no signal for that, so sub-goal 2's plan assumes an empty hand and AI2-THOR rejects it. See "`tier4_multi_step` investigation update" below for the current, precise per-episode status. |
| `behavior_tree` | 50/54 (92.6%) | 18/18 | 18/18 | 7/9 | 7/9 | Same task/plan-step outcomes as `rule_based` (shares its goal-handler templates); same failures for the same reasons. |
| `htn` | 43/45 (95.6%)¹ | 18/18 | 18/18 | 7/9 | not attempted¹ | A real Hierarchical Task Network engine (compound tasks, a state-conditional method library, recursive decomposition) -- not a second implementation of `rule_based`'s control flow. ¹Slice 1 only: does not yet support `tier4_multi_step`'s multi-subtask decomposition, so those 9 tasks were deliberately not attempted, not scored as failures -- goal success is out of 45, not 54. Both `tier3_store` failures (`milo-v1-fp301-t3a`, `milo-v1.1-fp203-t3a`) are the identical placement-geometry limit `rule_based`/`behavior_tree` hit on the same pair -- no new failure mode across the 4 additional scenes, i.e. `v1.0`'s 5-scene result generalizes. |
| `react` (`qwen2.5:7b`, Q4_K_M, via Ollama, local) | 36/54 (66.7%) | 18/18 | 18/18 | 0/9 | 0/9 | `tier4_multi_step`'s 0/9 is the arithmetically expected composition of `tier3_store`'s already-0% rate (a tier requiring two consecutive successful `store` sequences cannot score above a planner's single-`store` success rate) -- confirmed by inspecting each failure, not assumed: every one shows the same precondition-mis-sequencing pattern `v1.0`'s Addendum 3 already documents. `goal_success`/`execution_success`/`plan_success` agree on every episode; 0/54 episodes needed a retry. |

See the origin repository's `experiments/reports/
phase_e_milo_benchmark_report.md`'s Addendum 7 for full methodology,
per-failure root-cause detail, cost/latency, and exact reproduction
commands.

### `tier4_multi_step` investigation update

The `WorldState`-reseeding gap noted in the `rule_based`/`behavior_tree`
row above has since been investigated in depth (not fixed and
re-benchmarked -- the table above is still the original publish run).
Two distinct causes were found behind the two known-failing episodes:

- **`milo-v1.1-fp302-t4a`**: the engine-crash *symptom* (the planner
  blindly issuing a doomed action once a hand is already occupied) is
  fixed and verified -- re-seeding `robot_holding` with one detection
  call per object name (rather than one joint multi-phrase prompt) at
  a validated `box_threshold=0.25` correctly detects the held object
  and lets the planner correctly *decline* to plan the second sub-goal
  instead of crashing AI2-THOR. This fix is demonstrated via a targeted
  investigation script, not yet merged into the production benchmark
  harness's `_seed_initial_state_from_live_metadata()` path -- the
  table above does not yet reflect it. The task's `goal_success` is
  still `False` either way, now solely because sub-goal 1 hits the same
  real placement-geometry limit `tier3_store` already has, unrelated to
  this bug.
- **`milo-v1.1-fp201-t4a`**: still open. Per-name detection queries do
  find the held object, but at a measured depth (0.853m) outside the
  held-object heuristic's `HELD_OBJECT_MAX_DEPTH_M=0.5m` cutoff --
  calibrated against smaller held objects (0.347m-0.459m) than this
  one. A separate, nearer, *not*-held object was also wrongly preferred
  by the heuristic's "closest wins" tie-break. The concrete next step
  identified (seeding `robot_holding` from AI2-THOR's own live
  `isPickedUp`/`inventoryObjects` metadata, sidestepping both the
  detection-prompt and depth-calibration dependencies) has not been
  implemented.

A related, broader finding surfaced during this investigation: Grounding
DINO's confidence measurably drops under multi-phrase joint prompts
(confirmed on 2 independent objects/frames) -- this does not affect
`goal_success` for any tier in this dataset or `perceived_by_agent`'s
`tier1_locate` check (both already query one object name at a time),
but does affect some manual demo scripts in the origin repository. Full
chain, exact numbers, and regression tests: the origin repository's
`docs/roadmap.md`.

## Second local model for `react`: `qwen2.5:3b` comparison

A second small local model was run through the identical `react`
harness/instrumentation against this same 54-task set, to see how
model size trades off against accuracy/latency:

| Model | Goal success | tier1_locate | tier2_pickup | tier3_store | tier4_multi_step | Avg latency/episode | Hardware |
|---|---|---|---|---|---|---|---|
| `qwen2.5:7b` (Q4_K_M) | 36/54 (66.7%) | 18/18 | 18/18 | 0/9 | 0/9 | 7156ms | RTX 4050 Laptop GPU, 6GB VRAM, 82%/18% GPU/CPU split |
| `qwen2.5:3b` (Q4_K_M) | 36/54 (66.7%) | 18/18 | 18/18 | 0/9 | 0/9 | 3107ms | Same GPU, full GPU residency |

`qwen2.5:3b` matches `qwen2.5:7b`'s goal-success rate **exactly,
task-for-task** (verified via a full 54-row side-by-side comparison,
0 differences) at roughly 2.3x lower average latency and modestly
fewer tokens per episode -- a real cost/latency win with no accuracy
cost observed on this task set.

Investigated why the aggregate scores are identical (rather than
taking the match at face value) by re-running 6 of these failing
episodes (3 per model) with a diagnostic wrapper that captures the
actual raw LLM completions -- reproducing the same outcomes as the
full run. Real finding, verified directly on those 6 episodes (not
re-checked against all 27 originally-classified failures from the
full run): **both models' `tier3_store`/`tier4_multi_step` failures
share a root cause -- neither model's proposals ever include a
`locate` call for the destination/container object, only sometimes
for the primary object being moved.** `qwen2.5:3b`'s proposals stall
immediately at that gap in all 3 episodes checked. `qwen2.5:7b`, in
the 1 of 3 checked episodes that got further, correctly completes
`locate`/`navigate`/`pickup` on the primary object, then fails at
placement by supplying the destination's name to `put_down`/`place`'s
`target` field -- which the action schema defines as the *held
object's* identity, not the destination -- a wrong-value mistake, not
a missing one.

This is treated as a real LLM reasoning/prompting limitation, not a
bug in this dataset's reference planner code -- no precondition
validation was weakened to work around it. See the origin repository's
`experiments/reports/phase_e_milo_benchmark_report.md`'s Addendum 8
for the full real transcripts and methodology, and `docs/roadmap.md`
for the tracked, open finding (including a possible, not-yet-tried
future direction: refining the `react` system prompt to explicitly
require locating both the object and the destination before any
`navigate`/`place` step).

## Versioning

`v1.1` is now itself frozen going forward, following the same policy
`v1.0`'s card states: task_ids, scenes, and success predicates in this
version will not change after this point. A future `v1.2` would extend
again rather than mutate this file.

## License

MIT, matching the origin repository, identical to `v1.0`.

## Citation

Cite the origin repository
([github.com/NaishaShetty/MILO](https://github.com/NaishaShetty/MILO))
and this dataset version (`milo_benchmark v1.1`).
