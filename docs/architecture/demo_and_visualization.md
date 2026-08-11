# Phase 8.6 — Demo & Visualization Architecture

**Phase 8.6 demo visualizations use live MILO data wherever the underlying
capability exists.** This document says exactly what "live" means for each
visualization, where the mocked/test-only boundary sits, and how to run a
real end-to-end demo yourself.

## Source-of-truth table

| Visualization | Component(s) | Live data source | Notes |
|---|---|---|---|
| MILO's current state/avatar | `MiloAvatar`, `MiloStateIndicator` (every page) | `MiloStateContext` → `TaskContext`/`SpeechContext`/`VoiceContext`/`AgentsContext` | Single canonical derivation; see `milo_state_system.md` |
| Current mission / progress | Mission Control "Current Mission" | `TaskContext.activeTask` → `GET /api/v1/tasks/{id}` | Polled every 1000ms |
| Agent architecture | `AgentArchitectureDiagram` | `AgentsContext` → `GET /api/v1/agents` | Same data as `AgentStatusList`, graph layout instead of a flat list |
| Plan / step timeline | `PlanTimeline` | `TaskState.current_plan` + `TaskState.execution_history` → `GET /api/v1/tasks/{id}` | Duration/retry/error per step come from real `ExecutionRecord`s; a step with no execution result yet shows no timing row (never a fabricated "0ms") |
| Memory for this task | `TaskMemoryPanel` | `GET /api/v1/tasks/{id}/memory` | Shows "No relevant memory retrieved." when empty — never an invented entry |
| Robot / simulator state | `RobotStatePanel` | `GET /api/v1/tasks/{id}/robot` (new, Phase 8.6) → `Simulator.get_metadata()` | 503 → "Simulator not connected," the real dev-mode default |
| Activity feed / event log | Mission Control "Activity Feed", Activity page | `GET /api/v1/tasks/{id}/events` | In-memory only on the backend; lost on restart |
| Memory browser | Memory page | `GET /api/v1/memory`, `/memory/search` | Real semantic/episodic/failure/user memory store |
| Lab stats / experiments | MILO Lab page | `GET /api/v1/lab/stats`, `/lab/experiments` | Shows `"Not implemented"`/`"unavailable"` for anything unmeasured |

## What's new in Phase 8.6

- `GET /api/v1/tasks/{task_id}/robot` (`backend/api/routes/tasks.py`) —
  a curated view of AI2-THOR's raw `get_metadata()` (position, rotation,
  camera tilt, held object, visible objects). This is genuinely new
  plumbing (the data existed in the simulator wrapper but no route
  exposed it), not a new agent or capability.
- `AgentArchitectureDiagram`, `PlanTimeline`, `TaskMemoryPanel`,
  `RobotStatePanel` (`frontend/src/components/`) — new visualizations,
  all reading from the sources in the table above. `PlanTimeline`
  replaces the plain `PlanStepsList` in Mission Control; the others are
  additive cards.
- `TaskContext.robotState`/`robotStateStatus`/`robotStateError` — new
  polling slice, same `usePolling` pattern as everything else in that
  context, 2000ms interval, kept running through terminal task status
  (unlike the events poll) since the simulator's live pose stays
  meaningful right after a task finishes.

"Live Demo Mode" (spec section 7) was implemented as an enhancement to
the existing Mission Control page rather than a new route — Mission
Control already reads every real signal a "live demo" view needs
(instruction → understanding → planning → perception → execution →
memory → reflection → response), so a second page would have been a
redundant view over the same `TaskContext`/`AgentsContext` state.

## Known unreachable states (documented, not silently patched)

`MiloState`'s `perceiving` and `navigating` values have no backend
`TaskStatus` producer — see `limitations.md`. No new backend
`TaskStatus` value was added to manufacture a producer for them; doing
so was out of this phase's "expose the existing system" scope.

## Real-time mechanism

Polling only, via the shared `usePolling` hook — there is no
WebSocket/SSE anywhere in this backend (verified by exhaustive grep
during Phase 8.6 research: zero `StreamingResponse`/websocket routes).
Every new Phase 8.6 polling slice follows the existing interval/enabled/
isTerminal pattern rather than introducing a new transport.

## Screenshot workflow

See [`docs/screenshots/README.md`](../screenshots/README.md) for the
full breakdown. Short version: `docs/screenshots/demo/live-*.png` were
captured against a real running backend + real AI2-THOR; everything
else in `docs/screenshots/` was captured by
`frontend/tests/e2e/screenshots.spec.ts` against the same
`page.route()`-mocked backend the rest of the Playwright E2E suite uses
— real frontend code, deterministic fixture data, never presented as a
live MILO run.

## Mock/test-data boundaries

- `frontend/tests/e2e/utils/mockApi.ts` is imported **only** by files
  under `frontend/tests/e2e/` — nothing in `frontend/src/` imports it or
  anything like it. Production code has no mock data path.
- Backend tests (`backend/tests/test_api_tasks.py`, etc.) use
  `FakeSimulator`/`app.dependency_overrides` — confined to `backend/tests/`,
  never imported by `backend/api`/`backend/agents`/etc.
- The one exception spec explicitly allows (spec section 2): the E2E
  screenshot spec's fixtures exist so specific UI states (e.g. "robot
  holding an object") can be captured reliably without depending on a
  live AI2-THOR session being up during CI/screenshot generation. See
  `docs/screenshots/README.md`'s explicit warning against presenting
  those as evidence of a real run.

## Running a real demo yourself

```bash
# Backend, with a real simulator:
cd backend
VISION_ENABLE_SIMULATOR=true python -m uvicorn api.app:app --port 8000

# Frontend, pointed at it:
cd frontend
VITE_BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

Then open Mission Control and submit an instruction MILO's current scene
supports — the environment used during this phase's own validation was
AI2-THOR's `FloorPlan1`, whose object set includes `Mug`, `Apple`,
`Bread`, `Fridge`, and others (see `backend/simulator/ai2thor_env.py`'s
default `scene` and Grounding DINO's detection prompt in `VisionPanel`).
Every stage — parsing, memory retrieval, planning, execution, robot
state, reflection, memory write — will be real. This is exactly how
`docs/screenshots/demo/live-*.png` were produced.
