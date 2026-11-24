import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as tasksApi from "../api/tasks";
import type { TaskState } from "../api/tasksTypes";
import { useLiveTask } from "./useLiveTask";

vi.mock("../api/tasks", () => ({ getTask: vi.fn(), getTaskEvents: vi.fn() }));

type Listener = (message: MessageEvent) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, Listener> = {};
  onerror: ((e: unknown) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(name: string, fn: Listener) {
    this.listeners[name] = fn;
  }
  close() {
    this.closed = true;
  }
  emit(name: string, data: unknown) {
    this.listeners[name]?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

const task = (status: string) => ({ task_id: "t1", status }) as unknown as TaskState;

afterEach(() => {
  FakeEventSource.instances = [];
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("useLiveTask", () => {
  it("uses pushed state over SSE without polling", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const { result } = renderHook(() => useLiveTask("t1"));
    const source = FakeEventSource.instances[0];
    expect(source.url).toContain("/api/v1/tasks/t1/stream");

    act(() => source.emit("state", task("executing")));
    await waitFor(() => expect(result.current.transport).toBe("sse"));
    expect(result.current.task?.status).toBe("executing");
    expect(tasksApi.getTask).not.toHaveBeenCalled();
  });

  it("falls back to polling when the stream fails", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(tasksApi.getTask).mockResolvedValue(task("succeeded"));
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([]);
    const { result } = renderHook(() => useLiveTask("t1"));

    act(() => FakeEventSource.instances[0].onerror?.(new Event("error")));

    await waitFor(() => expect(result.current.transport).toBe("polling"));
    await waitFor(() => expect(result.current.task?.status).toBe("succeeded"));
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it("polls straight away when EventSource does not exist", async () => {
    vi.stubGlobal("EventSource", undefined);
    vi.mocked(tasksApi.getTask).mockResolvedValue(task("executing"));
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([]);
    const { result } = renderHook(() => useLiveTask("t1"));
    await waitFor(() => expect(result.current.transport).toBe("polling"));
    await waitFor(() => expect(result.current.task?.status).toBe("executing"));
  });

  it("is idle with no task", () => {
    const { result } = renderHook(() => useLiveTask(null));
    expect(result.current.transport).toBe("idle");
    expect(result.current.task).toBeNull();
  });
});
