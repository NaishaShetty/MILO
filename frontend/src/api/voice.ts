// voice.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// Phase 8.2 Voice API (`backend/api/routes/voice.py`) -- mirrors
// `tasks.ts`/`memory.ts`'s "centralized API client per domain"
// convention. `getVoiceStatus()` backs Settings' "Speech & Voice"
// section; `transcribe()`/`speak()` back Stage 4's voice pipeline
// (`VoiceContext.tsx`).

import { ApiError, request, requestForm } from "./client";
import type { SpokenResponse, VoiceStatus, VoiceTranscription } from "./voiceTypes";

export { ApiError as VoiceApiError };

/** `GET /api/v1/voice` -- real config status, never 503s. */
export async function getVoiceStatus(): Promise<VoiceStatus> {
  return request<VoiceStatus>("/api/v1/voice");
}

/**
 * `POST /api/v1/voice/transcribe` (multipart/form-data, field `file`)
 * -- ElevenLabs speech-to-text. Mirrors `speech.ts::transcribeAudio()`'s
 * shape exactly; throws `ApiError` for 422/502/503.
 */
export async function transcribe(audio: Blob): Promise<VoiceTranscription> {
  const form = new FormData();
  form.append("file", audio, "speech.webm");
  return requestForm<VoiceTranscription>("/api/v1/voice/transcribe", form);
}

/**
 * `POST /api/v1/voice/speak` -- real MILO speech, audio + the exact
 * text that produced it (from the `X-Milo-Response-Text` header, see
 * `routes/voice.py`'s docstring on why that header exists). Not built
 * on `request()`/`requestForm()`: the response body is raw audio
 * bytes, not JSON, and a header needs to be read alongside it.
 * Relative-URL only, same rule as every other API module.
 */
export async function speak(body: { taskId: string } | { text: string }): Promise<SpokenResponse> {
  const payload = "taskId" in body ? { task_id: body.taskId } : { text: body.text };
  const response = await fetch("/api/v1/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let errorBody = { category: "internal_error", message: "MILO could not speak right now." };
    try {
      const parsed = await response.json();
      if (typeof parsed.message === "string" && typeof parsed.category === "string") {
        errorBody = parsed;
      }
    } catch {
      // Non-JSON error body -- fall back to the generic message above.
    }
    throw new ApiError(response.status, errorBody);
  }
  const encodedText = response.headers.get("X-Milo-Response-Text") ?? "";
  const audioBlob = await response.blob();
  return { audioBlob, text: decodeURIComponent(encodedText) };
}
