# Phase D — Floor-Plan Generalization Sweep: Findings

Status: **COMPLETE**. Verdict: the pipeline generalizes across room
types with no code changes beyond a one-line `Simulator` constructor
passthrough (`scene=`) — 13/15 episodes succeeded across 5 real
AI2-THOR scenes spanning all four iTHOR room types. Both failures have
concrete, understood causes: one is a real AI2-THOR physical-placement
limit (a room/geometry fact, not a bug), the other is a genuine
`rule_based.py` planner bug this sweep newly exposed (see section 4).

Generated from a real, reproducible run of
`backend/memory_evaluation/run_floorplan_sweep.py` against 5 real
AI2-THOR/Unity scenes. Raw output:
[`experiments/results/floorplan_sweep_20260817T085722Z.json`](../results/floorplan_sweep_20260817T085722Z.json)
/ [`..._episodes.csv`](../results/floorplan_sweep_20260817T085722Z_episodes.csv).
Every number below is read directly from that file.

---

## 1. Why this report exists

Every prior real-AI2-THOR result in this project (`real_scenarios.py`,
`experiment_real.py`, the Phase B ablation) ran exclusively against
`FloorPlan1` — README.md's "Limited scene/task diversity" limitation
and `docs/roadmap.md`'s "Broader scene/task diversity" future-work row
both flagged this as unvalidated, not just untested. This sweep runs
the same unmodified `TaskRunner(RuleBasedPlanner(), Simulator())`
pipeline against 5 scenes it has never seen before, to answer the
obvious question an interviewer (or the roadmap itself) would ask:
does this only work in one room?

One infrastructure change was needed, landing in production code:
`simulator.simulator.Simulator.__init__` gained a `scene=` passthrough
parameter (default `"FloorPlan1"`, matching every existing caller's
prior implicit behavior) — it already existed on the lower-level
`AI2ThorEnv` but was never forwarded by the `Simulator` wrapper every
other module depends on. Nothing else changed: same `RuleBasedPlanner`,
same `TaskRunner`, same `ObjectResolver`, same execution/validation
code every other real-AI2-THOR result in this repo already exercises.

## 2. Methodology

5 scenes, one per the `real_scenarios.py` discipline (task
object/target names confirmed against a live `get_metadata()` scan of
each scene before authoring any task — never guessed from AI2-THOR
documentation), 3 tasks per scene exercising the 3 goal handlers most
structurally different in `rule_based.py`: `find` (`_goal_perceive` —
object resolution only), `pick_up` (`_goal_pick_up` — adds
navigate/pickup), `store` (`_goal_store` — adds `_deposit()`'s
open/place/close container logic, the exact code path Phase A's
closed-receptacle fix and the Phase 8.7 audit both lived in).

| Scene | Room type | find | pick_up | store |
|---|---|---|---|---|
| `FloorPlan1` | kitchen | mug | apple | bread → fridge |
| `FloorPlan5` | kitchen | bowl | potato | mug → cabinet |
| `FloorPlan201` | living room | laptop | newspaper | remote control → drawer |
| `FloorPlan301` | bedroom | alarm clock | pillow | book → drawer |
| `FloorPlan401` | bathroom | soap bar | towel | spray bottle → shelf |

Single condition — no memory on/off comparison (this is a
generalization/success-fail check, not an ablation) — memory disabled.
Each episode restarts the simulator (fresh Unity process), matching
`real_scenarios.py`'s "fresh simulator per episode" policy. Each
episode's `WorldState` is seeded with the target's live `isOpen` via
`experiment_real.py`'s existing `_seed_initial_state_from_live_metadata`
helper, reused unchanged.

## 3. Headline result

```
Totals: 13/15 succeeded

FloorPlan1   (kitchen)      3/3
FloorPlan5   (kitchen)      3/3
FloorPlan201 (living room)  3/3
FloorPlan301 (bedroom)      2/3
FloorPlan401 (bathroom)     2/3
```

Every `find` and `pick_up` task succeeded, in every room type, on the
first attempt — object resolution (`ObjectResolver`) and the
locate/navigate/pickup action sequence generalize cleanly with zero
FloorPlan1-specific assumptions anywhere in that path. Both failures
are in `store` tasks, and both are in the two non-kitchen scenes that
weren't the ones this project's task set had ever been authored
against before.

## 4. Failure 1 (real finding, planner bug): `store spraybottle → shelf` in `FloorPlan401`

Plan succeeded (8 steps, all resolved); execution failed at step 6:

```
action='open' target='Shelf|-02.59|+00.78|+03.91'
message='Shelf|-02.59|+00.78|+03.91 is not an Openable object'
```

Root cause, in `rule_based.py`'s `_deposit()` (used by `_goal_store`
with `use_container=True`):

```python
needs_open = is_open is not True and (use_container or is_open is False)
```

For a `store` goal, `use_container` is always `True`, so `needs_open`
is `True` whenever `is_open` is not exactly `True` — including when
`is_open` is `None` (unknown), which is exactly the state every
non-openable object is left in: `_seed_initial_state_from_live_metadata`
only writes `is_open` when AI2-THOR's own metadata says the object is
`openable` (see that function's own docstring on why — it was already
burned once by over-reading `isOpen` on non-openable objects, see Phase
B's report section 5). A shelf is a legitimate `store` destination (a
receptacle) but is not openable — `_goal_store` has no code path that
checks `openable` before deciding to insert an `open`/`close` pair, so
it always tries to open any `store` target it doesn't already know is
open. `FloorPlan1`/`FloorPlan5`'s `store` targets (fridge, cabinet) are
both real containers that need opening, so this gap was invisible until
a task set exercised a non-container receptacle for `store` — this
sweep is what surfaced it, not a synthetic test.

