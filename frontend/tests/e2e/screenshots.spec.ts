// screenshots.spec.ts
//
// Purpose
// -------
// Phase 8.6 screenshot workflow (spec sections 20-21): captures every
// major routed page plus the new visualization components at a
// consistent desktop viewport, against the same `mockBaselineApi()`
// mocking helper the rest of this E2E suite uses -- deterministic UI
// states only, never a real backend/AI2-THOR (that's `docs/screenshots/
// demo/live-*.png`, captured separately against a real running
// backend+simulator; see `docs/screenshots/README.md` for which is
// which). Output lands in `docs/screenshots/{ui,agents,planning,
// memory,robotics}/`, matching this project's documented screenshot
// layout.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

import { fakeTask, mockBaselineApi } from "./utils/mockApi";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREENSHOT_ROOT = path.resolve(__dirname, "../../../docs/screenshots");
const VIEWPORT = { width: 1440, height: 900 };

function out(...segments: string[]): string {
  return path.join(SCREENSHOT_ROOT, ...segments);
}

test.describe("Phase 8.6 screenshots", () => {
  test.use({ viewport: VIEWPORT });

  test("captures every major page", async ({ page }) => {
    await mockBaselineApi(page);

    const pages: Array<[string, string]> = [
      ["/", "home.png"],
      ["/mission-control", "mission-control.png"],
      ["/memory", "memory.png"],
      ["/activity", "activity.png"],
      ["/about", "about.png"],
      ["/lab", "lab.png"],
      ["/settings", "settings.png"],
    ];

    for (const [route, filename] of pages) {
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: out("ui", filename), fullPage: true });
    }
  });

  test("captures the agent architecture diagram with live-looking agent states", async ({ page }) => {
    await mockBaselineApi(page);
    await page.route("**/api/v1/agents", (route) =>
      route.fulfill({
        json: [
          { name: "vision", state: "idle" },
          { name: "memory", state: "idle" },
          { name: "navigation", state: "idle" },
          { name: "planner", state: "thinking" },
          { name: "execution", state: "active" },
          { name: "reflection", state: "idle" },
          { name: "speech", state: "idle" },
        ],
      }),
    );
    await page.route("**/api/v1/tasks", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: [fakeTask({ status: "executing" })] });
      }
      return route.continue();
    });
    await page.route("**/api/v1/tasks/e2e-task-1", (route) =>
      route.fulfill({ json: fakeTask({ status: "executing" }) }),
    );

    await page.goto("/mission-control");
    await expect(page.getByRole("region", { name: "Agent Architecture" })).toBeVisible();
    await page.getByRole("region", { name: "Agent Architecture" }).screenshot({
      path: out("agents", "agent-architecture-diagram.png"),
    });
  });

  test("captures the plan timeline with step timing", async ({ page }) => {
    await mockBaselineApi(page);
    const plannedTask = fakeTask({
      status: "executing",
      current_plan: {
        plan_id: "p1",
        task_id: "e2e-task-1",
        planner_type: "rule_based",
        goal_summary: { goal: "find", object: "mug" },
        status: "executing",
        created_at: 0,
        metadata: {},
        steps: [
          {
            step_id: 1,
            action: "locate",
            target: "mug",
            parameters: {},
            description: "Locate mug",
            preconditions: [],
            postconditions: ["mug is perceived/known"],
            status: "completed",
          },
          {
            step_id: 2,
            action: "navigate",
            target: "mug",
            parameters: {},
            description: "Navigate to mug",
            preconditions: ["target must be located before navigating to it"],
            postconditions: ["robot is near mug"],
            status: "running",
          },
        ],
      },
      execution_history: [
        {
          execution_id: "ex1",
          plan_id: "p1",
          task_id: "e2e-task-1",
          status: "running",
          step_results: [
            {
              step_id: 1,
              action: "locate",
              target: "mug",
              status: "completed",
              result: {
                success: true,
                action: "locate",
                action_id: "a1",
                step_id: 1,
                duration_ms: 12,
                retry_count: 0,
                timestamp: 0,
                metadata: {},
              },
            },
          ],
          events: [],
        },
      ],
    });
    await page.route("**/api/v1/tasks", (route) => {
      if (route.request().method() === "GET") return route.fulfill({ json: [plannedTask] });
      return route.continue();
    });
    await page.route("**/api/v1/tasks/e2e-task-1", (route) => route.fulfill({ json: plannedTask }));

    await page.goto("/mission-control");
    await expect(page.getByText("Locate mug")).toBeVisible();
    await page.getByRole("region", { name: "MILO's Plan" }).screenshot({
      path: out("planning", "plan-timeline.png"),
    });
  });

  test("captures the task memory panel", async ({ page }) => {
    await mockBaselineApi(page);
    await page.route("**/api/v1/tasks", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: [fakeTask({ status: "executing" })] });
      }
      return route.continue();
    });
    await page.route("**/api/v1/tasks/e2e-task-1", (route) =>
      route.fulfill({ json: fakeTask({ status: "executing" }) }),
    );
    await page.route("**/api/v1/tasks/e2e-task-1/memory", (route) =>
      route.fulfill({
        json: {
          retrieved: [
            { memory_id: "m1", memory_type: "episodic", content: "Found a mug on the counter before." },
          ],
          created: [{ memory_id: "m2", memory_type: "episodic", content: "Found the mug near the sink." }],
        },
      }),
    );

    await page.goto("/mission-control");
    await expect(page.getByText("Found a mug on the counter before.")).toBeVisible();
    await page.getByRole("region", { name: "Memory for this Task" }).screenshot({
      path: out("memory", "task-memory-panel.png"),
    });
  });

  test("captures the robot state panel: simulator not connected (real dev default)", async ({ page }) => {
    await mockBaselineApi(page);
    await page.route("**/api/v1/tasks", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: [fakeTask({ status: "executing" })] });
      }
      return route.continue();
    });
    await page.route("**/api/v1/tasks/e2e-task-1", (route) =>
      route.fulfill({ json: fakeTask({ status: "executing" }) }),
    );

    await page.goto("/mission-control");
    await expect(page.getByText("Simulator not connected — no live robot state.")).toBeVisible();
    await page.getByRole("region", { name: "Where Is MILO?" }).screenshot({
      path: out("robotics", "robot-state-not-connected.png"),
    });
  });

  test("captures the robot state panel: simulator connected", async ({ page }) => {
    await mockBaselineApi(page);
    await page.route("**/api/v1/tasks", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: [fakeTask({ status: "executing" })] });
      }
      return route.continue();
    });
    await page.route("**/api/v1/tasks/e2e-task-1", (route) =>
      route.fulfill({ json: fakeTask({ status: "executing" }) }),
    );
    await page.route("**/api/v1/tasks/e2e-task-1/robot", (route) =>
      route.fulfill({
        json: {
          position: { x: -1.25, y: 0.9, z: -1.0 },
          rotation: { x: 0, y: 0, z: 0 },
          camera_horizon: -30,
          held_object: null,
          visible_objects: [
            { object_id: "Mug|1", object_type: "Mug", position: { x: -1.7, y: 0.9, z: -0.6 }, distance: 0.6 },
          ],
        },
      }),
    );

    await page.goto("/mission-control");
    await expect(page.getByText("x -1.25, y 0.90, z -1.00")).toBeVisible();
    await page.getByRole("region", { name: "Where Is MILO?" }).screenshot({
      path: out("robotics", "robot-state-connected.png"),
    });
  });
});
