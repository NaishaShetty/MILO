// speechTypes.ts
//
// Purpose
// -------
// TypeScript types for the Phase 7 Speech API
// (`POST /api/v1/speech/transcribe`) served by
// `backend/api/routes/speech.py`. Mirrors `backend/speech/models.py`'s
// `TranscriptionResult`.

// Mirrors `backend/speech/models.py`'s `TranscriptionResult`.
export interface TranscriptionResult {
  text: string;
  language: string | null;
  duration_seconds: number | null;
  latency_ms: number;
}

// The frontend-only speech lifecycle state machine this UI drives the
// mic/upload flow through (spec: IDLE -> LISTENING -> PROCESSING ->
// TRANSCRIBING -> TRANSCRIBED -> TASK_CREATED, or ERROR at any point).
// Not a backend type -- `backend/speech/models.py` has no equivalent
// enum exposed over HTTP; this is purely UI state.
export type SpeechLifecycleState =
  | "idle"
  | "listening"
  | "processing"
  | "transcribing"
  | "transcribed"
  | "task_created"
  | "error";

// Every distinct failure mode this UI must display per spec Part 8 --
// deliberately not the backend's HTTP error `category` strings 1:1
// (some of these, like `mic_unavailable`/`permission_denied`, never
// reach the backend at all -- they fail in the browser before any
// request is made).
export type SpeechErrorKind =
  | "mic_unavailable"
  | "permission_denied"
  | "no_speech_detected"
  | "transcription_failed"
  | "whisper_unavailable"
  | "backend_unavailable";