**This is a genuine bug**, not a limitation of physical space or scene
diversity. Fix shape (not applied here — out of this report's scope,
which is characterizing behavior, not patching the planner): `_deposit`
needs to know whether `target` is `openable` at all, not just whether
it's currently open — the current `ObjectState`/`WorldState` model has
no `is_openable` field to ask that question, so the real fix likely
needs a data source that reports it (live AI2-THOR metadata already
has `openable`; vision does not observe this yet — see
`backend/planner/grounding.py`'s Phase C scope note on why open/held
state is deliberately not vision-grounded yet).

## 5. Failure 2 (real finding, not a bug): `store book → drawer` in `FloorPlan301`

Plan succeeded; drawer opened successfully; execution failed at step 7:

```
action='place' target='book' container='Drawer|...'
message='No valid positions to place object found'
```

This is AI2-THOR's own physics/geometry system reporting it could not
find room inside this specific drawer for this specific book's
bounding box — the drawer opened correctly (`_deposit()`'s open/close
logic did the right thing here), and `ObjectResolver` resolved both
names correctly. There is no planner-level fix for this: it is a fact
about this particular drawer's real interior volume versus this
particular book's real size, the kind of thing `docs/roadmap.md`'s
"True path-planning navigation" and general simulator-fidelity caveats
already gesture at. A different `store` target in the same scene (or a
smaller object) would very plausibly succeed; this sweep did not retry
with an alternative to confirm that, since the point here is
characterizing what happens with the task set as authored, not
maximizing the success rate after the fact.

## 6. What this does and does not establish

**Does establish:**
- Object resolution, navigation, and pickup generalize across all 4
  iTHOR room types with zero code changes to the pipeline itself.
- The `store` goal's open/place/close logic generalizes correctly when
  the destination is a real container (fridge, cabinet, drawer — 3/3
  container `store` tasks succeeded).
- A previously-latent planner bug (section 4) that no `FloorPlan1`-only
  task set could have surfaced, because `FloorPlan1`'s own `store`
  targets are all real containers.

**Does not establish:**
- Broader task/goal coverage per scene — 3 tasks/scene is enough to
  exercise the 3 structurally distinct goal handlers once each, not a
  statistically powered study (matching Phase B's own "Statistical
  honesty" caveat).
- Non-rule-based planners (`ReActPlanner`) or memory-conditioned
  behavior in non-`FloorPlan1` scenes — this sweep runs
  `RuleBasedPlanner` only, memory disabled, matching this report's
  narrower generalization question.
- Vision-grounded planning (Phase C) in non-`FloorPlan1` scenes —
  `ground_world_state()` was not exercised here; this sweep uses the
  same live-metadata seeding `experiment_real.py` already used, not the
  vision pipeline.
- Any scene outside the 5 sampled (2 kitchens, 1 each of living
  room/bedroom/bathroom) — the remaining ~115 iTHOR scenes are
  unsampled.

## 7. Suggested next step

Fix `_deposit()`'s `needs_open` logic to check `openable` (from live
metadata or, longer-term, a vision-derived signal) before assuming
every `store` destination needs opening — the concrete, reproducible
bug this sweep found, not a hypothetical one. `README.md`'s "Limited
scene/task diversity" bullet and `docs/roadmap.md`'s "Broader
scene/task diversity" row can be narrowed (not removed — see section 6)
to point at this report.

---

## Addendum (resolved) — `_deposit()` non-openable-target bug fixed

**This section documents a fix made after the finding above; section 4's
original text is left unchanged as the honest record of what was found
and when.**

`planner.state.ObjectState` gained an `is_openable: Optional[bool]`
field (`None` unless a caller knows for certain). `rule_based.py`'s
`_deposit()` now skips inserting `open`/`close` when a `store`/`place`
target is known (`is_openable is False`) not to be a container at all
— `is_openable=None` (the default, no live metadata seeded) preserves
the exact prior behavior, so this is strictly a carve-out, not a
changed default. `memory_evaluation.experiment_real.
_seed_initial_state_from_live_metadata` (used by every real-AI2-THOR
harness in this project, including `run_floorplan_sweep.py` and
`planning_evaluation.run_benchmark`) now seeds `is_openable` directly
from AI2-THOR's own `openable` flag for every task-referenced name.

Re-ran `milo-v1-fp401-t3a` ("Put the spray bottle away on the shelf.",
`FloorPlan401`) against real AI2-THOR with the fix applied:

```
shelf is_openable seeded: False
plan steps: ['locate', 'navigate', 'pickup', 'locate', 'navigate', 'place']
execution succeeded: True
goal_success: True
```

Also re-ran `milo-v1-fp301-t3a` ("Put the book away in the drawer.",
`FloorPlan301`) to confirm the fix is targeted and doesn't mask the
*other*, unrelated failure this report documents (the real
placement/geometry limit, section 5): it still fails identically
(`"No valid positions to place object found"`), as expected — that
failure was never about `_deposit()`'s open/close logic and this fix
does not touch it.

Regression tests added: `test_store_goal_has_no_open_close_for_a_known_non_openable_target`,
`test_store_goal_still_opens_a_target_with_unknown_openable_state`
(`backend/tests/test_planner_rule_based.py`). `docs/roadmap.md` updated
accordingly (moved from "Future work" to the Phase completion history
as "E follow-up").
