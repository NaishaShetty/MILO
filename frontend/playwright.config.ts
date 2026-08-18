// playwright.config.ts
//
// Purpose
// -------
// Configuration for the frontend's browser-level E2E suite
// (`tests/e2e/`), added to permanently close the "no browser
// automation available" gap identified during Phase 8.5's end-to-end
// validation pass -- distinct from `vite.config.ts`'s Vitest `test`
// block, which drives the existing jsdom-based unit/integration
// suite (`src/**/*.test.tsx`) and is untouched by this file.
//
// Why these tests never touch a real backend or a paid provider
// ------------------------------------------------------------------
// Every E2E test mocks the backend HTTP surface via Playwright's
// `page.route()` (see `tests/e2e/utils/mockApi.ts`) instead of
// requiring a running FastAPI process or real Gemini/OpenAI/
// ElevenLabs credentials. This keeps the suite runnable in CI (or any
// contributor's machine) with zero external dependencies and zero
// cost -- real-provider validation is a deliberately separate,
// manual/opt-in activity (see `docs/troubleshooting.md` and the
// Phase 8.5 docs), never something automated CI performs.
//
// `webServer` starts only the Vite dev server (`npm run dev`) --
// never the Python backend -- since every backend call a test needs
// is intercepted in-browser before it would ever reach it.
import { defineConfig, devices } from "@playwright/test";

const PORT = 5175;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  timeout: 30_000,

  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Fake audio device + auto-accepted media prompt -- lets
        // `navigator.mediaDevices.getUserMedia({audio: true})` and
        // `MediaRecorder` succeed against a synthetic stream with no
        // physical microphone and no manual permission prompt, so mic
        // interaction tests are fully headless/CI-safe. See
        // `tests/e2e/microphone.spec.ts`.
        permissions: ["microphone"],
        launchOptions: {
          args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
        },
      },
    },
  ],

  webServer: {
    // `--host 127.0.0.1` is load-bearing, not cosmetic: without it,
    // Vite binds to whatever `localhost` resolves to on the runner,
    // which on some GitHub-hosted ubuntu-latest runners resolves to
    // the IPv6 loopback (`::1`) first depending on the box's DNS
    // resolution order -- while `url` below (and Playwright's
    // readiness poll) always hits `127.0.0.1` explicitly. That
    // mismatch reproduces as this exact symptom: the dev server is
    // actually up in well under a second, but the IPv4 poll never
    // connects, so Playwright waits the full `timeout` and reports a
    // misleading "Timed out waiting ... from config.webServer" that
    // looks like a slow boot but isn't. Forcing the bind address to
    // match the poll address removes the ambiguity outright.
    command: `npm run dev -- --port ${PORT} --strictPort --host 127.0.0.1`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    // Surfaces the dev server's own stdout/stderr in the CI log
    // instead of Playwright's default silent capture, so a future
    // webServer failure (this one or a new one) is diagnosable from
    // the job log directly rather than needing a fresh local repro.
    stdout: "pipe",
    stderr: "pipe",
  },
});
