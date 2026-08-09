# Phase 6.4 -- Evaluation, Hardening & Research Validation: Final Report

Status: **COMPLETE** (evaluation infrastructure and evidence -- see
verdict, section P). The evaluation's own finding about the memory
*system* under test is a qualified **NO** -- see section C/N.

Generated from a real, reproducible run of
`backend/memory_evaluation/run_benchmark.py`. Raw output:
[`experiments/results/benchmark_20260809T120511Z.json`](../results/benchmark_20260809T120511Z.json)
/ [`..._episodes.csv`](../results/benchmark_20260809T120511Z_episodes.csv).
Every number in this report is read directly from that file -- none
were hand-edited, rounded up, or selected after the fact.

---

## A. System summary

Phase 6.1-6.3 built a working, tested, closed causal memory loop:

```
SingleTask -> MemoryAgent.retrieve_relevant_memories() -> RuleBasedPlanner.plan()
    -> ExecutionController.execute_plan() -> TaskRunner.remember_*()
    -> MemoryAgent -> SQLiteMemoryStore + SQLiteVectorStore
```

`orchestration.task_runner.TaskRunner.run(task, memory_enabled: bool)`
already *is* the clean MEMORY_ON/MEMORY_OFF experimental interface
Phase 6.4 section 2 asks for -- `memory_enabled=False` (or
`memory_agent=None`) skips every memory operation; nothing else about
planning/execution/simulator changes. Phase 6.4 did not need to build
this switch; it needed to build a benchmark and a runner *around* it,
and to run real experiments with it.

```
Active planner:        RuleBasedPlanner (deterministic; the only
                        planner whose retrieval-time behavior Phase
                        6.3 implemented -- see limitations, section O)
Memory-enabled path:    TaskRunner.run(task, memory_enabled=True)
Memory-disabled path:   TaskRunner.run(task, memory_enabled=False)
                        (or memory_agent=None)
Simulator:              FakeSimulator (backend/tests/
                        _execution_test_helpers.py) -- deterministic,
                        in-memory, zero AI2-THOR/Unity dependency,
                        matching every existing Phase 5/6 test in this
                        repository. No real-AI2-THOR run was performed.
Task definition:        schemas.task.SingleTask (existing Phase 3
                        schema, reused as-is)
Metrics source:         backend/memory_evaluation/experiment.py
                        (EpisodeResult, built from TaskRunner's own
                        TaskRunResult / latencies_ms)
Randomization source:   none -- the benchmark is fully deterministic
                        (see section J)
```

## B. Experimental methodology

`backend/memory_evaluation/scenarios.py` defines five version-controlled
`BenchmarkScenario`s (one per phase-spec category), each a sequence of
`EpisodeSpec`s (task + `FakeSimulator` scene + optional controlled
failure) run in order against one shared memory subsystem per
condition:

| Category | Scenario | Episodes |
|---|---|---|
| A -- Object Location Recall | `A_object_recall_mug` | find mug twice, unchanged scene |
| B -- Episodic Experience | `B_episodic_experience_mug` | find mug, then a related task (bring mug to table) |
| C -- Failure Recovery | `C_failure_recovery_fridge` | reach fridge (blocked), retry (cleared), same `task_id` |
| D -- Stale Memory | `D_stale_memory_mug` | learn location, then a "soft" move (old receptacle still exists), then a "hard" move (old receptacle removed entirely) |
| E -- Conflicting Memory | `E_conflicting_memory_mug` | two conflicting pre-seeded observations (older/lower-confidence vs newer/higher-confidence), one episode |

`memory_off`: no `MemoryAgent` constructed for the scenario at all.
`memory_on`: one real `MemoryAgent` (`SQLiteMemoryStore` +
`SQLiteVectorStore` + `HashingEmbedder`, under a scenario-scoped
temporary directory) persists across the scenario's own episodes.
Category E's two conflicting memories are seeded via
`MemoryAgent.remember_observation()` -- the same production write path
every real observation uses, never a private/bypass insertion.

