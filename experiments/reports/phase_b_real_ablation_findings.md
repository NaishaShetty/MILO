# Phase B — Real AI2-THOR Memory Ablation: Findings

Status: **COMPLETE**. Verdict: the FakeSimulator benchmark's headline
"memory reduced success 90%→80%" finding does **not** reproduce under
real AI2-THOR — not because it was wrong, but because its precondition
never occurs in real conditions. See section 4 for what actually
explains the real result.

Generated from a real, reproducible run of
`backend/memory_evaluation/run_ablation_real.py` against a real
AI2-THOR/Unity instance (`FloorPlan1`) and a real, learned sentence
embedding model. Raw output:
[`experiments/results/real_ablation_20260817T074835Z.json`](../results/real_ablation_20260817T074835Z.json)
/ [`..._episodes.csv`](../results/real_ablation_20260817T074835Z_episodes.csv).
Every number below is read directly from that file — none were
hand-edited, rounded up, or selected after the fact. An earlier run
that same session was discarded after its own numbers exposed a bug in
this harness's state-seeding helper (see section 5) — that run's
output files were deleted rather than kept alongside a caveat, since
they measured the bug, not the system.

---

## 1. Why this report exists

`docs/roadmap.md`'s "Future work" table and the README's Known
Limitations both flagged the same caveat on the Phase 6.4 memory
benchmark: it ran entirely against `FakeSimulator` (a deterministic,
in-memory scene fake) and `HashingEmbedder` (a deterministic lexical
embedder), not real AI2-THOR or a learned model. That is good research
hygiene — the limitation was documented, not hidden — but it meant the
"memory reduced success 90%→80%" result described a simplified
harness, not the full stack. This phase closes that gap: same kind of
memory_on vs memory_off comparison, run for real.

Two things changed for this phase, both landing in production code
paths (not just this benchmark):

1. **Real simulator**: `simulator.simulator.Simulator` (real
   AI2-THOR/Unity), not `FakeSimulator`. See
   `backend/memory_evaluation/experiment_real.py`.
2. **Real embedder**: `memory.embeddings.SentenceTransformerEmbedder`
   (`sentence-transformers/all-MiniLM-L6-v2`, loaded via plain
   `transformers.AutoModel`/`AutoTokenizer` — no new dependency), not
   `HashingEmbedder`. Verified semantically ("mug"/"cup" score more
   similar than "mug"/"airplane" — a distinction the lexical embedder
   cannot make); see `backend/tests/test_memory_embeddings.py`'s
   `TestSentenceTransformerEmbedder`.

A third, smaller change made both of the above possible: `TaskRunner.
run()` gained an opt-in `initial_state` parameter so this harness could
seed each episode's `WorldState` with the destination's REAL, live
`isOpen` (a "live AI2-THOR metadata scan by name" — the narrower
alternative to full Vision-grounded `WorldState` the README's
Limitations already named) before planning. Without it, the Phase A
closed-receptacle fix in `rule_based.py`'s `_deposit()` would have had
no real data to act on in this harness, since `WorldState.initial()`'s
default leaves every object's `is_open` unknown.

## 2. Methodology

`backend/memory_evaluation/real_scenarios.py` defines 7 scenarios / 16
episodes, all against the same real `FloorPlan1` scene (restarted —
fresh Unity process — between episodes, since this project's
`Simulator` has no object-teleportation capability to give each episode
a distinct scene the way `FakeSimulator` can):

| Category | Scenario | Episodes | Purpose |
|---|---|---|---|
| A — Object recall | `RA_object_recall_mug` | find mug twice | memory-hint mechanism, repeat visit |
| B — Episodic experience | `RB_episodic_experience_bowl` | find bowl, then pick it up | memory-hint mechanism, related task |
| C — Closed receptacle | `RC_closed_receptacle_apple_cabinet` | place apple in cabinet, twice | Phase A fix + real physics |
| C — Closed receptacle | `RC2_closed_receptacle_egg_fridge` | store egg in fridge, twice | second container/object pair |
| D — Non-container place | `RD_non_container_place_mug_countertop` | place mug on countertop, twice | fix must NOT over-trigger |
| E — Natural failure | `RE_natural_failure_open_apple` | open the apple (not openable), twice | real execution failure, no fake hook needed |
| F — Object variety | `RF_object_sweep` | pick_up/find/open/store across 4 distinct objects | breadth |

