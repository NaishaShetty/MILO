"""
models.py (backend/speech)

Purpose
-------
The typed data model for `backend/speech/`: `TranscriptionResult` (what
a successful transcription produces) and `SpeechState` (the lifecycle
`agents.speech_agent.SpeechAgent.get_state()` reports, restricted to
what this *backend* package can actually observe).

Why `SpeechState` has fewer values than the phase brief's full list
------------------------------------------------------------------------
Section 7.15 lists `IDLE, LISTENING, PROCESSING, TRANSCRIBING,
TRANSCRIBED, ERROR`. `LISTENING` describes audio *capture*, which
happens in the browser before this backend ever sees a byte -- this
package cannot truthfully report a state it has no visibility into.
`SpeechState` therefore covers exactly the states this backend
transitions through (`IDLE -> PROCESSING -> TRANSCRIBING ->
TRANSCRIBED|ERROR`); Session 3's frontend state machine adds
`LISTENING` on top, entirely client-side, before ever calling this
backend.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SpeechState(str, Enum):
    """Backend-observable speech lifecycle states. See module docstring."""

    IDLE = "idle"
    PROCESSING = "processing"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    ERROR = "error"


class TranscriptionResult(BaseModel):
    """One successful `WhisperTranscriber.transcribe()` result."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The transcribed text.")
    language: Optional[str] = Field(
        default=None, description="Language code Whisper detected, e.g. 'en'."
    )
    duration_seconds: Optional[float] = Field(
        default=None, description="Duration of the input audio, if known."
    )
    latency_ms: float = Field(description="Wall-clock time spent transcribing.")
