// planner.test.ts
//
// Purpose
// -------
// Unit tests for the centralized Planning API client (`planTask`,
// `evaluatePlanners`) -- mirrors `language.test.ts`'s own convention of
// mocking the global `fetch` rather than a real backend, verifying
// this file's own responsibilities: building the right request,
// resolving with the backend's `PlanningResult`/`EvaluateResponse`
// body, and translating a non-2xx response into a `PlannerApiError`.
import { afterEach, describe, expect, it, vi } from "vitest";

import { evaluatePlanners, PlannerApiError, planTask } from "./planner";

const TASK = { task_type: "single" as const, task_id: "t1", needs_clarification: false };

function mockFetchOnce(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("planTask", () => {
  it("POSTs to the versioned planner endpoint with task and planner_type", async () => {
    mockFetchOnce(200, { success: true, planner_type: "rule_based", latency_ms: 1, errors: [] });

    await planTask(TASK, "rule_based");

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/planner/plan",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task: TASK, planner_type: "rule_based" }),
      }),
    );
  });

  it("defaults to the rule_based strategy", async () => {
    mockFetchOnce(200, { success: true, planner_type: "rule_based", latency_ms: 1, errors: [] });
    await planTask(TASK);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/planner/plan",
      expect.objectContaining({
        body: JSON.stringify({ task: TASK, planner_type: "rule_based" }),
      }),
    );
  });

  it("resolves with the backend's PlanningResult", async () => {
    const body = { success: true, planner_type: "rule_based", latency_ms: 1, errors: [] };
    mockFetchOnce(200, body);
    await expect(planTask(TASK)).resolves.toEqual(body);
  });

  it("throws PlannerApiError with the backend's category/message on failure", async () => {
    mockFetchOnce(422, { category: "invalid_planner_type", message: "Unknown planner_type" });
    await expect(planTask(TASK, "bogus" as never)).rejects.toMatchObject({
      category: "invalid_planner_type",
      status: 422,
      message: "Unknown planner_type",
    });
  });

  it("throws PlannerApiError instances specifically", async () => {
    mockFetchOnce(422, { category: "invalid_planner_type", message: "bad" });
    await expect(planTask(TASK)).rejects.toBeInstanceOf(PlannerApiError);
  });
});

describe("evaluatePlanners", () => {
  it("POSTs the task and optional planner_types to the evaluate endpoint", async () => {
    mockFetchOnce(200, { task_id: "t1", results: [] });
    await evaluatePlanners(TASK, ["rule_based"]);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/planner/evaluate",
      expect.objectContaining({
        body: JSON.stringify({ task: TASK, planner_types: ["rule_based"] }),
      }),
    );
  });

  it("resolves with the backend's EvaluateResponse", async () => {
    const body = { task_id: "t1", results: [{ planner_type: "rule_based" }] };
    mockFetchOnce(200, body);
    await expect(evaluatePlanners(TASK)).resolves.toEqual(body);
  });
});