`memory_off`: no `MemoryAgent` constructed. `memory_on`: one real
`MemoryAgent` (`SQLiteMemoryStore` + `SQLiteVectorStore` +
`SentenceTransformerEmbedder`) persists across a scenario's own
episodes, exactly `run_scenario`'s existing contract. Planner:
`RuleBasedPlanner` (deterministic, no LLM) — the only planner whose
retrieval-time behavior consumes memory as of this pass (see
`backend/planner/react.py` for the separate fix that threads memory
into the ReAct/LLM planner's prompt, evaluated independently, not part
of this ablation).

**Statistical honesty**: 16 episodes is a first real number against
production conditions, not a statistically powered study — a real
AI2-THOR mission costs real wall-clock seconds per action, so running
enough repeats for a confidence interval is future work. Every number
below is descriptive over these 16 episode pairs, not a p-value/CI
basis. Real AI2-THOR is also not perfectly deterministic run to run
(pose/physics settling) the way `FakeSimulator` is.

## 3. Headline result

```
Episode pairs: 16
Success rate   OFF=87.50%  ON=87.50%   Delta=+0.0pp
Mean actions   OFF=4.69    ON=4.69
Episodes where success flipped between conditions: 0
Episodes where memory measurably influenced the plan: 0
```

Zero delta on every metric. 14/16 episode pairs succeeded in both
conditions; the remaining 2 (`RE_natural_failure_open_apple`, both
episodes) failed in both conditions for the same real reason — AI2-THOR
correctly rejects `OpenObject` on the apple, which is not an openable
type. No episode's outcome depended on whether memory was on or off.

Mean latency overhead of `memory_on`: `memory_retrieval_ms` averaged
5.2ms/episode, `memory_write_ms` averaged 9.7ms/episode — both trivial
next to `execution_ms` (~542ms/episode, dominated by real AI2-THOR
action dispatch). Memory is cheap here; it is just inert.

## 4. Why the FakeSimulator finding didn't reproduce — the real finding

The Phase 6.4 FakeSimulator benchmark's 90%→80% result was driven
entirely by `planner.rule_based._apply_memory_hint()`: when a
retrieved `SEMANTIC`/`USER` memory names a location for the task's
object (predicate `located_on`/`located_in`/etc.), the rule-based
planner inserts an extra `locate`+`navigate` pair for that location
ahead of the object's own steps — sometimes wasted (if the hint is
stale), sometimes helpful, per that benchmark's own category design.

That mechanism requires a `SEMANTIC` "location" memory to exist.
`orchestration.task_runner.TaskRunner._form_observation()` is the only
thing that forms one, and it triggers only when the task's object
"resolves to a live simulator object AND that object's AI2-THOR
`parentReceptacle` metadata names another live object." Traced directly
against this run:

```python
>>> sim.get_metadata()["objects"]  # FloorPlan1, real AI2-THOR
Apple  parentReceptacle = None
Bowl   parentReceptacle = None
Egg    parentReceptacle = None
Mug    parentReceptacle = None
Pot    parentReceptacle = None
Potato parentReceptacle = None
Spoon  parentReceptacle = None
```

Every small, pickupable object in this scene's default layout has
`parentReceptacle: None` — AI2-THOR does not register a
parent/child physics relationship for an object simply resting on a
surface; that field is populated for objects explicitly placed inside
a container object at scene-init, not for loose tabletop items. So
`_form_observation()`'s trigger condition never held, for any object,
in any episode of this run. Confirmed directly: every `memory_on`
episode retrieved exactly the prior episode's `EPISODIC` memory
(`memory_context_count` 1–2 per repeat episode — memory retrieval and
formation both worked), but `observation_memories` was empty in every
single case. No `SEMANTIC` location memory was ever available to
retrieve, so `_apply_memory_hint()` had nothing to match against, so
the plan's shape — and therefore everything downstream (actions taken,
success/failure) — was byte-for-byte identical between `memory_on` and
`memory_off` on every episode. `episodes_where_memory_influenced_plan:
0` is not a bug in the measurement; it is the accurate readout of a
mechanism that structurally could not fire here.

**This is the real, reproducible finding of Phase B**: the
memory-conditioned location-hint mechanism is implemented correctly
and is proven to change planning behavior under `FakeSimulator` (whose
hand-authored `EpisodeSpec.objects` dicts set `parentReceptacle`
directly) — but it is currently inert under real AI2-THOR's default
object placement, because the one write path that could produce a
qualifying memory depends on simulator ground truth
(`parentReceptacle`) that ordinary loose objects don't carry. The
gap is not in the planner or the memory system's ranking/retrieval
logic; it is in `_form_observation()`'s single signal for "where is
this object" — a `parentReceptacle` check that is too narrow for real
scenes. A more robust real-conditions signal (e.g. nearest-surface
proximity, or a `receptacleObjectIds` containment check queried from
the container's side rather than the object's) would very plausibly
let this mechanism engage under real AI2-THOR too — untested here,
flagged as the natural next step.

