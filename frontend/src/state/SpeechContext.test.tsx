// SpeechContext.test.tsx
//
// Purpose
// -------
// jsdom has no real microphone/MediaRecorder, so this stubs
// `navigator.mediaDevices.getUserMedia` and a minimal fake
// `MediaRecorder` to drive the state machine end to end.
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SpeechProvider, useSpeech } from "./SpeechContext";
import * as speechApi from "../api/speech";

vi.mock("../api/speech", async () => {
  const actual = await vi.importActual<typeof import("../api/speech")>("../api/speech");
  return { ...actual, transcribeAudio: vi.fn() };
});

class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(public stream: MediaStream) {
    FakeMediaRecorder.instances.push(this);
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["chunk"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

function stubMic(getUserMedia: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: { getUserMedia },
  });
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
}

const fakeStream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;

afterEach(() => {
  vi.unstubAllGlobals();
  FakeMediaRecorder.instances = [];
});

describe("SpeechContext", () => {
  it("reports mic_unavailable when the browser has no mediaDevices support", async () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: undefined });
    const { result } = renderHook(() => useSpeech(), { wrapper: SpeechProvider });

    await act(async () => {
      await result.current.startListening();
    });

    expect(result.current.state).toBe("error");
    expect(result.current.errorKind).toBe("mic_unavailable");
  });

  it("reports permission_denied when getUserMedia is rejected", async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new DOMException("nope", "NotAllowedError"));
    stubMic(getUserMedia);
    const { result } = renderHook(() => useSpeech(), { wrapper: SpeechProvider });

    await act(async () => {
      await result.current.startListening();
    });

    expect(result.current.state).toBe("error");
    expect(result.current.errorKind).toBe("permission_denied");
  });

  it("goes idle -> listening -> transcribed on a full successful capture", async () => {
    const getUserMedia = vi.fn().mockResolvedValue(fakeStream);
    stubMic(getUserMedia);
    vi.mocked(speechApi.transcribeAudio).mockResolvedValue({
      text: "find the mug",
      language: "en",
      duration_seconds: 1,
      latency_ms: 10,
    });

    const { result } = renderHook(() => useSpeech(), { wrapper: SpeechProvider });

    expect(result.current.state).toBe("idle");

    await act(async () => {
      await result.current.startListening();
    });
    expect(result.current.state).toBe("listening");

    await act(async () => {
      result.current.stopListening();
    });

    await waitFor(() => expect(result.current.state).toBe("transcribed"));
    expect(result.current.transcript).toBe("find the mug");
  });

  it("reports no_speech_detected when Whisper returns empty text", async () => {
    const getUserMedia = vi.fn().mockResolvedValue(fakeStream);
    stubMic(getUserMedia);
    vi.mocked(speechApi.transcribeAudio).mockResolvedValue({
      text: "   ",
      language: null,
      duration_seconds: 0.1,
      latency_ms: 5,
    });

    const { result } = renderHook(() => useSpeech(), { wrapper: SpeechProvider });
    await act(async () => {
      await result.current.startListening();
    });
    await act(async () => {
      result.current.stopListening();
    });

    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(result.current.errorKind).toBe("no_speech_detected");
  });

  it("maps a transcription backend failure to an error state without throwing", async () => {
    const getUserMedia = vi.fn().mockResolvedValue(fakeStream);
    stubMic(getUserMedia);
    const { ApiError } = await import("../api/client");
    vi.mocked(speechApi.transcribeAudio).mockRejectedValue(
      new ApiError(503, { category: "model_unavailable", message: "Whisper not loaded." }),
    );

    const { result } = renderHook(() => useSpeech(), { wrapper: SpeechProvider });
    await act(async () => {
      await result.current.startListening();
    });
    await act(async () => {
      result.current.stopListening();
    });

    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(result.current.errorKind).toBe("whisper_unavailable");
  });

  it("markTaskCreated/reset move the state machine as expected", async () => {
    const getUserMedia = vi.fn().mockResolvedValue(fakeStream);
    stubMic(getUserMedia);
    vi.mocked(speechApi.transcribeAudio).mockResolvedValue({
      text: "find the mug",
      language: "en",
      duration_seconds: 1,
      latency_ms: 10,
    });
    const { result } = renderHook(() => useSpeech(), { wrapper: SpeechProvider });
    await act(async () => {
      await result.current.startListening();
    });
    await act(async () => {
      result.current.stopListening();
    });
    await waitFor(() => expect(result.current.state).toBe("transcribed"));

    act(() => result.current.markTaskCreated());
    expect(result.current.state).toBe("task_created");

    act(() => result.current.reset());
    expect(result.current.state).toBe("idle");
    expect(result.current.transcript).toBeNull();
  });
});
