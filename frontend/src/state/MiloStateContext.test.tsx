// MiloStateContext.test.tsx
//
// Purpose
// -------
// Covers the precedence chain documented in `MiloStateContext.tsx`'s
// own module docstring: voice-speaking > speech-listening/understanding
// > task status > offline/agents fallback, plus the TaskStatus ->
// MiloState mapping table and the success/error hold-timer. Did not
// exist before Phase 8.5 Stage 2 -- added alongside the interruption/
// race-condition fixes since this context is the one place all of
// that state ultimately surfaces.
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentsProvider } from "./AgentsContext";
import { MiloStateProvider, useMiloState } from "./MiloStateContext";
import { SpeechProvider, useSpeech } from "./SpeechContext";
import { TaskProvider, useTask } from "./TaskContext";
import { VoiceProvider, useVoice } from "./VoiceContext";
import * as agentsApi from "../api/agents";
import * as speechApi from "../api/speech";
import * as tasksApi from "../api/tasks";
import * as voiceApi from "../api/voice";
import type { TaskState } from "../api/tasksTypes";

vi.mock("../api/agents", async () => {
  const actual = await vi.importActual<typeof import("../api/agents")>("../api/agents");
  return { ...actual, listAgents: vi.fn() };
});

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return { ...actual, listTasks: vi.fn(), getTask: vi.fn(), getTaskEvents: vi.fn(), cancelTask: vi.fn() };
});

vi.mock("../api/voice", async () => {
  const actual = await vi.importActual<typeof import("../api/voice")>("../api/voice");
  return { ...actual, speak: vi.fn() };
});

vi.mock("../api/speech", async () => {
  const actual = await vi.importActual<typeof import("../api/speech")>("../api/speech");
  return {
    ...actual,
    transcribeAudio: vi.fn(),
    getSpeechStatus: vi.fn().mockResolvedValue({ provider: "whisper", enabled: true, available: true }),
  };
});

class FakeMediaRecorder {
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(public stream: MediaStream) {}
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["chunk"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

const fakeStream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;

function stubMic() {
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
  });
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
}

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

function taskAtStep(action: string, overrides: Partial<TaskState> = {}) {
  return baseTask({
    status: "executing",
    current_step: 0,
    current_plan: {
      plan_id: "p1",
      task_id: "t1",
      planner_type: "gpt",
      goal_summary: {},
      steps: [
        {
          step_id: 0,
          action,
          target: null,
          parameters: {},
          description: action,
          preconditions: [],
          postconditions: [],
          status: "executing",
        },
      ],
      status: "executing",
      created_at: 0,
      metadata: {},
    },
    ...overrides,
  } as unknown as Partial<TaskState>);
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <AgentsProvider>
      <TaskProvider>
        <SpeechProvider>
          <VoiceProvider>
            <MiloStateProvider>{children}</MiloStateProvider>
          </VoiceProvider>
        </SpeechProvider>
      </TaskProvider>
    </AgentsProvider>
  );
}

function useAll() {
  return { milo: useMiloState(), task: useTask(), speech: useSpeech(), voice: useVoice() };
}

beforeEach(() => {
  vi.mocked(agentsApi.listAgents).mockReset().mockResolvedValue([{ name: "vision", state: "idle" }]);
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.getTask).mockReset();
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  // Default: reject so a terminal task in a test that isn't
  // specifically exercising voice output never crashes VoiceContext's
  // effect with an unmocked (undefined-returning) speak() call --
  // see `VoiceContext.tsx` line ~90. Tests that care about voice
  // output override this with their own `mockResolvedValue`.
  vi.mocked(voiceApi.speak).mockReset().mockRejectedValue(new Error("not mocked for this test"));
  vi.mocked(speechApi.transcribeAudio).mockReset();
  // See VoiceContext.test.tsx's beforeEach for why these are needed.
  URL.createObjectURL = vi.fn(() => "blob:fake-url");
  URL.revokeObjectURL = vi.fn();
});

