# MILO -- Frontend (Session 3 / Phase 7)

**MILO** -- Memory Integrated Language Oriented Robot -- is a Vite + React +
TypeScript application around the backend's Phase 7 agent/orchestrator
architecture (`backend/agents/`, `backend/orchestration/orchestrator.py`).
This is the functional (not yet visually final -- see "Phase 8" below)
seven-page MILO app: it creates real tasks, watches them run through the
real orchestrator, and shows real agent/memory/event data. Nothing here
plans, executes, or reasons on its own -- every action goes through the
backend's Task API.

See the root [README.md](../README.md) and
[`backend/docs/language_interface_spec.md`](../backend/docs/language_interface_spec.md)
for the full backend architecture; this file only covers the frontend.

## The seven pages

| Route | Page | Answers |
|---|---|---|
| `/` | 🏠 Home | Who is MILO? Can I talk to MILO? |
| `/mission-control` | 🎮 Mission Control | What is MILO doing right now? |
| `/memory` | 🧠 Memory | What does MILO remember? |
| `/activity` | 📜 Activity | What has MILO been doing? |
| `/about` | 👋 About MILO | What is MILO, and how does it work? |
| `/lab` | 🔬 MILO Lab | How is the system working technically? |
| `/settings` | ⚙ Settings | Configuration (only what's actually supported) |

There is deliberately no eighth "Mission Detail" page -- task detail lives
inline on Mission Control/Activity/Memory/Lab.

## Architecture

```
Backend API  ->  API Client (src/api/*)  ->  Types (src/api/*Types.ts)
            ->  State (src/state/*, src/hooks/*)  ->  Pages (src/pages/*)
            ->  Reusable components (src/components/*)  ->  Presentation
```

This separation is deliberate: Phase 8 is expected to redesign the visual
presentation substantially, and should be able to do that without touching
API integration, task/agent/speech/memory state, or event handling.

- **API layer** (`src/api/`): one module per backend domain
  (`tasks.ts`, `agents.ts`, `speech.ts`, plus the pre-existing
  `language.ts`/`vision.ts`/`planner.ts`/`execution.ts`), each the sole
  place that calls `fetch()` for its domain. `client.ts` holds the shared
  `request()`/`requestForm()` helpers the three new modules build on
  (existing modules keep their own established pattern unchanged).
  Every module uses **relative URLs only** (`/api/v1/...`) so the same
  built bundle works behind any reverse proxy.
- **Types** (`src/api/*Types.ts`): hand-written TypeScript views of the
  backend's real Pydantic/dataclass models -- not codegen, only the fields
  the UI renders. `tasksTypes.ts` mirrors `backend/agents/task_state.py`'s
  `TaskState.to_dict()` exactly.
- **State** (`src/state/*Context.tsx`, `src/hooks/use*.ts`): React Context
  + hooks, no external state library. `TaskContext` owns the active
  mission (polls `GET /tasks/{id}` + `/events`) and task history (`GET
  /tasks`); `AgentsContext` polls `GET /agents`; `SpeechContext` drives the
  browser-side mic capture/Whisper lifecycle; `SettingsContext` persists
  to `localStorage`. `usePolling` is the one shared polling primitive
  (self-rescheduling `setTimeout`, since the backend has no WebSocket/SSE
  transport -- see `backend/api/routes/tasks.py`'s docstring on why
  `POST /tasks` backgrounds the run and expects polling).
- **Pages** (`src/pages/`): one component per route, composed from
  reusable components and state hooks -- no direct `fetch()` calls.
- **Reusable components** (`src/components/`): `TalkToMilo` (text + speech
  input, shared by Home and Mission Control), `AgentStatusList` (shared by
  Home/Mission Control/Lab), `NavBar`, `ErrorBoundary`, plus the
  pre-existing `VisionPanel`/`PlanStepsList`/`ObjectInspectorTable`/etc.,
  reused as-is inside the new pages where they fit (e.g. `VisionPanel`
  powers Mission Control's "MILO's Eyes"/"Detected Objects" sections
  unchanged).

## Real data only

Every number/status in the app is either real backend data or an explicit
empty/unavailable state -- never a hardcoded placeholder. Two examples worth
knowing about:

- **`GET /api/v1/tasks`** (list) was added to the backend specifically for
  this frontend (`backend/api/routes/tasks.py::list_tasks`) -- the backend
  had no way to list past tasks, and several pages (Home's "Recent
  Mission", Activity's history, Lab's stats) need real cross-task data
  rather than fabricated numbers.
- The backend has **no generic memory-search endpoint** and **no
  aggregate-metrics endpoint**. Memory/Activity/Lab pages build their views
  by aggregating each task's own `retrieved_memories`/`created_memories`/
  `events`/`metrics` (already returned by `GET /tasks`) client-side -- see
  `src/utils/memory.ts` and `src/utils/activity.ts`. "Quick Memory Search"
  on the Memory page asks a real question through the real task pipeline
  (`TaskContext.submitInstruction`), not a fake local filter.

## Setup

```bash
cd frontend
npm install   # or `npm ci` for a reproducible install from package-lock.json
```

## Development

Run the backend first (see root README's "Quick Start"). For Mission
Control's camera/task lifecycle to do anything beyond showing empty states,
the backend also needs `VISION_ENABLE_SIMULATOR=true` and a reachable
AI2-THOR/Unity binary; without it, pages show a real "unavailable" state
(503s from `/vision/perceive`, `/tasks`, `/agents`) rather than fabricating
data or crashing.

```bash
npm run dev
```

Opens on `http://localhost:5173`. The dev server proxies `/api` and
`/health` to `http://localhost:8000` (override with `VITE_BACKEND_URL` if
the backend runs elsewhere) -- see `vite.config.ts`.

## Testing

```bash
npm test
```

Runs Vitest + Testing Library against fully mocked API clients (`vi.mock`
per module, matching this project's established convention -- no MSW). No
real backend, simulator, LLM, or microphone is involved. Covers: every API
module, every state Context/hook, routing, and every page's rendering,
empty states, and key interactions (including the full mic-capture ->
Whisper -> task-creation pipeline, with a fake `MediaRecorder`).

See [`docs/testing/manual_e2e_checklist.md`](../docs/testing/manual_e2e_checklist.md)
for the scenarios that need a live backend with a real simulator/display/
microphone and were not run automatically.

## Build

```bash
npm run build
```

Type-checks (`tsc --noEmit`) and produces a static bundle in `dist/`,
intended to be served behind the same reverse proxy as the backend so
`/api`/`/health` resolve without any absolute URL configuration.

## Deployment (Vercel)

`vercel.json` (this directory) gives Vercel the same job `nginx.conf.template`
does in the Docker setup: serve the static build and reverse-proxy `/api` and
`/health` to the backend, so `src/api/client.ts`'s "relative URLs only" rule
holds in production too -- no frontend code changes, no absolute backend URL
baked into the bundle.

Before deploying:

1. In the Vercel project settings, set **Root Directory** to `frontend`.
2. Edit `vercel.json`'s two `REPLACE_WITH_MILO_BACKEND_HOST` rewrite
   destinations to the real, already-running MILO backend's HTTPS origin
   (see the root README / `deployment/` for where that backend runs --
   it is not deployed by this file; the backend does not run on Vercel,
   see that README's "Why the backend isn't on Vercel").
3. Add that backend's origin to its own `API_ALLOWED_ORIGINS` env var so
   CORS allows requests forwarded from this Vercel deployment's domain.

No other environment variables are read by the frontend build or bundle
(see "Real data only" above) -- `VITE_BACKEND_URL` is a **local dev-only**
convenience for `vite.config.ts`'s dev proxy and is never read at runtime by
the deployed app.

## Structure

```
frontend/
  src/
    api/
      client.ts                 # shared fetch helper (tasks/agents/speech)
      tasks.ts, tasksTypes.ts   # Task/Orchestrator API
      agents.ts, agentsTypes.ts # Agent status API
      speech.ts, speechTypes.ts # Whisper transcription API
      language.ts, vision.ts, planner.ts, execution.ts  # pre-existing, reused
    state/
      TaskContext.tsx, AgentsContext.tsx, SpeechContext.tsx, SettingsContext.tsx
    hooks/
      usePolling.ts, useTaskHistory.ts, useActivityEvents.ts, useSpeechToTask.ts
    utils/
      memory.ts     # memory aggregation for the Memory page
      activity.ts   # event filtering/search/export for the Activity page
    pages/
      HomePage.tsx, MissionControlPage.tsx, MemoryPage.tsx, ActivityPage.tsx,
      AboutPage.tsx, LabPage.tsx, SettingsPage.tsx
    components/
      NavBar.tsx, ErrorBoundary.tsx, TalkToMilo.tsx, AgentStatusList.tsx,
      # plus the pre-existing Vision/Planner/Execution panel components,
      # reused inside the new pages
    App.tsx      # <BrowserRouter> + <NavBar> + the seven <Route>s
    main.tsx     # React entry point
```

## Not in this phase

Per the Session 3 brief, deliberately deferred to Phase 8: ElevenLabs voice
output, visual/UX polish, animations, and final branding. This phase
prioritizes functionality, real backend integration, and clean
architecture over pixel-perfect presentation.
