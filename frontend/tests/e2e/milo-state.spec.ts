// milo-state.spec.ts
//
// Purpose
// -------
// Real-browser proof that MiloStateContext's precedence chain (see
// `docs/architecture/milo_state_system.md`) actually drives the
// canonical MiloAvatar/MiloStateIndicator UI as a real task's status
// changes -- not just under jsdom (already covered by
// `src/state/MiloStateContext.test.tsx`), but through a real page
// load, a real polling loop (`usePolling.ts`), and real React
// re-renders in an actual browser. The backend is fully mocked (see
// `utils/mockApi.ts`) -- only the frontend's own state-derivation and
// rendering logic is under test here.
import { expect, test } from "@playwright/test";

import { fakeTask, mockBaselineApi } from "./utils/mockApi";

test.describe("MILO state transitions (Mission Control)", () => {
  test("reflects the real task lifecycle: executing -> succeeded -> idle", async ({ page }) => {
    await mockBaselineApi(page);

    // TaskContext auto-adopts the newest non-terminal task from
    // history on mount -- this is what puts a real active task in
    // front of MiloStateContext without a manual "submit" step.
    await page.route("**/api/v1/tasks", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: [fakeTask({ status: "executing" })] });
      }
      return route.continue();
    });

    let pollCount = 0;
    await page.route("**/api/v1/tasks/e2e-task-1", (route) => {
      pollCount += 1;
      // First couple of polls: still executing. From the third poll
      // onward: succeeded -- a real state transition over real time,
      // not a single static fixture.
      const status = pollCount < 3 ? "executing" : "succeeded";
      return route.fulfill({ json: fakeTask({ status }) });
    });
    await page.route("**/api/v1/tasks/e2e-task-1/events", (route) => route.fulfill({ json: [] }));

    await page.goto("/mission-control");

    const indicator = page.locator(".milo-state-indicator");
    await expect(indicator).toHaveClass(/milo-state-indicator--executing/, { timeout: 10_000 });
    await expect(page.getByRole("region", { name: "MILO Status" })).toContainText("Acting");

    await expect(indicator).toHaveClass(/milo-state-indicator--success/, { timeout: 10_000 });
    await expect(page.getByRole("region", { name: "MILO Status" })).toContainText("Success");

    // The MiloAvatar in the nav bar (a second, independent consumer
    // of the same MiloStateContext) must agree -- Phase 8.3's "every
    // MiloAvatar instance renders the same state" requirement.
    const navAvatar = page.locator(".milo-navbar__avatar img");
    await expect(navAvatar).toHaveAttribute("src", /milo-success\.png/);

    // MiloStateContext's real SUCCESS_HOLD_MS timer (4000ms) reverts
    // the display to idle on its own -- a real timer over a real
    // terminal status, not a fabricated animation (see
    // docs/architecture/milo_state_system.md). This is the slowest
    // assertion in this suite by design.
    await expect(indicator).toHaveClass(/milo-state-indicator--idle/, { timeout: 6_000 });
  });
});
