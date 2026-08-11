// mockApi.ts
//
// Purpose
// -------
// Shared backend-mocking helper for the E2E suite. Intercepts every
// endpoint the app calls unconditionally on mount/navigation (agent
// list, task history, speech/voice/language status) with a safe,
// generic 200 response, so an individual spec only needs to override
// the handful of routes its scenario actually cares about (e.g. a
// specific `GET /api/v1/tasks/:id` polling sequence). No test in this
// suite ever reaches a real backend process or a real LLM/speech
// provider -- see `playwright.config.ts`'s module docstring for why.
//
// Every route below fully `fulfill()`s, never `route.continue()`s.
// `POST /api/v1/tasks` and `POST /api/v1/voice/speak` in particular
// must have a default here even though most tests never call them
// directly: `useSpeechToTask.ts` auto-submits any received transcript
// as a real task, and `VoiceContext` auto-speaks any terminal task --
// both fire for real from ordinary app behavior a test may trigger
// only incidentally (e.g. a mic/transcript test that never intends to
// create a task). An earlier version of this helper `route.continue()`d
// unhandled POSTs, which let exactly that happen: a real request left
// the mocked browser and hit Vite's dev-server proxy, which then tried
// (and failed) to reach a real backend on port 8000 -- caught by
// tracing `page.on("request")` output against the Vite dev server's
// own "http proxy error: ECONNREFUSED" log line during a real test
// run, not assumed.
import type { Page } from "@playwright/test";

/** Registers safe default mocks for every endpoint the app can call
 * incidentally, not just the ones a given test scenario intends to
 * exercise. Every route fully resolves in-browser -- nothing is ever
 * allowed to fall through to the real network. */
export async function mockBaselineApi(page: Page): Promise<void> {
  // Safety net, registered first (lowest priority -- every more
  // specific route below, and any a test registers afterward, wins
  // over this one). Anything reaching this means some endpoint the
  // app actually called has no mock -- fail loudly and immediately
  // instead of silently letting the request fall through to the real
  // network (which is exactly how the ECONNREFUSED-to-Vite's-proxy
  // bug this file's docstring describes went unnoticed at first).
  await page.route("**/api/v1/**", (route) => {
    throw new Error(
      `Unmocked API call in E2E test: ${route.request().method()} ${route.request().url()}. ` +
        "Add a page.route() handler for it (see mockApi.ts's module docstring).",
    );
  });

  await page.route("**/health", (route) =>
    route.fulfill({ json: { status: "ok", llm_provider_configured: true } }),
  );
  await page.route("**/api/v1/agents", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/tasks", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ json: fakeTask({ status: "created" }) });
    }
    return route.fulfill({ json: [] });
  });
  // Default for `GET /api/v1/tasks/:id`/`:id/events` -- covers any
  // task created via the default `POST /api/v1/tasks` handler above
  // (e.g. `useSpeechToTask.ts`'s real auto-submit-on-transcript
  // effect) so its subsequent polling never leaks to the real
  // network either. Tests that care about a specific polling sequence
  // register a more specific override for that exact task id, which
  // takes precedence (last-registered route wins in Playwright).
  await page.route("**/api/v1/tasks/*", (route) =>
    route.fulfill({ json: fakeTask({ status: "created" }) }),
  );
  await page.route("**/api/v1/tasks/*/events", (route) => route.fulfill({ json: [] }));
  // Default for `GET /api/v1/tasks/:id/robot` (Phase 8.6) -- most specs
  // don't care about robot state, so default to "no simulator running"
  // (503, same contract every other simulator-backed route uses),
  // matching this project's real dev-mode default
  // (`VISION_ENABLE_SIMULATOR=false`). A spec that cares about a
  // connected-simulator state overrides this route itself.
  await page.route("**/api/v1/tasks/*/robot", (route) =>
    route.fulfill({
      status: 503,
      json: { category: "execution_unavailable", message: "No simulator is running." },
    }),
  );
  await page.route("**/api/v1/speech", (route) =>
    route.fulfill({ json: { provider: "whisper", enabled: true, available: true } }),
  );
  await page.route("**/api/v1/voice", (route) =>
    route.fulfill({
      json: { enabled: true, available: true, provider: "elevenlabs", voice_id: "test-voice" },
    }),
  );
  await page.route("**/api/v1/voice/speak", (route) =>
    route.fulfill({
      status: 503,
      json: { category: "voice_unavailable", message: "Voice is not available." },
    }),
  );
  await page.route("**/api/v1/language", (route) =>
    route.fulfill({
      json: { provider: "gemini", model: "gemini-flash-latest", configured: true, available: true },
    }),
  );
  await page.route("**/api/v1/memory*", (route) => route.fulfill({ json: [] }));
  // Default for `GET /api/v1/tasks/:id/memory` -- TaskMemoryPanel
  // (Phase 8.6) polls this whenever an active task exists.
  await page.route("**/api/v1/tasks/*/memory", (route) =>
    route.fulfill({ json: { retrieved: [], created: [] } }),
  );
  // MILO Lab page (`GET /api/v1/lab/experiments`, `/lab/stats`).
  await page.route("**/api/v1/lab/experiments", (route) =>
    route.fulfill({ json: { experiments: [] } }),
  );
  await page.route("**/api/v1/lab/stats", (route) =>
    route.fulfill({
      json: {
        experiments_run: 0,
        task_success_rate: null,
        total_actions: 0,
        memories_created: 0,
        tasks_run: 0,
      },
    }),
  );
}

/** A real-shaped `TaskState` with sensible defaults, overridable per test. */
export function fakeTask(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    task_id: "e2e-task-1",
    user_request: "find the mug",
    input_source: "text",
    goal: "find",
    objects: ["mug"],
    target: null,
    current_location: null,
    current_plan: null,
    current_step: null,
    observations: [],
    known_objects: [],
    completed_steps: [],
    execution_history: [],
    failures: [],
    retrieved_memories: [],
    agent_states: {},
    status: "executing",
    latencies_ms: {},
    created_memories: [],
    metrics: { actions: 0, failures: 0, replans: 0, attempts: 0, success: false, total_ms: null },
    ...overrides,
  };
}
