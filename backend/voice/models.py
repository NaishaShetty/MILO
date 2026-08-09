"""
models.py (backend/voice)

Purpose
-------
The typed, JSON-serializable response shape for `backend/voice/`'s STT
side -- mirrors `speech.models.TranscriptionResult` exactly. `voice.
elevenlabs_client.TranscriptionResult` (a plain object, matching
`speech.whisper_client`'s "collaborator return value" convention) is
converted into this pydantic model at the API boundary, same split
`speech/` uses between its internal collaborator and its route response.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class VoiceTranscription(BaseModel):
    """One successful `ElevenLabsClient.transcribe()` result."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The transcribed text.")
    language_code: Optional[str] = Field(
        default=None, description="Language code ElevenLabs detected, e.g. 'en'."
    )
    latency_ms: float = Field(description="Wall-clock time spent transcribing.")
