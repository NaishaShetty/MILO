// speech.test.ts
//
// Purpose
// -------
// Unit tests for the centralized Speech API client and its
// backend-error-to-`SpeechErrorKind` mapping.
import { afterEach, describe, expect, it, vi } from "vitest";

import { mapSpeechError, transcribeAudio } from "./speech";
import { ApiError } from "./client";

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

describe("transcribeAudio", () => {
  it("POSTs the audio as multipart form data", async () => {
    mockFetchOnce(200, { text: "find the mug", language: "en", duration_seconds: 1.2, latency_ms: 40 });

    await transcribeAudio(new Blob(["audio"], { type: "audio/webm" }));

    const call = vi.mocked(fetch).mock.calls[0];
    expect(call[0]).toBe("/api/v1/speech/transcribe");
    const init = call[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBeInstanceOf(Blob);
  });

  it("resolves with the backend's TranscriptionResult", async () => {
    const body = { text: "find the mug", language: "en", duration_seconds: 1.2, latency_ms: 40 };
    mockFetchOnce(200, body);
    await expect(transcribeAudio(new Blob(["audio"]))).resolves.toEqual(body);
  });

  it("throws ApiError on failure", async () => {
    mockFetchOnce(422, { category: "empty_audio", message: "No speech detected." });
    await expect(transcribeAudio(new Blob(["audio"]))).rejects.toBeInstanceOf(ApiError);
  });
});

describe("mapSpeechError", () => {
  it.each([
    ["model_unavailable", "whisper_unavailable"],
    ["model_load_failed", "whisper_unavailable"],
    ["speech_unavailable", "whisper_unavailable"],
    ["empty_audio", "no_speech_detected"],
    ["unintelligible", "no_speech_detected"],
    ["invalid_audio_format", "transcription_failed"],
    ["transcription_failed", "transcription_failed"],
    ["something_unrecognized", "backend_unavailable"],
  ])("maps category %s to %s", (category, expected) => {
    const error = new ApiError(500, { category, message: "x" });
    expect(mapSpeechError(error)).toBe(expected);
  });

  it("maps a non-ApiError (e.g. a rejected fetch) to backend_unavailable", () => {
    expect(mapSpeechError(new TypeError("Failed to fetch"))).toBe("backend_unavailable");
  });
});
