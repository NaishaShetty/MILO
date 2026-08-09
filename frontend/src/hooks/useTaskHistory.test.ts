// useTaskHistory.test.ts
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTaskHistory } from "./useTaskHistory";
import * as tasksApi from "../api/tasks";

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return { ...actual, listTasks: vi.fn() };
});

beforeEach(() => {
  vi.mocked(tasksApi.listTasks).mockReset();
});

describe("useTaskHistory", () => {
  it("returns the tasks from GET /tasks", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([
      { task_id: "t2" } as never,
      { task_id: "t1" } as never,
    ]);

    const { result } = renderHook(() => useTaskHistory());

    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.tasks.map((t) => t.task_id)).toEqual(["t2", "t1"]);
  });

  it("defaults to an empty array before the first response", () => {
    vi.mocked(tasksApi.listTasks).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useTaskHistory());
    expect(result.current.tasks).toEqual([]);
  });

  it("does not fetch when disabled", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([]);
    renderHook(() => useTaskHistory(false));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(tasksApi.listTasks).not.toHaveBeenCalled();
  });
});