## 5. A harness bug this run caught (and fixed) along the way

The first attempt at this run produced `RD_non_container_place_mug_
countertop` failing in **both** conditions with AI2-THOR rejecting
`OpenObject` on the countertop ("CounterTop ... is not an Openable
object"). Root cause: this harness's `_seed_initial_state_from_live_
metadata()` (in `experiment_real.py`) read `isOpen` directly from
AI2-THOR's metadata without checking the `openable` flag first — and
AI2-THOR reports `isOpen: False` on **every** object, including
non-openable ones, not `None`/absent. That seeded the countertop's
`WorldState.is_open` as `False` (a false "closed container" signal),
which correctly (per its own contract) made `rule_based.py`'s
`_deposit()` insert an `open` step for what it was told was a closed
receptacle — a real, physically-caused failure this harness
manufactured, not a planner defect. Fixed by only trusting `isOpen`
when `openable` is also true; the discarded first run's output files
were removed rather than kept as a caveat, since they measured this
bug. Left as a comment directly in `_seed_initial_state_from_live_
metadata()`'s docstring so it isn't rediscovered the hard way again.

This is also, independently, a second confirmation that the Phase A
`_deposit()` fix works exactly as designed: given accurate `is_open`
information, it inserts `open`/`close` for a genuinely closed
receptacle (`RC`/`RC2`, both succeeded, both conditions, both
episodes — the exact scenario shape the Phase 8.7 audit's live mission
reproduced as a failure) and does **not** insert them for a
non-container destination once the seeding bug was fixed (`RD`,
6-step plan, no spurious `open`/`close`, succeeded in both
conditions).

## 6. A second bug this run caught, upstream of the ablation itself

While investigating an early single-scenario smoke test that reported
`memory_used_in_plan=True` for an episode whose plan visibly had NOT
changed shape, `memory_evaluation/experiment.py`'s
`_memory_was_used_in_plan()` was found to not match its own docstring:
it claimed to check "the plan's first target is not the task's own
primary object" but its actual implementation was
`memory_context_count > 0 and len(plan_targets) > 0` — true whenever
*any* memory was retrieved for a non-empty plan, regardless of whether
the plan's shape changed at all. Fixed (now takes the task's primary
object and actually compares it against the plan's first target,
matching the docstring); the fix applies to both the FakeSimulator
benchmark and this real ablation, since both share the same function.
Re-running the FakeSimulator benchmark after the fix reproduces the
same 90%→80% / 5-of-10-pairs-influenced result as before — the fix
corrects a real measurement bug without changing that benchmark's
headline finding, since the bug only ever over-counted, and the
over-counted cases happened to coincide with genuinely-influenced ones
in that particular benchmark.

## 7. What this does and does not establish

**Does establish**: the closed-receptacle planner fix (Phase A) is
real and works end to end against real AI2-THOR physics, not just
symbolically. The real, learned embedder is wired up correctly and is
semantically meaningful (verified independently in
`test_memory_embeddings.py`). Memory's retrieval/write overhead is
small under real conditions. Real AI2-THOR's default object placement
does not populate the one signal (`parentReceptacle`) this project's
memory-conditioned planning currently depends on for loose objects,
so — as deployed today, against this scene — memory changes latency,
not task outcomes.

**Does NOT establish**: that memory-conditioned planning "doesn't
work" in general, or that the original FakeSimulator finding was
wrong — it accurately described its own (documented) harness. It also
does not establish what would happen with a scene where objects DO
carry real `parentReceptacle` metadata (e.g. objects placed inside a
cabinet/drawer at scene-init), or at a larger episode count.

## 8. Suggested next step

Broaden `TaskRunner._form_observation()`'s location signal beyond
`parentReceptacle` (e.g. nearest-receptacle-by-distance, or scanning
every receptacle's own `receptacleObjectIds` for the target instead of
reading the object's own `parentReceptacle`) and re-run this same
ablation unchanged — `real_scenarios.py`'s Category A/B are already
built to demonstrate the hint mechanism the moment a qualifying memory
exists to retrieve.
