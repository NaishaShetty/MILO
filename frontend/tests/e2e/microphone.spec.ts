// microphone.spec.ts
//
// Purpose
// -------
// Real-browser proof of the Play page's microphone path (`SpeechContext`'s
// recording lifecycle feeding `useSpeechToTask`) -- exercised against
// *real* browser media APIs (Chromium's fake audio device, configured in
// `playwright.config.ts`), not a jsdom mock. The backend is fully mocked
// (`utils/mockApi.ts`); no real microphone, speech provider, or LLM call
// is made.
//
// The old barge-in test (start recording while MILO speaks a task result
// through `VoiceContext`) was removed with the redesign: no page calls
// `VoiceContext.speak()` any more, so there is nothing to interrupt.
import { expect, test } from "@playwright/test";

import { fakeTask, mockBaselineApi } from "./utils/mockApi";

test.describe("Microphone / recording lifecycle", () => {
  test.beforeEach(async ({ page }) => {
    await mockBaselineApi(page);
    await page.addInitScript(() => window.localStorage.setItem("milo.tourSeen", "1"));
  });

  test("mic permission -> listening -> stop -> transcript becomes a mission", async ({ page }) => {
    await page.route("**/api/v1/speech/transcribe", (route) =>
      route.fulfill({
        json: { text: "bring me the red mug", language: "en", duration_seconds: 1.4, latency_ms: 42 },
      }),
    );
    let submitted: Record<string, unknown> | null = null;
    await page.route("**/api/v1/tasks", (route) => {
      if (route.request().method() === "POST") {
        submitted = route.request().postDataJSON() as Record<string, unknown>;
        return route.fulfill({ json: fakeTask({ status: "created", user_request: "bring me the red mug" }) });
      }
      return route.fulfill({ json: [] });
    });

    await page.goto("/");
    const stage = page.getByRole("region", { name: "MILO", exact: true });

    await page.getByRole("button", { name: "Talk to MILO" }).click();

    // Real getUserMedia({audio: true}) against Chromium's fake audio
    // device + real MediaRecorder -- proves the actual browser media
    // pipeline works, not just the mocked HTTP layer.
    await expect(page.getByRole("button", { name: "Stop listening" })).toBeVisible();
    await expect(stage.getByRole("img", { name: /MILO the robot, listening/ })).toBeVisible();
    await expect(stage.getByRole("status")).toHaveText("I'm listening...");

    await page.getByRole("button", { name: "Stop listening" }).click();

    // The transcript is submitted as a speech-sourced task and the app
    // moves to Missions to watch it.
    await expect(page).toHaveURL(/\/missions$/, { timeout: 10_000 });
    expect(submitted).toMatchObject({ instruction: "bring me the red mug", input_source: "speech" });
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
      navigator.mediaDevices.getUserMedia = () =>
        Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
    });

    await page.goto("/");
    await page.getByRole("button", { name: "Talk to MILO" }).click();

    await expect(page.getByRole("alert")).toContainText(/microphone permission was denied/i);
    // Never stuck "listening" -- the mic button must return to its
    // startable label.
    await expect(page.getByRole("button", { name: "Talk to MILO" })).toBeVisible();
  });
});
