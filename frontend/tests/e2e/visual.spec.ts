// visual.spec.ts -- one visual snapshot per page (Play, Missions, Memory, Lab,
// Mobile) with MILO's animation paused, so the redesign cannot regress.
// First run writes the baselines: `npx playwright test visual.spec.ts --update-snapshots`.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { fakeTask, mockBaselineApi } from "./utils/mockApi";

const FREEZE = `
  *, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }
`;

async function settle(page: Page, route: string) {
  await mockBaselineApi(page);
  await page.addInitScript(() => window.localStorage.setItem("milo.tourSeen", "1"));
  await page.goto(route);
  await page.waitForLoadState("networkidle");
  await page.addStyleTag({ content: FREEZE });
}

test.describe("visual snapshots", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  for (const [name, route] of [
    ["play", "/"],
    ["memory", "/memory"],
    ["lab", "/lab"],
  ] as const) {
    test(`${name} page`, async ({ page }) => {
      await settle(page, route);
      await expect(page).toHaveScreenshot(`${name}.png`, { animations: "disabled", maxDiffPixelRatio: 0.02 });
    });
  }

  test("missions page", async ({ page }) => {
    await mockBaselineApi(page);
    await page.route("**/api/v1/tasks", (route) =>
      route.fulfill({ json: [fakeTask({ task_id: "t1", status: "succeeded", user_request: "Put the apple in the fridge" })] }),
    );
    await page.addInitScript(() => window.localStorage.setItem("milo.tourSeen", "1"));
    await page.goto("/missions");
    await page.waitForLoadState("networkidle");
    await page.addStyleTag({ content: FREEZE });
    await expect(page).toHaveScreenshot("missions.png", { animations: "disabled", maxDiffPixelRatio: 0.02 });
  });
});

test.describe("mobile snapshot", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("play page with the bottom dock", async ({ page }) => {
    await settle(page, "/");
    await expect(page.locator(".dock")).toBeVisible();
    await expect(page).toHaveScreenshot("mobile.png", { animations: "disabled", maxDiffPixelRatio: 0.02 });
  });
});
