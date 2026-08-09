// voiceTypes.ts
//
// Purpose
// -------
// TypeScript types for the Phase 8.2 Voice API (`backend/api/routes/
// voice.py`). `VoiceStatus` mirrors `GET /api/v1/voice`'s real
// response shape -- used today by Settings' "Speech & Voice" section;
// transcribe/speak types are added in Stage 4 alongside the
// interactive voice pipeline.
export interface VoiceStatus {
  enabled: boolean;
  available: boolean;
  provider: string;
  voice_id: string;
}
