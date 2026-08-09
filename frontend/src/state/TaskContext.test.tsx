// TaskContext.test.tsx
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TaskProvider, useTask } from "./TaskContext";
import * as tasksApi from "../api/tasks";
import type { TaskState } from "../api/tasksTypes";

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return {
    ...actual,
    listTasks: vi.fn(),
    getTask: vi.fn(),
    getTaskEvents: vi.fn(),
    createTask: vi.fn(),
    cancelTask: vi.fn(),
  };
});

function baseTask(overrides: Partial<TaskState> = {}) {
  return {
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
    status: "executing",
    latencies_ms: {},
    created_memories: [],
    metrics: { actions: 0, failures: 0, replans: 0, attempts: 0, success: false, total_ms: null },
    ...overrides,
  } as unknown as TaskState;
}

describe("TaskContext", () => {
  it("has no active task and empty history when nothing has run", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([]);
    const { result } = renderHook(() => useTask(), { wrapper: TaskProvider });

    await waitFor(() => expect(result.current.historyStatus).toBe("success"));
    expect(result.current.activeTaskId).toBeNull();
    expect(result.current.history).toEqual([]);
  });

  it("bootstraps the active task from the newest non-terminal task in history", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([baseTask({ task_id: "t1", status: "executing" })]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ task_id: "t1", status: "executing" }));
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([]);

    const { result } = renderHook(() => useTask(), { wrapper: TaskProvider });

    await waitFor(() => expect(result.current.activeTaskId).toBe("t1"));
    await waitFor(() => expect(result.current.activeTask?.task_id).toBe("t1"));
  });

  it("does not adopt a terminal task as the active one", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([baseTask({ task_id: "t1", status: "succeeded" })]);

    const { result } = renderHook(() => useTask(), { wrapper: TaskProvider });

    await waitFor(() => expect(result.current.historyStatus).toBe("success"));
    expect(result.current.activeTaskId).toBeNull();
  });

  it("submitInstruction creates a task and makes it active", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([]);
    vi.mocked(tasksApi.createTask).mockResolvedValue(baseTask({ task_id: "t2", status: "created" }));
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ task_id: "t2", status: "created" }));
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([]);

    const { result } = renderHook(() => useTask(), { wrapper: TaskProvider });
    await waitFor(() => expect(result.current.historyStatus).toBe("success"));

    await act(async () => {
      await result.current.submitInstruction("find the mug", "text");
    });

    expect(tasksApi.createTask).toHaveBeenCalledWith("find the mug", "text");
    expect(result.current.activeTaskId).toBe("t2");
  });

  it("submitInstruction surfaces a friendly error and does not set an active task", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([]);
    const { ApiError } = await import("../api/client");
    vi.mocked(tasksApi.createTask).mockRejectedValue(
      new ApiError(409, { category: "task_in_progress", message: "Task already running." }),
    );

    const { result } = renderHook(() => useTask(), { wrapper: TaskProvider });
    await waitFor(() => expect(result.current.historyStatus).toBe("success"));

    await act(async () => {
      await expect(result.current.submitInstruction("find the mug")).rejects.toBeInstanceOf(ApiError);
    });

    expect(result.current.submitError).toBe("Task already running.");
    expect(result.current.activeTaskId).toBeNull();
  });

  it("cancelActive calls the cancel endpoint for the active task", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([baseTask({ task_id: "t1", status: "executing" })]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ task_id: "t1", status: "executing" }));
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([]);
    vi.mocked(tasksApi.cancelTask).mockResolvedValue(baseTask({ task_id: "t1", status: "cancelled" }));

    const { result } = renderHook(() => useTask(), { wrapper: TaskProvider });
    await waitFor(() => expect(result.current.activeTaskId).toBe("t1"));

    await act(async () => {
      await result.current.cancelActive();
    });

    expect(tasksApi.cancelTask).toHaveBeenCalledWith("t1");
  });

  it("throws a clear error when used outside the provider", () => {
    const { result } = renderHook(() => {
      try {
        return useTask();
      } catch (error) {
        return error;
      }
    });
    expect(result.current).toBeInstanceOf(Error);
  });
});
