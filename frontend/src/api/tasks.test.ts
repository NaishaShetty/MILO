// tasks.test.ts
//
// Purpose
// -------
// Unit tests for the centralized Task API client -- mirrors
// `execution.test.ts`'s convention of mocking the global `fetch`.
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelTask,
  createTask,
  getTask,
  getTaskEvents,
  getTaskMemory,
  getTaskPlan,
  listTasks,
} from "./tasks";

const TASK_STATE = {
  task_id: "t1",
  user_request: "find the mug",
  input_source: "text",
  goal: "find",
  objects: ["mug"],
  target: null,
  current_location: null,
  current_plan: null,
  current_step: null,
  observations: [],
  known_objects: [],
  completed_steps: [],
  execution_history: [],
  failures: [],
  retrieved_memories: [],
  agent_states: {},
  status: "created",
  latencies_ms: {},
  created_memories: [],
  metrics: { actions: 0, failures: 0, replans: 0, attempts: 0, success: false, total_ms: null },
};

function mockFetchOnce(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createTask", () => {
  it("POSTs the instruction and input_source", async () => {
    mockFetchOnce(202, TASK_STATE);
    await createTask("find the mug", "text");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/tasks",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ instruction: "find the mug", input_source: "text" }),
      }),
    );
  });

  it("defaults input_source to text", async () => {
    mockFetchOnce(202, TASK_STATE);
    await createTask("find the mug");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/tasks",
      expect.objectContaining({
        body: JSON.stringify({ instruction: "find the mug", input_source: "text" }),
      }),
    );
  });

  it("throws ApiError with the backend's category on 409", async () => {
    mockFetchOnce(409, { category: "task_in_progress", message: "already running" });
    await expect(createTask("find the mug")).rejects.toMatchObject({
      status: 409,
      category: "task_in_progress",
    });
  });
});

describe("listTasks", () => {
  it("GETs the task list", async () => {
    mockFetchOnce(200, [TASK_STATE]);
    await expect(listTasks()).resolves.toEqual([TASK_STATE]);
    expect(fetch).toHaveBeenCalledWith("/api/v1/tasks", expect.objectContaining({}));
  });
});

describe("getTask", () => {
  it("GETs the task by id", async () => {
    mockFetchOnce(200, TASK_STATE);
    await getTask("t1");
    expect(fetch).toHaveBeenCalledWith("/api/v1/tasks/t1", expect.objectContaining({}));
  });

  it("throws ApiError on 404", async () => {
    mockFetchOnce(404, { category: "task_not_found", message: "No task with id 't1'." });
    await expect(getTask("t1")).rejects.toMatchObject({ status: 404 });
  });
});

describe("getTaskPlan", () => {
  it("returns null before a plan exists", async () => {
    mockFetchOnce(200, null);
    await expect(getTaskPlan("t1")).resolves.toBeNull();
  });
});

describe("getTaskMemory", () => {
  it("GETs retrieved/created memory", async () => {
    mockFetchOnce(200, { retrieved: [], created: [] });
    await expect(getTaskMemory("t1")).resolves.toEqual({ retrieved: [], created: [] });
    expect(fetch).toHaveBeenCalledWith("/api/v1/tasks/t1/memory", expect.objectContaining({}));
  });
});

describe("getTaskEvents", () => {
  it("GETs the event log", async () => {
    mockFetchOnce(200, []);
    await getTaskEvents("t1");
    expect(fetch).toHaveBeenCalledWith("/api/v1/tasks/t1/events", expect.objectContaining({}));
  });
});

describe("cancelTask", () => {
  it("POSTs to the cancel endpoint", async () => {
    mockFetchOnce(200, { ...TASK_STATE, status: "cancelled" });
    await cancelTask("t1");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/tasks/t1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