Planner: `RuleBasedPlanner` (deterministic, no LLM). Seeds: recorded
per scenario (`1001`-`1005`) for bookkeeping; see section J for why
they do not make this benchmark "repeated trials."

## C. Memory vs No Memory

| Metric | Memory OFF | Memory ON | Difference |
| --- | ---: | ---: | ---: |
| Task Success Rate | 90.0% (9/10) | 80.0% (8/10) | **-10.0 pp** |
| Mean Actions / episode | 2.10 | 3.10 | **+1.00** |
| Mean Planning Time | 0.065 ms | 0.085 ms | +0.020 ms |
| Mean Execution Time | 0.105 ms | 0.126 ms | +0.021 ms |
| Mean Memory Retrieval Time | n/a | 0.361 ms | n/a |
| Mean Memory Write Time | n/a | 1.264 ms | n/a |
| Mean Total Time (all recorded stages) | 0.170 ms | 1.837 ms | +1.667 ms |
| Recovery Rate (Category C) | 1/1 recoverable failure recovered | 1/1 recovered, **and explicitly linked** via `recovered_from`/`recovered_by` | link only under ON |
| Episodes where memory measurably influenced the plan | -- | 6 / 10 | -- |

*N = 10 episode-pairs (5 scenarios x their episode counts), one
deterministic run each condition -- descriptive, not inferential (see
section J).* "Total Time" sums whichever latency stages `TaskRunner`
recorded for that run (`memory_off` never records
`memory_retrieval_ms`/`memory_write_ms` at all, since those calls never
happen -- not because they were fast).

**Headline finding, stated plainly:** on this benchmark, this planner,
and this simulator, enabling persistent memory **reduced** task success
by 10 percentage points and **increased** action count and wall-clock
overhead. This is the honest result of the measurement, not a
mis-scoped benchmark -- see the mechanism in sections F/G below, and
"what changed the outcome" in section N.

## D. Retrieval (Phase 6.2 infrastructure, reused not rebuilt)

