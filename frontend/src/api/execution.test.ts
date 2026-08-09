// execution.test.ts
//
// Purpose
// -------
// Unit tests for the centralized Execution API client (`startExecution`,
// `getExecution`, `cancelExecution`) -- mirrors `planner.test.ts`'s own
// convention of mocking the global `fetch` rather than a real backend.
import { afterEach, describe, expect, it, vi } from "vitest";

import { cancelExecution, ExecutionApiError, getExecution, startExecution } from "./execution";

const PLAN = {
  plan_id: "p1",
  task_id: "t1",
  planner_type: "rule_based",
  goal_summary: {},
  status: "valid" as const,
  created_at: 0,
  metadata: {},
  steps: [],
};

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

describe("startExecution", () => {
  it("POSTs the plan to the execution start endpoint", async () => {
    mockFetchOnce(202, { execution_id: "e1", plan_id: "p1", task_id: "t1", status: "pending", step_results: [], events: [] });

    await startExecution(PLAN);

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/execution/start",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ plan: PLAN, max_step_retries: 0, step_timeout_s: null }),
      }),
    );
  });

  it("resolves with the backend's ExecutionRecord", async () => {
    const body = { execution_id: "e1", plan_id: "p1", task_id: "t1", status: "pending", step_results: [], events: [] };
    mockFetchOnce(202, body);
    await expect(startExecution(PLAN)).resolves.toEqual(body);
  });

  it("throws ExecutionApiError with the backend's category/message on failure", async () => {
    mockFetchOnce(503, { category: "execution_unavailable", message: "No simulator is running." });
    await expect(startExecution(PLAN)).rejects.toMatchObject({
      category: "execution_unavailable",
      status: 503,
      message: "No simulator is running.",
    });
    mockFetchOnce(503, { category: "execution_unavailable", message: "No simulator is running." });
    await expect(startExecution(PLAN)).rejects.toBeInstanceOf(ExecutionApiError);
  });
});

describe("getExecution", () => {
  it("GETs the execution by id", async () => {
    mockFetchOnce(200, { execution_id: "e1", plan_id: "p1", task_id: "t1", status: "running", step_results: [], events: [] });
    await getExecution("e1");
    expect(fetch).toHaveBeenCalledWith("/api/v1/execution/e1", expect.objectContaining({}));
  });

  it("throws ExecutionApiError on 404", async () => {
    mockFetchOnce(404, { category: "execution_not_found", message: "No execution with id 'e1'." });
    await expect(getExecution("e1")).rejects.toMatchObject({ status: 404 });
  });
});

describe("cancelExecution", () => {
  it("POSTs to the cancel endpoint", async () => {
    mockFetchOnce(200, { execution_id: "e1", plan_id: "p1", task_id: "t1", status: "running", step_results: [], events: [] });
    await cancelExecution("e1");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/execution/e1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
