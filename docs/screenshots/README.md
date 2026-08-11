# Screenshots index (Phase 8.6)

Two distinct sources of screenshots exist in this directory. Both are real
renders of the real frontend/backend code — the difference is only whether
the *data* they show came from a live backend + AI2-THOR, or from a
deterministic mocked API response used to get a stable, presentation-ready
capture of a UI state that's hard to hit reliably on demand (e.g. "plan
mid-execution with a retry").

## `demo/` — captured against a real, running backend + AI2-THOR

`live-01-instruction-typed.png`, `live-02-task-in-progress.png`,
`live-03-task-complete.png` were captured by driving the real frontend
(Vite dev server) against a real FastAPI backend started with
`VISION_ENABLE_SIMULATOR=true`, with a real AI2-THOR/Unity process running
under Xvfb, a real LLM call (Gemini) for language parsing, and the real
rule-based planner/executor/reflection pipeline. The instruction typed
("Find the mug") was actually parsed, planned, executed against a real
`FloorPlan1` AI2-THOR scene (which genuinely contains a `Mug` object), and
reflected on — nothing in these three images is scripted or faked. See
`docs/architecture/demo_and_visualization.md` for the full source-of-truth
table and how to reproduce this yourself.

## `ui/`, `agents/`, `planning/`, `memory/`, `robotics/` — mocked API, real UI

Everything else was captured by `frontend/tests/e2e/screenshots.spec.ts`
(`npm run test:e2e -- screenshots.spec.ts`), which uses the same
`page.route()` backend-mocking helper (`tests/e2e/utils/mockApi.ts`) the
rest of the Playwright E2E suite uses. The React components, CSS, and
rendering are 100% real (this is a real browser rendering the real built
app); only the API *responses* are canned fixtures, chosen to reliably
reproduce a specific state (e.g. "simulator not connected" vs. "simulator
connected showing a held object") without depending on live AI2-THOR being
up. This mirrors how `milo-state.spec.ts`/`microphone.spec.ts` already test
real frontend behavior against a mocked backend — see that file's own
docstring.

**These mocked-source screenshots must never be presented as evidence of a
specific live MILO run** — they illustrate what the UI looks like in a
given state, not that MILO actually did something. The `demo/` screenshots
above are the ones that make that claim.

| Folder | Contents |
|---|---|
| `ui/` | All 7 routed pages (Home, Mission Control, Memory, Activity, About MILO, MILO Lab, Settings) |
| `agents/` | Agent Architecture Diagram (Mission Control) |
| `planning/` | Plan Timeline with real per-step duration/retry fields |
| `memory/` | Task Memory Panel (retrieved vs. newly created) |
| `robotics/` | Robot State Panel, both "simulator not connected" (the real dev-mode default) and "simulator connected" |
| `demo/` | Live capture against a real backend + real AI2-THOR (see above) |

## Regenerating

```bash
cd frontend
npm run test:e2e -- screenshots.spec.ts
```

Screenshots are captured at a fixed 1440x900 desktop viewport for
consistency. This command does not touch `demo/` — those require a real
backend + AI2-THOR run (see `docs/architecture/demo_and_visualization.md`).