`memory_evaluation.run_evaluation` (Phase 6.2's own harness) against
its fixed 9-memory/6-query dataset, `HashingEmbedder`, dimension 512:

| Config | R@1 | R@3 | R@5 | MRR | mean latency |
|---|---:|---:|---:|---:|---:|
| A: vector-only | 0.58 | 0.92 | 1.00 | 0.89 | 0.93 ms |
| B: + confidence | 0.58 | 0.92 | 1.00 | 0.89 | 0.75 ms |
| C: + recency | 0.75 | 1.00 | 1.00 | 1.00 | 0.73 ms |
| D: full hybrid | 0.67 | 1.00 | 1.00 | 0.92 | 0.71 ms |

(Re-measured for this report; matches Phase 6.2's own documented
numbers within normal machine-to-machine latency noise -- Recall/MRR
identical, since this evaluation is itself deterministic.)

## E. Ablation

**Retrieval-only ablation** (table D above) shows ranking-formula
choice affects *rank quality* (R@1/MRR) on the 6-query eval set.

**Task-level ablation** (`task_ablation.py`, both Category A and
Category E, all four `RankingWeights` configs, `memory_on`):

*Category A (one qualifying memory, no competition):* identical
outcome across every config (`success=True`,
`plan_targets[0]=="table"`). Nothing for the ranking formula to
differentiate between -- a control case confirming the ablation
harness itself behaves as expected when there is no real choice to
make.

*Category E (two competing, conflicting memories -- `table`,
confidence 0.6, older; `cabinet`, confidence 0.9, newer, matching
current reality):*

| Config | Plan's first target | Correct (matches current scene)? |
|---|---|---|
| A: vector-only | `table` | **No** |
| B: + confidence | `cabinet` | Yes |
| C: + confidence + recency | `cabinet` | Yes |
| D: full hybrid | `cabinet` | Yes |

This is the ablation's one substantive, real finding in this report:
**with similarity as the only ranking signal, both memories score
identically** (same query, same vector similarity to both "mug
located_on table" and "mug located_on cabinet"), so the result is
decided by the deterministic tie-break
(`(-final_score, -created_at, memory_id)` --
`memory.retrieval.RetrievalEngine`'s own sort key) rather than by
anything meaningful, and in this run it happened to select the
*stale, lower-confidence* memory. Every config that adds confidence
weighting selects the correct, higher-confidence memory instead. All
four configs still complete the task successfully here (both
candidate locations happen to still exist in the scene), but this is
the same failure mode as Category D's hard-stale case waiting to
happen: had the stale "table" memory's location been removed from the
scene (as in Category D), `A_vector_only`'s tie-break-driven choice
would have caused the same kind of task failure the other three
configs would have avoided. Confidence weighting is not a cosmetic
parameter here -- it is the mechanism that keeps a conflicting-memory
scenario from resolving to the wrong fact by coin flip.

## F. Failure Recovery (Category C)

```
Initial failure rate (episode 1, blocked navigate): 100% (both conditions -- identical, controlled)
Recovery rate (episode 2, obstacle cleared, same task_id): 100% (both conditions)
Recovery actions: 2 (identical both conditions)
Repeated failure rate: 0% (both conditions)
```

Memory ON adds **no measurable behavioral difference** in whether or
how fast recovery happens here -- `RuleBasedPlanner` does not currently
reason over `FAILURE` memories at all (only `SEMANTIC`/`USER` location
hints feed the planner; see `rule_based.py`). What memory ON *does* add
is bookkeeping: the recovered episode's `recovered_from` and the
original failure's `recovered_by` metadata are populated and verified
(`test_memory_on_links_recovery_to_the_prior_failure`) -- useful for a
future analysis/reflection layer, not (yet) for changing what the
robot does differently on retry.

## G. Stale Memory (Category D) -- mandatory experiment

This is the most important empirical result in this report, because it
tests a claim Phase 6.3's own documentation makes: that "current
perception overrides stale memory."

```
episode_1_learn_location:  memory ON and OFF both succeed (2 actions) -- baseline
episode_2_soft_stale (mug moved, old receptacle still in scene):
    memory OFF: succeeds, 2 actions (finds mug directly)
    memory ON:  succeeds, 4 actions (wastes 2 actions navigating to the
                stale "table" location first, then still finds the mug)
episode_3_hard_stale (mug moved, old receptacle REMOVED from scene):
    memory OFF: succeeds, 2 actions
    memory ON:  FAILS -- the memory-hinted "locate table" step cannot
                resolve against the live scene (no object of that type
                exists), the step is BLOCKED, and per
                execution.controller.ExecutionController.execute_plan()
                a BLOCKED/FAILED step halts the remaining plan --
                the whole task fails even though the mug itself was
                perfectly reachable.
```

**Verified empirically, not assumed:** `RuleBasedPlanner`'s "current
perception overrides stale memory" branch (`state.object(obj).
is_located`) never fires in this integration, because
`orchestration.task_runner.TaskRunner.run()` always constructs
`WorldState.initial()` -- an empty world state. Vision is not wired
into `TaskRunner` as of Phase 6.3/6.4 (documented as a known limitation
in `docs/phases/phase6_memory.md`'s Phase 6.3 section), so there is no
live perception signal for that override branch to ever see. The
override mechanism is real *code*, and is unit-tested in isolation
(`test_memory_retrieval.py`/planner tests), but this report is the
first evidence of whether it actually protects the *end-to-end* loop
against stale memory -- and it does not, because the perception input
it depends on is never populated by the current integration. This
finding is now locked in as a regression test
(`test_hard_stale_causes_task_failure_under_memory_on`).

## H. Memory Growth / Pollution

```
Total episodes run (all 5 scenarios, memory_on):        10
Successful episodes naming a primary object:             8
Semantic memories created:                                9
Episodic memories created:                                8
Failure memories created:                                 2
Semantic memories per successful object episode:      1.125
```

Growth is controlled (roughly one semantic memory per successful,
object-naming episode, not a per-frame/per-detection dump) -- the
ratio is slightly above 1.0 because Category E seeds two precondition
memories once per scenario (not per episode), a small, known,
documented contributor, not runaway growth. `TaskRunner._form_
observation()`'s "at most one observation per successful run" policy
holds under this benchmark's exercise of it.

## I. Persistence

Not re-implemented in 6.4 -- reused and verified via the existing
automated regression coverage:
`backend/tests/test_orchestration_task_runner.py::
TestPersistenceAcrossRestart` and `TestGoldenMemoryTest` construct a
brand-new `MemoryAgent`/`RetrievalEngine`/`SQLiteMemoryStore`/
`SQLiteVectorStore` against the same on-disk database path after
deleting the originals, and assert the retrieved memory both exists
and changes the resulting plan (`targets[0] == "table"`). Both tests
pass in this report's full suite run (section L). Phase 6.4 added no
new persistence claim beyond what these tests already demonstrate.

## J. Reproducibility

```
git_commit:        None -- this checkout is not a git repository
                    (`git rev-parse HEAD` fails; recorded honestly,
                    never fabricated)
timestamp_utc:      2026-08-09T11:59:35Z
python_version:     3.14.6
platform:           Linux-6.6.87.2-microsoft-standard-WSL2-x86_64
planner:            RuleBasedPlanner
simulator:          FakeSimulator (deterministic; not real AI2-THOR)
embedding_model:    HashingEmbedder (deterministic, offline, lexical)
vector_store:       SQLiteVectorStore
memory_store:       SQLiteMemoryStore
seeds:              A=1001, B=1002, C=1003, D=1004, E=1005
hardware:           dev machine CPU only, no GPU used by this benchmark
```

**Statistical honesty (mandatory disclosure):** every scenario in this
benchmark is fully deterministic -- same planner, same simulator, same
fixed scene data, no LLM call, no randomness anywhere in the loop.
Running the whole suite twice produces byte-identical results (verified
by re-running it during this report's preparation). The comparison in
section C is therefore **descriptive, not inferential**: it reports the
outcome on 5 distinct, independently-designed scenarios (10 episode
pairs), not repeated independent trials of one scenario. No p-value,
confidence interval, or significance claim is made anywhere in this
report, and none should be inferred from the tables above. A future
phase that wants inferential statistics would need either scenario
randomization (varied scene layouts/seeds per trial) or an LLM-backed
planner with sampling variance -- neither is in scope here (section
28's "what not to add").

No separate `experiments/configs/` directory was created: the only
configuration this benchmark has is the scenario suite itself
(`backend/memory_evaluation/scenarios.py`, already version-controlled
Python, not YAML/JSON) and the CLI flags documented in
`run_benchmark.py --help` -- inventing a parallel config file format for
zero additional configurable surface would be exactly the "giant
experiment framework" section 20 warns against.

## K. CI / Docker

**CI:** `.github/workflows/ci.yml` already runs `black --check`,
`ruff check`, `mypy`, and `python -m pytest tests/ -v` from `backend/`
on every push/PR. No workflow changes were needed for Phase 6.4: the
new test file (`backend/tests/test_memory_evaluation_benchmark.py`) is
picked up automatically by the existing `tests/` glob, and the new
`memory_evaluation/` modules pass the existing lint/format/type gates
unmodified (verified locally; see section L). `run_benchmark.py` itself
is a research CLI, not a test -- it is not invoked by CI, matching
`memory_evaluation/run_evaluation.py`'s existing precedent.

**Docker:** `docker/Dockerfile` installs `backend/requirements.txt` and
copies all of `backend/`. Phase 6 (including 6.4) added no new Python
dependency -- `sqlite3` is stdlib and `numpy` (used by
`SQLiteVectorStore`) was already in `backend/requirements.txt` before
Phase 6.2. The existing image therefore already covers Phase 6.4's code
unmodified; no Dockerfile change was made or needed. This was verified
by inspection (dependency diff), not by an actual container build in
this environment.

## L. Tests

```
New tests (this phase):    18  (backend/tests/test_memory_evaluation_benchmark.py)
Existing tests (6.1-6.3):  738
Total:                     756
Passed:                    756
Failed:                    0
Skipped:                   2  (pre-existing, unrelated to Phase 6.4)
```

Full suite: `cd backend && python -m pytest tests/ -v` -- 756 passed, 2
skipped, 0 failed. No Phase 1-6.3 regression.

## M. Quality gates

```
Black:   PASS (228 files, no changes needed after formatting new files)
Ruff:    PASS (0 errors)
Mypy:    PASS (0 errors, 228 source files)
CI:      Not run in this environment (no git remote/Actions runner
         available here); the same commands CI runs were run locally
         and all pass -- see section L.
Docker:  Not rebuilt in this environment; dependency coverage verified
         by inspection (section K).
```

## N. Results interpretation

**What the experiments demonstrate:**
- The `memory_enabled` on/off switch in `TaskRunner` is a real,
  working, controlled experimental interface -- both conditions run
  the identical task/scene/planner/simulator otherwise.
- On this benchmark, `RuleBasedPlanner`'s memory integration
  (`_apply_memory_hint`) *adds* a preliminary locate+navigate step
  rather than replacing the object's own direct grounding step -- so
  it increases action count on every scenario where it fires (A, B, D,
  E), it never decreases it.
- Stale memory can cause outright task failure (Category D, hard
  case), and does so because `TaskRunner` never populates `WorldState`
  from live perception -- the documented "current perception overrides
  stale memory" safeguard is real code but is not actually exercised
  end-to-end by the current integration.
- Conflicting memories are both retrieved and handled safely under the
  default ranking (Category E): the higher-confidence, more-recent
  memory is used, the task succeeds, nothing crashes. The ablation
  (section E) shows this is *not* incidental to this scenario:
  confidence weighting is the specific mechanism responsible --
  removing it (`A_vector_only`) causes the planner to act on the
  stale, lower-confidence memory instead, via an uninformative
  similarity tie rather than a reasoned choice. That misordering did
  not fail this particular scene only because both candidate locations
  happened to still exist in it; combined with Category D's finding,
  an under-confidence-weighted retrieval config in a scene like
  Category D's hard-stale case would reproduce that same failure.
- Failure-recovery bookkeeping (`recovered_from`/`recovered_by`) works
  and is verified, but does not change planner behavior on retry.
- Memory growth is controlled, not per-frame.
- Persistence across restart works (reused Phase 6.3 evidence).

**What the experiments suggest (not proven at this benchmark's scale):**
- The overhead/failure pattern here is likely a property of
  `RuleBasedPlanner`'s specific, narrow memory-hint mechanism
  (insert-before-not-replace), not an inherent property of memory
  itself -- a planner that used a memory hint to *skip* re-locating a
  known-fresh object (rather than always re-verifying via its own
  direct grounding step) might show the opposite result. This
  benchmark does not test that planner, because it does not exist yet.
- A benchmark with a scene where the object itself is hard to find
  directly (unlike `FakeSimulator`'s flat, single-hop object lists,
  where direct grounding is always cheap) might show memory's search
  guidance actually paying for itself in action count. This
  benchmark's scenes are too simple to distinguish that.

**What remains unproven:**
- Any benefit or harm on real AI2-THOR/Unity (this report used
  `FakeSimulator` exclusively, per every other Phase 5/6 test's
  convention).
- Any result under an LLM-backed or ReAct/Behavior-Tree planner (only
  `RuleBasedPlanner` reasons over `memory_context` as of 6.3/6.4;
  see `docs/phases/phase6_memory.md`).
- Behavior at genuinely large, realistic memory scale in a *live*,
  many-session deployment (the memory-size experiment used synthetic
  distractors, not organically accumulated memories).
- Whether the specific confidence values used in Category E (0.6 vs
  0.9) generalize -- a closer confidence gap, or three-way conflicting
  evidence, was not tested.

## O. Limitations

- **Benchmark size**: 5 scenarios, 10 episodes total. Small by design
  (per-scenario hand-authored, version-controlled Python, not a
  synthetic generator) -- sufficient to demonstrate mechanisms, not to
  support population-level claims.
- **Simulator**: `FakeSimulator` only -- deterministic, flat object
  lists, distance-based nearest-match resolution. No occlusion,
  navigation cost, or multi-hop search the real AI2-THOR/Unity
  environment would impose.
- **Planner coverage**: only `RuleBasedPlanner` reasons over memory.
  `BehaviorTreePlanner`/`ReActPlanner` accept and forward
  `memory_context` but do not act on it (documented limitation carried
  over from Phase 6.3, still true).
- **Embedding**: `HashingEmbedder` is lexical/substring, not semantic --
  a synonym query ("beverage" vs "tea") will not match without shared
  tokens (Phase 6.2's own documented limitation, unchanged).
- **Deterministic environment**: no stochastic variation was
  introduced; see section J's statistical-honesty note.
- **No real-robot/real-simulator validation**: everything in this
  report ran against `FakeSimulator`, matching this repository's
  existing testing convention for Phases 5-6, but explicitly not a
  hardware or Unity-simulator benchmark.
- **`WorldState` is not populated from Vision**: the single most
  consequential limitation this report surfaces (section G) --
  fixing it (wiring a live scene graph into `TaskRunner`) is out of
  Phase 6.4's scope (it is a Vision<->Execution integration change,
  not a memory-evaluation change) but is the most direct fix for the
  stale-memory failure mode this report documents.

## P. Phase 6 verdict

```
COMPLETE
```

**Why:** every item in the Phase 6.4 acceptance checklist -- MEMORY_ON/
MEMORY_OFF conditions, a controlled multi-category benchmark, seeds,
an experiment runner, raw + machine-readable result storage, all
required core/memory-validation metrics and experiments (task success,
actions, planning/execution/total time, recovery rate, memory
overhead, retrieval metrics, memory influence, memory-size experiment,
failure-recovery experiment, stale-memory experiment, pollution test,
persistence test) -- was built and exercised against real,
un-cherry-picked data (sections C-I), with 756/756 tests passing and
zero Phase 1-6.3 regressions (section L), all quality gates green
(section M), and the task-level ablation extended to cover both the
control case (Category A) and the genuinely competing-memories case
(Category E) rather than left as a stated gap.

**This is a COMPLETE evaluation, not a COMPLETE memory system.** The
central research question was answered with controlled evidence, and
the honest answer is a qualified **NO** for the current integration:
on this benchmark, persistent memory reduced task success by 10
percentage points and increased action count, because (a)
`RuleBasedPlanner`'s memory hint adds a step rather than replacing one,
and (b) `TaskRunner` never populates `WorldState` from live perception,
so the documented "current perception overrides stale memory"
safeguard does not fire end-to-end -- letting stale memory cause
outright task failure in the hard-stale case (section G), a failure
mode the ablation (section E) shows confidence-weighted ranking
mitigates but does not eliminate. Reporting that finding honestly,
with the mechanism identified and locked into regression tests, *is*
Phase 6.4's deliverable -- per this phase's own governing principle,
a negative result is acceptable; invalid or missing evidence is not.
Fixing the underlying planner/perception limitations this evaluation
surfaced is Phase 6.5+ work, not a precondition for this evaluation
phase's own completion.
