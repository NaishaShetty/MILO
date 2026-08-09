// VoiceContext.test.tsx
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TaskProvider, useTask } from "./TaskContext";
import { VoiceProvider, useVoice } from "./VoiceContext";
import * as tasksApi from "../api/tasks";
import * as voiceApi from "../api/voice";

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return { ...actual, listTasks: vi.fn(), getTask: vi.fn(), getTaskEvents: vi.fn() };
});

vi.mock("../api/voice", async () => {
  const actual = await vi.importActual<typeof import("../api/voice")>("../api/voice");
  return { ...actual, speak: vi.fn() };
});

function wrapper({ children }: { children: ReactNode }) {
  return (
    <TaskProvider>
      <VoiceProvider>{children}</VoiceProvider>
    </TaskProvider>
  );
}

function terminalTask(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "t1",
    user_request: "bring the mug",
    input_source: "text",
    goal: "bring",
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
    status: "succeeded",
    latencies_ms: {},
    created_memories: [],
    metrics: { actions: 1, failures: 0, replans: 0, attempts: 1, success: true, total_ms: 1000 },
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([terminalTask() as never]);
  vi.mocked(tasksApi.getTask).mockReset().mockResolvedValue(terminalTask() as never);
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  vi.mocked(voiceApi.speak).mockReset();
});

// TaskContext only auto-adopts an in-flight task on mount (see that
// context's own docstring) -- a terminal task needs to be explicitly
// selected as active, exactly like `submitInstruction`/`TalkToMilo`
// would do the moment a real task is created. Combining both hooks
// lets each test drive that selection then observe VoiceContext's
// reaction to the resulting real terminal TaskState.
function useTaskAndVoice() {
  return { task: useTask(), voice: useVoice() };
}

describe("VoiceContext", () => {
  it("speaks a real terminal task's real composed response exactly once", async () => {
    vi.mocked(voiceApi.speak).mockResolvedValue({
      audioBlob: new Blob(["fake-audio"]),
      text: "I finished: bring the mug.",
    });

    const { result } = renderHook(() => useTaskAndVoice(), { wrapper });
    result.current.task.setActiveTaskId("t1");

    await waitFor(() => expect(result.current.voice.spokenText).toBe("I finished: bring the mug."));
    expect(voiceApi.speak).toHaveBeenCalledWith({ taskId: "t1" });

    // A second poll tick returning the same terminal task must not re-trigger speech.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(voiceApi.speak).toHaveBeenCalledTimes(1);
  });

  it("degrades gracefully when voice is unavailable -- no crash, no dialogue", async () => {
    vi.mocked(voiceApi.speak).mockRejectedValue(new Error("voice unavailable"));

    const { result } = renderHook(() => useTaskAndVoice(), { wrapper });
    result.current.task.setActiveTaskId("t1");

    await waitFor(() => expect(result.current.voice.state).toBe("error"));
    expect(result.current.voice.spokenText).toBeNull();
  });

  it("throws a clear error when used outside the provider", () => {
    const { result } = renderHook(() => {
      try {
        return useVoice();
      } catch (error) {
        return error;
      }
    });
    expect(result.current).toBeInstanceOf(Error);
  });
});
