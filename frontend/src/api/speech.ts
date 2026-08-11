// speech.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// backend's Whisper-backed Speech API (`backend/api/routes/
// speech.py`). Mirrors `tasks.ts`/`agents.ts`'s "one file per domain"
// convention. `transcribeAudio()` is the sole way this frontend turns
// captured audio into text -- callers then pass that text to
// `tasks.ts::createTask(text, "speech")`, the same task-creation path
// text input uses, so speech never becomes a second, parallel task
// pipeline (see this project's explicit "do not duplicate the
// orchestrator" rule).

import { ApiError, request, requestForm } from "./client";
import type { SpeechErrorKind, SpeechStatus, TranscriptionResult } from "./speechTypes";

export { ApiError as SpeechApiError };

/** `GET /api/v1/speech` -- which STT backend is active. Never 503s. */
export async function getSpeechStatus(): Promise<SpeechStatus> {
  return request<SpeechStatus>("/api/v1/speech");
}

/**
 * `POST /api/v1/speech/transcribe` (multipart/form-data, field `file`).
 * Throws `ApiError` for 422 (empty/unintelligible/malformed audio),
 * 502 (transcription failed), or 503 (Whisper/speech agent
 * unavailable) -- see `mapSpeechError()` to translate that into the
 * UI's `SpeechErrorKind`.
 */
export async function transcribeAudio(audio: Blob): Promise<TranscriptionResult> {
  const form = new FormData();
  form.append("file", audio, "speech.webm");
  return requestForm<TranscriptionResult>("/api/v1/speech/transcribe", form);
}

/**
 * Maps a backend `ApiError` (or a browser-side failure) from the
 * speech flow onto the UI's fixed set of `SpeechErrorKind`s (spec Part
 * 8). Backend `category` strings are the source of truth; anything
 * unrecognized falls back to `backend_unavailable` (the safest
 * "something is wrong on the server side" bucket) rather than
 * `transcription_failed`, which would incorrectly imply Whisper itself
 * ran and rejected the audio.
 */
export function mapSpeechError(error: unknown): SpeechErrorKind {
  if (error instanceof ApiError) {
    switch (error.category) {
      case "model_unavailable":
      case "model_load_failed":
      case "speech_unavailable":
        return "whisper_unavailable";
      case "empty_audio":
      case "unintelligible":
        return "no_speech_detected";
      case "invalid_audio_format":
      case "transcription_failed":
        return "transcription_failed";
      default:
        return "backend_unavailable";
    }
  }
  return "backend_unavailable";
}
