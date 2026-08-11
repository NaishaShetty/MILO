// TalkToMilo.test.tsx
//
// Purpose
// -------
// Integration test for the full speech pipeline as wired through the
// UI: mic click -> capture -> Whisper transcript -> `createTask(...,
// "speech")` -> navigate to Mission Control. Complements
// `SpeechContext.test.tsx` (which only exercises the state machine in
// isolation) and `HomePage.test.tsx`/`MissionControlPage.test.tsx`
// (which exercise the shared component but not this end-to-end path).
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TalkToMilo } from "./TalkToMilo";
import { SpeechProvider } from "../state/SpeechContext";
import { TaskProvider } from "../state/TaskContext";
import { VoiceProvider } from "../state/VoiceContext";
import * as tasksApi from "../api/tasks";
import * as speechApi from "../api/speech";
import * as voiceApi from "../api/voice";

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return {
    ...actual,
    listTasks: vi.fn(),
    getTask: vi.fn(),
    getTaskEvents: vi.fn(),
    createTask: vi.fn(),
  };
});

vi.mock("../api/speech", async () => {
  const actual = await vi.importActual<typeof import("../api/speech")>("../api/speech");
  return { ...actual, transcribeAudio: vi.fn() };
});

vi.mock("../api/voice", async () => {
  const actual = await vi.importActual<typeof import("../api/voice")>("../api/voice");
  return { ...actual, speak: vi.fn(), transcribe: vi.fn() };
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

function renderTalkToMilo() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <TaskProvider>
        <SpeechProvider>
          <VoiceProvider>
            <Routes>
              <Route path="/" element={<TalkToMilo />} />
              <Route path="/mission-control" element={<div>Mission Control Page</div>} />
            </Routes>
          </VoiceProvider>
        </SpeechProvider>
      </TaskProvider>
    </MemoryRouter>,
  );
}

function baseTask(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "t1",
    user_request: "find the mug",
    input_source: "speech",
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
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.getTask).mockReset();
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.createTask).mockReset();
  vi.mocked(voiceApi.speak).mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TalkToMilo speech pipeline", () => {
  it("mic -> transcript -> createTask(..., 'speech') -> navigates to Mission Control", async () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) } });
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    vi.mocked(speechApi.transcribeAudio).mockResolvedValue({
      text: "find the mug",
      language: "en",
      duration_seconds: 1,
      latency_ms: 12,
    });
    vi.mocked(tasksApi.createTask).mockResolvedValue(baseTask() as never);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask() as never);

    const user = userEvent.setup();
    renderTalkToMilo();

    await user.click(screen.getByRole("button", { name: /speak an instruction/i }));
    expect(screen.getByRole("button", { name: /stop listening/i })).toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /stop listening/i }));
    });

    await waitFor(() =>
      expect(tasksApi.createTask).toHaveBeenCalledWith("find the mug", "speech"),
    );
    expect(await screen.findByText("Mission Control Page")).toBeInTheDocument();
  });

  it("shows a friendly message when the microphone is unavailable", async () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: undefined });
    const user = userEvent.setup();
    renderTalkToMilo();

    await user.click(screen.getByRole("button", { name: /speak an instruction/i }));

    expect(await screen.findByText(/microphone unavailable/i)).toBeInTheDocument();
  });

  it("shows a friendly message when Whisper is unavailable", async () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) } });
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    const { ApiError } = await import("../api/client");
    vi.mocked(speechApi.transcribeAudio).mockRejectedValue(
      new ApiError(503, { category: "model_unavailable", message: "Whisper not loaded." }),
    );

    const user = userEvent.setup();
    renderTalkToMilo();

    await user.click(screen.getByRole("button", { name: /speak an instruction/i }));
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /stop listening/i }));
    });

    expect(await screen.findByText(/speech service \(whisper\) is unavailable/i)).toBeInTheDocument();
    expect(tasksApi.createTask).not.toHaveBeenCalled();
  });
});