describe("MiloStateContext precedence", () => {
  it("maps a representative sample of real TaskStatus values", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([baseTask({ task_id: "t1", status: "executing" })]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ task_id: "t1", status: "planning" }));

    const { result } = renderHook(() => useAll(), { wrapper });
    await waitFor(() => expect(result.current.task.activeTaskId).toBe("t1"));
    await waitFor(() => expect(result.current.milo).toBe("planning"));
  });

  it("task status wins over the offline/agents fallback once a task is active", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([baseTask({ task_id: "t1", status: "executing" })]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ task_id: "t1", status: "executing" }));

    const { result } = renderHook(() => useAll(), { wrapper });
    await waitFor(() => expect(result.current.milo).toBe("executing"));
  });

  it("speech-listening wins over an in-progress task's status", async () => {
    stubMic();
    vi.mocked(tasksApi.listTasks).mockResolvedValue([baseTask({ task_id: "t1", status: "executing" })]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ task_id: "t1", status: "executing" }));

    const { result } = renderHook(() => useAll(), { wrapper });
    await waitFor(() => expect(result.current.milo).toBe("executing"));

    await act(async () => {
      await result.current.speech.startListening();
    });

    expect(result.current.milo).toBe("listening");
  });

  it("voice-speaking wins over the terminal task's success display", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ task_id: "t1", status: "succeeded" }));
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.mocked(voiceApi.speak).mockResolvedValue({
      audioBlob: new Blob(["fake-audio"]),
      text: "Done.",
    });

    const { result } = renderHook(() => useAll(), { wrapper });
    act(() => result.current.task.setActiveTaskId("t1"));

    await waitFor(() => expect(result.current.voice.state).toBe("speaking"));
    expect(result.current.milo).toBe("speaking");
  });

  it("falls back to offline when agents connectivity genuinely fails", async () => {
    vi.mocked(agentsApi.listAgents).mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useAll(), { wrapper });
    await waitFor(() => expect(result.current.milo).toBe("offline"));
  });

  it("holds success/error briefly then reverts to idle", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.mocked(tasksApi.listTasks).mockResolvedValue([]);
      vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ task_id: "t1", status: "succeeded" }));

      const { result } = renderHook(() => useAll(), { wrapper });
      act(() => result.current.task.setActiveTaskId("t1"));

      await waitFor(() => expect(result.current.milo).toBe("success"));

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
      });

      expect(result.current.milo).toBe("idle");
    } finally {
      vi.useRealTimers();
    }
  });

  it("derives 'navigating' from the current step's real action while executing", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([taskAtStep("navigate")]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(taskAtStep("navigate"));

    const { result } = renderHook(() => useAll(), { wrapper });
    await waitFor(() => expect(result.current.milo).toBe("navigating"));
  });

  it("derives 'perceiving' from a 'locate' step while executing", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([taskAtStep("locate")]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(taskAtStep("locate"));

    const { result } = renderHook(() => useAll(), { wrapper });
    await waitFor(() => expect(result.current.milo).toBe("perceiving"));
  });

  it("falls back to generic 'executing' for a step action with no dedicated state", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([taskAtStep("pickup")]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(taskAtStep("pickup"));

    const { result } = renderHook(() => useAll(), { wrapper });
    await waitFor(() => expect(result.current.milo).toBe("executing"));
  });

  it("maps the real 'retrieving_memory' status to 'recalling_memory'", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([baseTask({ status: "retrieving_memory" })]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ status: "retrieving_memory" }));

    const { result } = renderHook(() => useAll(), { wrapper });
    await waitFor(() => expect(result.current.milo).toBe("recalling_memory"));
  });

  it("shows 'pausing' while a real cancel request is in flight, then reflects the outcome", async () => {
    let resolveCancel!: (task: TaskState) => void;
    vi.mocked(tasksApi.cancelTask).mockReturnValue(
      new Promise((resolve) => {
        resolveCancel = resolve;
      }),
    );
    vi.mocked(tasksApi.listTasks).mockResolvedValue([baseTask({ status: "executing" })]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ status: "executing" }));

    const { result } = renderHook(() => useAll(), { wrapper });
    await waitFor(() => expect(result.current.milo).toBe("executing"));

    let cancelPromise!: Promise<void>;
    act(() => {
      cancelPromise = result.current.task.cancelActive();
    });
    await waitFor(() => expect(result.current.milo).toBe("pausing"));

    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ status: "cancelled" }));
    await act(async () => {
      resolveCancel(baseTask({ status: "cancelled" }));
      await cancelPromise;
    });

    await waitFor(() => expect(result.current.milo).toBe("idle"));
  });
});
