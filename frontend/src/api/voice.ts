// voice.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// Phase 8.2 Voice API (`backend/api/routes/voice.py`) -- mirrors
// `tasks.ts`/`memory.ts`'s "centralized API client per domain"
// convention. `getVoiceStatus()` backs Settings' "Speech & Voice"
// section today; transcribe/speak calls are added in Stage 4.

import { ApiError, request } from "./client";
import type { VoiceStatus } from "./voiceTypes";

export { ApiError as VoiceApiError };

/** `GET /api/v1/voice` -- real config status, never 503s. */
export async function getVoiceStatus(): Promise<VoiceStatus> {
  return request<VoiceStatus>("/api/v1/voice");
}
