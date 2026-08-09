# Phase 5 -- Execution & Action Control

Status: complete.

## Goal

Turn a validated Phase 4 `Plan` (an ordered sequence of abstract
`PlanStep`s -- `PlanStep(action="navigate", target="apple")`) into
actual AI2-THOR behavior, step by step, with explicit state tracking,
precondition checking, result validation against simulator ground
truth, structured failure handling, and a clean execution record --
without the Planner ever knowing AI2-THOR exists, and without ever
treating a simulator call's return value as automatically successful.

## Architecture map

```
Existing Planner (backend/planner/)
        |  Plan (PlanStep[])
        v
[Phase 5 integration point: backend/execution/]
        |
        v
Existing Simulator Abstraction (backend/simulator/)
        |
        v
AI2-THOR
```

Every arrow above is a real, one-directional dependency:
`backend/planner/` never imports `backend/simulator/` (verified by
that package's own test suite running with zero AI2-THOR dependency);
`backend/execution/` imports `backend/planner/` (to reuse its action
registry/state/models) and `backend/simulator/` (through
`Simulator`, never `ai2thor.controller` directly), and nothing
downstream of Execution reaches back up into it.

```
Planner            -- WHAT should the robot do?    -> abstract PlanStep
Execution (Phase 5) -- HOW do I do it?              -> concrete Action + dispatch
Simulator            -- perform this low-level action -> AI2-THOR call
```

## What already existed (audited before writing any Phase 5 code)

- `backend/simulator/simulator.py` / `ai2thor_env.py` / `actions.py` --
  the simulator abstraction, pre-Phase-5 covering only movement/look
  primitives (`move_ahead`, `turn_left`, `turn_right`, `look_up`,
  `look_down`) plus `get_rgb`/`get_metadata`/`get_depth`. No
  manipulation actions (`pickup`, `open`, `close`, `put`) and no
  navigation-to-object capability existed yet.
- `backend/planner/models.py` -- `PlanStep`/`Plan`/`StepStatus`/
  `PlanStatus`, already documented as mutable, with `PlanStep.status`
  explicitly described as "updated in place... as Phase 5 executes
  it." Reused directly; not duplicated.
- `backend/planner/actions.py` -- `ACTION_REGISTRY`, one `ActionSpec`
  per abstract action with `Precondition`s and an effect function
  against `WorldState`. Reused directly by
  `execution/preconditions.py` and `execution/controller.py`.
- `backend/planner/state.py` -- `WorldState`, the symbolic simulator
  Phase 4 already validates plans against. Reused directly as the
  state Execution replays a plan's effects into as it actually runs.
- `backend/api/app.py` -- already owned the `Simulator` lifecycle
  (`app.state.simulator`, gated by `VISION_ENABLE_SIMULATOR`) for the
  Vision API; the Execution API reuses that exact same instance rather
  than constructing a second one.

**Conclusion of the audit:** no execution-related components existed
yet. The simulator abstraction needed extending (new manipulation/
navigation methods), the planner's lifecycle enums needed two small
additive members, and everything else in this phase is new, isolated
to `backend/execution/`.

## New components

| Component | File | Responsibility |
|---|---|---|
| `ActionType`, `Action`, `ActionResult` | `execution/models.py` | Standardized, typed, serializable action model (section 2). |
| `ExecutionStatus`, `ExecutionEvent`, `StepExecutionRecord`, `ExecutionRecord` | `execution/models.py` | Execution-level state machine + history (sections 5, 11, 12). |
| `ExecutionErrorCode`, `ExecutionError` | `execution/errors.py` | Closed, machine-readable error taxonomy (section 23). |
| `ObjectResolver` | `execution/resolver.py` | `PlanStep.target` (human name) -> live AI2-THOR `objectId`. |
| `ActionDispatcher` | `execution/dispatcher.py` | The single centralized `Action` -> `Simulator` method translation boundary (section 3). |
| `PreconditionChecker` | `execution/preconditions.py` | Symbolic (reused Phase 4) + grounded (live-scene) precondition checks (section 6). |
| `ResultValidator` | `execution/validator.py` | Never trusts a simulator response blindly; checks `lastActionSuccess` AND ground-truth postconditions (section 8). |
| `ExecutionController` | `execution/controller.py` | Sequential executor: retries, timeouts, cancellation, state updates (section 4). |
| `StartExecutionRequest` | `api/models/execution.py` | HTTP request envelope. |
| Execution router | `api/routes/execution.py` | `/api/v1/execution/{start,{id},{id}/cancel,{id}/steps,{id}/events}`. |
| `ExecutionPanel`, `ExecutionStepsList`, `ExecutionLog` | `frontend/src/components/` | Live execution UI, rendered beneath a generated plan. |

Simulator extensions (not new components, but new capability on
existing ones): `Simulator`/`AI2ThorEnv` gained `pickup_object`,
`put_object`, `open_object`, `close_object`, `navigate_to`, and
`move_back`; `simulator/actions.py` gained the matching AI2-THOR action
name constants (`PickupObject`, `PutObject`, `OpenObject`,
`CloseObject`, `GetInteractablePoses`, `TeleportFull`, `MoveBack`).

## Action lifecycle

```
Plan Step
   |
   v
Resolve objectId (ObjectResolver, against live Simulator.get_metadata())
   |
   v
Precondition Check (PreconditionChecker: symbolic ACTION_REGISTRY + grounded existence)
   |  (unmet -> StepStatus.BLOCKED, ExecutionError, plan halts)
   v
Dispatch (ActionDispatcher -> exactly one Simulator method call, with bounded retry + optional timeout)
   |
   v
Simulator -> AI2-THOR
   |
   v
Result Validation (ResultValidator: lastActionSuccess AND ground-truth postcondition)
   |  (failed -> StepStatus.FAILED, ExecutionError, plan halts)
   v
State Update (WorldState effect applied, PlanStep.status = COMPLETED)
   |
   v
Next Step (or SKIPPED if the plan already halted)
```

## Failure lifecycle

```
Action dispatched
   |
   v
Failure (precondition rejection, simulator-reported failure, timeout,
         or a ground-truth postcondition mismatch)
   |
   v
Structured ExecutionError (ExecutionErrorCode + message + step_id + action + recoverable hint)
   |
   v
PlanStep.status = FAILED (or BLOCKED for a precondition rejection)
Plan.status = FAILED; ExecutionRecord.status = FAILED
   |
   v
ExecutionEvent appended (status="failed"/"blocked", error_code, message)
   |
   v
Every remaining step marked SKIPPED -- execution halts, never continues
past a step whose preconditions Phase 4's own dependency model already
knows cannot hold
   |
   v
Exposed via GET /api/v1/execution/{id} (and .../events, .../steps) for
the API/frontend, and structured cleanly enough for a future
replanning/Memory consumer -- but this phase never acts on it itself
```

## Error taxonomy

`INVALID_ACTION`, `INVALID_PARAMETER`, `PRECONDITION_FAILED`,
`OBJECT_NOT_FOUND`, `TARGET_NOT_FOUND`, `OBJECT_NOT_REACHABLE`,
`NAVIGATION_FAILED`, `SIMULATOR_ERROR`, `ACTION_TIMEOUT`,
`EXECUTION_CANCELLED`, `VALIDATION_FAILED`, `UNKNOWN_ERROR` --
`execution/errors.py`. Only `SIMULATOR_ERROR`, `NAVIGATION_FAILED`,
`OBJECT_NOT_REACHABLE`, and `ACTION_TIMEOUT` are ever retried (bounded,
explicit, off by default) -- every other code reflects a defect in the
plan/request itself that a retry cannot fix.

## Retries, timeouts, cancellation

- **Retries**: `max_step_retries` (default `0`). Only transient-looking
  error codes are retried, up to a fixed ceiling. `ActionResult.retry_count`
  always reports how many were actually used -- never hidden, never
  unbounded.
- **Timeouts**: `step_timeout_s` (default `None` = no timeout). Each
  dispatched simulator call runs on a single-worker thread pool with a
  bounded `future.result(timeout=...)` wait; exceeding it reports
  `ACTION_TIMEOUT`, never a hang.
- **Cancellation**: `ExecutionController.cancel()`/`.stop()` set a
  `threading.Event` checked at each step boundary. `POST
  /api/v1/execution/{id}/cancel` reaches a running controller because
  `POST /start` runs `execute_plan()` on a background thread (see
  `api/routes/execution.py`'s docstring for why).

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/execution/start` | Begin executing a validated `Plan`; 202, returns immediately with the initial `ExecutionRecord`. 503 (no simulator) / 409 (another execution running) / 422 (plan not executable). |
| `GET /api/v1/execution/{execution_id}` | Current `ExecutionRecord`. 404 if unknown. |
| `POST /api/v1/execution/{execution_id}/cancel` | Request cancellation. |
| `GET /api/v1/execution/{execution_id}/steps` | Per-step results. |
| `GET /api/v1/execution/{execution_id}/events` | Structured event log. |

## Testing strategy

- **Fast, deterministic unit/integration tests**
  (`backend/tests/test_execution_*.py`, `test_api_execution.py`) --
  zero AI2-THOR dependency, run in CI as part of `pytest tests/`. Use
  `FakeSimulator` (`backend/tests/_execution_test_helpers.py`), a
  minimal in-memory stand-in implementing the exact same method surface
  as `Simulator`.
- **Real AI2-THOR end-to-end tests**
  (`backend/simulator/test_execution_e2e.py`) -- opt-in via
  `RUN_SIMULATOR_TESTS=true`, never run automatically (mirrors
  `VISION_ENABLE_SIMULATOR`/`RUN_LLM_SMOKE_TESTS`/`RUN_LLM_BENCHMARK`).
  Covers movement, rotation, pickup, open, put, and the full multi-step
  "store the apple in the refrigerator" task through the real
  `ExecutionController`.

## Post-implementation fixes (found by the real-AI2THOR e2e suite)

`simulator/test_execution_e2e.py` earns its place here: running it
against a real AI2-THOR instance immediately caught a real bug that
every mocked/`FakeSimulator` test in this phase's own suite could not
see, since `FakeSimulator` was written correctly from the start.

- **`Simulator.move_ahead()`/`move_back()`/`turn_left()`/
  `turn_right()`/`look_up()`/`look_down()` never returned the AI2-THOR
  event.** A pre-existing Phase 1 bug (`return` was simply missing --
  `get_rgb()`/`get_metadata()`/`get_depth()` just below them did have
  it), silently masked ever since because nothing before Phase 5 ever
  consumed a movement call's return value
  (`simulator/test_navigation.py` only calls them for their side
  effect). `execution.dispatcher.ActionDispatcher`/
  `execution.validator.ResultValidator` are the first real callers that
  need the event back to check `lastActionSuccess`; against a real
  simulator this surfaced as `AttributeError: 'NoneType' object has no
  attribute 'metadata'` on the very first `move_ahead`/`turn_left`
  call. Fixed in `simulator/simulator.py` by adding the missing
  `return` to each -- see that file's own docstring note.
- **`PickupObject`/`PutObject`/`OpenObject` needed `forceAction=True`.**
  AI2-THOR's default interaction checks are strict physics/visibility
  checks tuned for careful manual placement; a `navigate_to()` teleport
  pose that AI2-THOR itself calls "interactable" is not always close
  enough to satisfy them (this is what real AI2-THOR's `PutObject`
  reported as an ordinary `lastActionSuccess=False`, not a bug in the
  Phase 5 dispatch/validation logic around it -- `ResultValidator`
  correctly reported it as a failed action). `forceAction=True` is the
  standard AI2-THOR idiom for an agent that is not also simulating a
  full robotic arm's grasp/placement planning (out of this project's
  scope); added to `pickup_object()`, `put_object()`, `open_object()`,
  and `close_object()` in `simulator/ai2thor_env.py`.

Neither of the two fixes above required any change to
`backend/execution/`'s own logic -- both were latent/expected gaps one
layer down in `backend/simulator/`.

A third issue -- this one inside `backend/execution/` -- surfaced only
once `test_a`-`test_e` were passing and the *full* multi-step plan
(`test_f`) was run: `Navigate to refrigerator` was reported `BLOCKED`
with `OBJECT_NOT_FOUND`, even though the scene's default `FloorPlan1`
clearly has a fridge. Diagnosis (`ExecutionRecord.step_results`, per
step) showed every earlier step succeeding and pinned the failure
precisely to `ObjectResolver.resolve("refrigerator", metadata)`
returning `None`. Cross-referencing `test_d`/`test_e` (which use
`"Fridge"` directly and pass) confirmed the cause: AI2-THOR's real
`objectType` for this object is `"Fridge"`, not `"Refrigerator"` --
the exact word this project's own README canonical demo task
(`target="refrigerator"`) and the Planner's `PlanStep.target` use.
`ObjectResolver`'s plain case-insensitive match had no way to bridge
that gap. Fixed with a small, explicit, confirmed-only alias table
(`_ALIASES = {"refrigerator": "fridge"}`, matched in both directions)
-- not fuzzy/similarity matching, which could silently resolve a step
against the wrong object; see `resolver.py`'s own docstring for why
only *confirmed* aliases belong there. Covered by
`backend/tests/test_execution_resolver.py`.

All three fixes were found by the real end-to-end suite, exactly the
"strongest available verification" that suite exists to provide --
`backend/execution/`'s own mocked test suite could not have caught any
of them, since `FakeSimulator` never had these particular real-world
quirks to begin with.

**Verified:** with all three fixes applied, `RUN_SIMULATOR_TESTS=true
python -m pytest simulator/test_execution_e2e.py -v` passes all 6
tests against a real AI2-THOR/Unity instance, Test F included -- the
full Planner -> Execution -> AI2-THOR -> validated-result pipeline for
the README's headline "store the apple in the refrigerator" task,
confirmed working end to end, not just against `FakeSimulator`.

## Known limitations

- **`navigate_to()` is teleport-based, not path-planning.** It uses
  AI2-THOR's `GetInteractablePoses` + `TeleportFull` -- a standard
  AI2-THOR idiom that respects scene geometry (a returned pose is only
  interactable if the object is genuinely reachable/visible from it)
  but does not simulate a walked path. True navigation research is
  explicitly out of scope for this phase.
- **Object resolution is a live metadata name match, not
  Vision-grounded.** `ObjectResolver` matches `PlanStep.target` against
  `Simulator.get_metadata()["objects"]` by `objectType` (plus a small,
  confirmed-only alias table for known AI2-THOR naming divergences,
  e.g. `"refrigerator"` <-> `"Fridge"` -- see "Post-implementation
  fixes" above), picking the nearest candidate. It does not yet consult
  Vision's `SpatialScene`/tracked objects (Phase 3.x) -- see
  `resolver.py`'s docstring for why this seam is deliberately narrow
  and swappable. A task/plan target whose wording diverges from
  AI2-THOR's `objectType` and has no alias entry yet will still fail to
  resolve; a Vision-grounded resolver is the real fix, not a growing
  alias table.
- **`put_down` (a generic "set the held object down here" action) has
  no simulator-groundable target.** AI2-THOR's `PutObject` always
  targets a specific receptacle id; a `put_down` `PlanStep` maps to
  `ActionType.LOCATE` (a no-op) rather than being silently
  mis-dispatched. `place` (with an explicit `container`) is fully
  supported.
- **No visual/perception-based result verification.** `ResultValidator`
  checks AI2-THOR's own simulator ground truth (`lastActionSuccess`,
  `isOpen`, `inventoryObjects`); it deliberately does not re-run
  detection to visually confirm a state change, per this phase's scope
  boundary with Vision.
- **No dynamic replanning.** A failed plan halts, with the failure
  fully structured and exposed -- no automatic repair/replan is
  attempted. See the README's Future Phases section.
- **Single execution at a time.** `Simulator` owns exactly one AI2-THOR
  subprocess; the Execution API rejects a second concurrent `start`
  with `409` rather than racing two controllers against it.

## Phase 6 readiness

`ExecutionRecord` (plan/task id, per-step results with full
`ActionResult`/`ExecutionError` detail, a timestamped `ExecutionEvent`
log, start/finish timestamps) is a clean, storage-agnostic,
JSON-serializable record -- exactly the shape section 26's example
episodic-experience JSON describes. A future Phase 6 Memory Agent can
consume it via the API (or, later, directly) without this package
changing at all; this phase deliberately does not persist it to a
database or implement any memory/reflection logic itself.
