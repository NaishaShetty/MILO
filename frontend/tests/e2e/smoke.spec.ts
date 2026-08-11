// smoke.spec.ts
//
// Purpose
// -------
// The most basic possible proof this repository's browser automation
// actually works end to end: launch real Chromium, load the real
// built/dev-served MILO frontend (not a static fixture), and confirm
// the real app shell renders -- nav, MILO's canonical character
// artwork (Phase 8.3's real asset, never a placeholder), and the Home
// page's real content.
import { expect, test } from "@playwright/test";

import { mockBaselineApi } from "./utils/mockApi";

test.describe("MILO frontend smoke test", () => {
  test.beforeEach(async ({ page }) => {
    await mockBaselineApi(page);
  });

  test("loads the real app shell and MILO's canonical artwork", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveTitle(/Vision-Language Robotics/i);
    await expect(page.getByRole("navigation")).toBeVisible();
    await expect(page.getByText("MILO", { exact: true }).first()).toBeVisible();

    // The real Phase 8.3 MILO asset, not a generic avatar/icon --
    // confirms the canonical character artwork actually ships and
    // loads in a real browser, not just referenced in source.
    const miloImage = page.locator('img[src*="/assets/milo/milo-"]').first();
    await expect(miloImage).toBeVisible();
    const naturalWidth = await miloImage.evaluate((img: HTMLImageElement) => img.naturalWidth);
    expect(naturalWidth).toBeGreaterThan(0);
  });

  test("navigates between real routed pages", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /settings/i }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();

    await page.getByRole("link", { name: /mission control/i }).click();
    await expect(page).toHaveURL(/\/mission-control$/);
  });
});
