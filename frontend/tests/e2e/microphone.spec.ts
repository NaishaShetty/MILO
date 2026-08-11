// microphone.spec.ts
//
// Purpose
// -------
// Real-browser proof of the microphone/speech/TTS interaction and
// barge-in behavior added in Phase 8.5 (`SpeechContext`'s recording
// lifecycle, `VoiceContext.stop()`, `TalkToMilo`'s barge-in wiring) --
// exercised against *real* browser media APIs (Chromium's fake audio
// device, configured in `playwright.config.ts`), not a jsdom mock.
// The backend is fully mocked (`utils/mockApi.ts`); no real
// microphone, ElevenLabs, or LLM call is made.
import { expect, test } from "@playwright/test";

import { fakeTask, mockBaselineApi } from "./utils/mockApi";
import { buildSilentWav } from "./utils/wav";

test.describe("Microphone / recording lifecycle", () => {
  test.beforeEach(async ({ page }) => {
    await mockBaselineApi(page);
  });

  test("mic permission -> LISTENING -> stop -> real transcript", async ({ page }) => {
    await page.route("**/api/v1/speech/transcribe", (route) =>
      route.fulfill({
        json: { text: "bring me the red mug", language: "en", duration_seconds: 1.4, latency_ms: 42 },
      }),
    );

    await page.goto("/");

    const micButton = page.getByRole("button", { name: "Speak an instruction" });
    await micButton.click();

    // Real getUserMedia({audio: true}) against Chromium's fake audio
    // device + real MediaRecorder -- proves the actual browser media
    // pipeline works, not just the mocked HTTP layer.
    await expect(page.getByRole("button", { name: "Stop listening" })).toBeVisible();
    await expect(page.locator(".milo-navbar__avatar img")).toHaveAttribute(
      "src",
      /milo-listening\.png/,
    );
    await expect(page.getByText("Listening...")).toBeVisible();

    await page.getByRole("button", { name: "Stop listening" }).click();

    await expect(page.getByText(/Heard: .*bring me the red mug/)).toBeVisible({ timeout: 10_000 });
  });

  test("microphone permission denied surfaces a friendly message, never a stuck state", async ({
    page,
    context,
  }) => {
    // Simulate a real permission denial (distinct from the
    // fake-device-granted default) -- clears the context-level grant
    // for this test only.
    await context.clearPermissions();
    await page.addInitScript(() => {
      // Chromium's fake-UI flag auto-accepts by default; force a
      // real NotAllowedError from getUserMedia without needing an
      // actual denial dialog, exercising SpeechContext's real
      // permission-denied branch.
      const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = () =>
        Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
      void original;
    });

    await page.goto("/");
    await page.getByRole("button", { name: "Speak an instruction" }).click();

    await expect(page.getByText(/microphone permission was denied/i)).toBeVisible();
    // Never stuck "listening" -- the mic button must return to its
    // startable label.
    await expect(page.getByRole("button", { name: "Speak an instruction" })).toBeVisible();
  });

  test("barge-in: starting a new recording interrupts MILO mid-speech", async ({ page }) => {
    const wav = buildSilentWav(3);

    await page.route("**/api/v1/tasks", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ json: fakeTask({ task_id: "e2e-task-2", status: "created" }) });
      }
      return route.fulfill({ json: [] });
    });
    await page.route("**/api/v1/tasks/e2e-task-2", (route) =>
      route.fulfill({ json: fakeTask({ task_id: "e2e-task-2", status: "succeeded" }) }),
    );
    await page.route("**/api/v1/tasks/e2e-task-2/events", (route) => route.fulfill({ json: [] }));
    await page.route("**/api/v1/voice/speak", (route) =>
      route.fulfill({
        body: wav,
        contentType: "audio/wav",
        headers: { "X-Milo-Response-Text": "I%20found%20the%20mug." },
      }),
    );

    await page.goto("/");

    // Create a real task via the text path -> polls to a real
    // terminal status -> VoiceContext really calls speak() and plays
    // real (silent) audio.
    await page.getByLabel("Instruction for MILO").fill("bring me the mug");
    await page.getByRole("button", { name: "Send" }).click();

    const navAvatar = page.locator(".milo-navbar__avatar img");
    await expect(navAvatar).toHaveAttribute("src", /milo-speaking\.png/, { timeout: 10_000 });

    // Barge in: starting a new recording while MILO is speaking must
    // interrupt playback (TalkToMilo.tsx's `voice.stop()` call) and
    // move to LISTENING -- never both, never stuck on SPEAKING.
    await page.getByRole("button", { name: "Speak an instruction" }).click();

    await expect(navAvatar).toHaveAttribute("src", /milo-listening\.png/, { timeout: 5_000 });
  });
});
