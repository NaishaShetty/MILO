# Shared foundation: action registry, success predicates, mission traces

## Action registry (`backend/planner/actions.py`)

One typed table of every action a plan may use. Each entry has typed arguments, preconditions (checked against the symbolic `WorldState`), effects, and an `executable` flag. The executor's mapping (`execution/controller.py`) covers exactly the executable entries (a test enforces this):

| Plan action | Arguments | Executor action |
|---|---|---|
| `locate` | target: object | (symbolic, no simulator call) |
| `navigate` | target: object | `NAVIGATE` (teleport to an interactable pose) |
| `pickup` | target: object | `PICKUP` |
| `place` | target: object, container: receptacle | `PUT` |
| `put_down` | target: object | `DROP` (new) |
| `open` / `close` | target: openable | `OPEN` / `CLOSE` |
| `turn_on` / `turn_off` | target: toggleable | `TURN_ON` / `TURN_OFF` |
| `push` | target: object | `PUSH` (new, AI2-THOR `PushObject`) |
| `look_around` | none | `LOOK_AROUND` (new, four 90-degree turns) |
| `act` | target, action: text | none: a planning placeholder, `executable=False` |

Previously `put_down` and `act` were silently executed as a no-op `locate` and reported success. Now `put_down` really drops the object. A plan containing `act` (a goal no planner knows, such as "clean the window") is refused before anything runs, and MILO says "I don't have a way to do 'clean' yet." Roadmap Phase 2's novel-task solver is where such goals will go next.

## Success predicates (`backend/verification/predicates.py`)

Checkable goal conditions read from the simulator's own object metadata: `held`, `hand_empty`, `in_receptacle`, `is_open`, `is_closed`, `toggled_on`, `toggled_off`, `visible`, `near`. Each returns `ok` plus a plain reason ("the mug is not in/on the fridge"). They round-trip through JSON so a planner can state them. `goal_predicates(task)` gives the success conditions for each task-library goal.

At the end of every mission the orchestrator checks them (`MILO_GOAL_CHECK=off|report|enforce`, default `report`). In `report` mode the results go on the task as `verification` and a failed check becomes one of MILO's thoughts. In `enforce` mode a failed check also turns the mission into a failure.

Measured on 300 held-out synthetic missions (`python -m verification.eval_goal_check`): 213 reported successes had a checkable goal. The world contradicted 3 of them, all `find` tasks with an injected wrong detection, where MILO said it found an object that is not in view. Enforcement is left opt-in until it has been checked on real AI2-THOR runs.

## Mission traces (`backend/tracelog/`)

A versioned SQLite store (`MILO_TRACE_DB`, default `data/traces.db`, schema version 1) of everything a mission did. It has one `missions` row (task, parsed task, planner, start/end, outcome, reason, stage latencies, verification) and ordered `records`:

`mission_started`, `memory` (hits), `plan` (full plan and stage timings), `step` (action, target, status, start/end, duration, model confidence and "why", explanation, stage timings so far, camera thumbnail), `thought`, `reflection` (verdict, reason), `model_decision`, `replan`, `verification`, `mission_finished`.

On by default (`MILO_TRACE=0` turns it off; `MILO_TRACE_FRAMES=0` drops thumbnails). Every hook swallows its own errors, so tracing can never fail or stall a mission (a test checks this). It writes about 18 records per synthetic mission and costs about 2.4 ms per mission (median). Read it with `GET /api/v1/traces` and `GET /api/v1/traces/{mission_id}`.
