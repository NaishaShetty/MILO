// browserVoice.spec.ts
//
// The browser-voice path ("Talk with MILO" on) in real Chromium: the switch, a spoken
// command, and a spoken approval -- the flows `src/state/BrowserVoice.test.tsx` covers
// in jsdom, here through the real app, router and pages.
//
// What is real and what isn't
// ---------------------------
// Chrome's own speech recognition sends audio to Google's servers, so no CI browser
// can genuinely recognise speech. The recogniser is therefore a stand-in that
// "hears" a scripted sentence, and speech synthesis is a stand-in that records what
// MILO says and finishes at once (headless Chromium may have no voices, and a real
// utterance would never end). Everything between them -- the app's voice state, the
// mic button, the pages, the requests sent -- is the real app in a real browser.
// Real recognition quality still needs a person: see the checklist in docs/voice.md.
import { expect, test, type Page } from "@playwright/test";

import { fakeTask, mockBaselineApi } from "./utils/mockApi";

/** Installs the stand-in recogniser and speaker before the app loads. */
async function standInSpeech(page: Page, heard: string[]) {
  await page.addInitScript((sentences: string[]) => {
    const w = window as unknown as Record<string, unknown>;
    w.__heard = [...sentences];
    w.__said = [];
    w.__listens = 0;
    class StandInRecognition {
      lang = "";
      interimResults = false;
      maxAlternatives = 1;
      onresult: ((e: unknown) => void) | null = null;
      onerror: ((e: unknown) => void) | null = null;
      onend: (() => void) | null = null;
      start() {
        (w.__listens as number)++;
        const text = (w.__heard as string[]).shift() ?? "";
        setTimeout(() => {
          if (text) this.onresult?.({ results: [[{ transcript: text }]] });
          this.onend?.();
        }, 150);
      }
      stop() {
        this.onend?.();
      }
    }
    w.SpeechRecognition = StandInRecognition;
    w.webkitSpeechRecognition = StandInRecognition;
    const synth = window.speechSynthesis;
    synth.speak = (u: SpeechSynthesisUtterance) => {
      (w.__said as string[]).push(u.text);
      setTimeout(() => u.onend?.(new Event("end") as SpeechSynthesisEvent), 10);
    };
    synth.cancel = () => undefined;
    window.localStorage.setItem("milo.tourSeen", "1");
  }, heard);
}

/** The Missions page follows a task through its server-sent event stream; this sends
 * the task's state once and ends, as the real stream does for a task that's waiting. */
async function streamTask(page: Page, task: Record<string, unknown>) {
  await page.route("**/api/v1/tasks/*/stream*", (route) =>
    route.fulfill({
      headers: { "content-type": "text/event-stream" },
      body: `event: state\ndata: ${JSON.stringify(task)}\n\nevent: end\ndata: {}\n\n`,
    }),
  );
}

test.describe("Browser voice (Talk with MILO)", () => {
  test.beforeEach(async ({ page }) => {
    await mockBaselineApi(page);
    // The Missions page asks for a camera view; with no simulator the backend says 503.
    await page.route("**/api/v1/vision/perceive*", (route) =>
      route.fulfill({ status: 503, json: { category: "vision_unavailable", message: "No simulator is running." } }),
    );
  });

  test("the switch is remembered, and a spoken command becomes a speech mission", async ({ page }) => {
    await standInSpeech(page, ["put the apple in the fridge"]);
    await streamTask(page, fakeTask({ status: "created", user_request: "put the apple in the fridge" }));
    let submitted: Record<string, unknown> | null = null;
    await page.route("**/api/v1/tasks", (route) => {
      if (route.request().method() === "POST") {
        submitted = route.request().postDataJSON() as Record<string, unknown>;
        // POST /tasks answers with `kind: "task"` (CreateTaskResult) for a mission
        return route.fulfill({
          json: { ...fakeTask({ status: "created", user_request: "put the apple in the fridge" }), kind: "task", understood_as: "store apple in fridge" },
        });
      }
      return route.fulfill({ json: [] });
    });

    await page.goto("/");
    const toggle = page.getByRole("checkbox", { name: "Talk with MILO" });
    await expect(toggle).toBeEnabled();
    await toggle.check();
    await page.reload();
    await expect(page.getByRole("checkbox", { name: "Talk with MILO" })).toBeChecked();

    await page.getByRole("button", { name: "Talk to MILO" }).click();
    await expect(page).toHaveURL(/\/missions$/, { timeout: 10_000 });
    // heard by the browser, so it is sent as speech, not typed text
    expect(submitted).toMatchObject({ instruction: "put the apple in the fridge", input_source: "speech" });
    expect(await page.evaluate(() => (window as unknown as { __listens: number }).__listens)).toBe(1);
  });

  test("MILO says an approval request out loud and a spoken 'yes' approves it", async ({ page }) => {
    await standInSpeech(page, ["open the fridge", "yes, go ahead"]);
    const waiting = fakeTask({
      status: "executing",
      user_request: "open the fridge",
      pending_decision: {
        kind: "step",
        why: "opening the fridge changes the room",
        step_id: 3,
        action: "open",
        target: "fridge",
        text: "Open the fridge.",
        asked_at: 1,
      },
    });
    await page.route("**/api/v1/tasks", (route) =>
      route.request().method() === "POST"
        ? route.fulfill({ json: { ...waiting, kind: "task", understood_as: "open the fridge" } })
        : route.fulfill({ json: [] }),
    );
    await page.route("**/api/v1/tasks/e2e-task-1", (route) => route.fulfill({ json: waiting }));
    await streamTask(page, waiting);
    let decision: Record<string, unknown> | null = null;
    await page.route("**/api/v1/tasks/e2e-task-1/decision", (route) => {
      decision = route.request().postDataJSON() as Record<string, unknown>;
      return route.fulfill({ json: { ...waiting, pending_decision: null } });
    });

    await page.goto("/");
    await page.getByRole("checkbox", { name: "Talk with MILO" }).check();
    await page.getByRole("button", { name: "Talk to MILO" }).click();
    await expect(page).toHaveURL(/\/missions$/, { timeout: 10_000 });

    await expect.poll(() => decision, { timeout: 10_000 }).toEqual({ choice: "approve" });
    const said = await page.evaluate(() => (window as unknown as { __said: string[] }).__said);
    expect(said).toContain("Open the fridge. I'm asking because opening the fridge changes the room. Say yes, or skip.");
  });

  test("a browser that can't listen or speak gets a plain fallback, not a broken switch", async ({ page }) => {
    await page.addInitScript(() => {
      const w = window as unknown as Record<string, unknown>;
      delete w.SpeechRecognition;
      delete w.webkitSpeechRecognition;
      delete (Window.prototype as unknown as Record<string, unknown>).webkitSpeechRecognition;
      delete (Window.prototype as unknown as Record<string, unknown>).speechSynthesis;
      delete w.speechSynthesis;
      window.localStorage.setItem("milo.tourSeen", "1");
    });
    await page.goto("/");
    await expect(page.getByRole("checkbox", { name: "Talk with MILO" })).toBeDisabled();
    await expect(page.getByText("This browser can't listen or speak. Type to MILO instead.")).toBeVisible();
    // typing still works
    await expect(page.getByRole("textbox").first()).toBeEnabled();
  });
});
