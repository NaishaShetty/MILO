"""
speech_agent.py (backend/agents)

Purpose
-------
`SpeechAgent` -- the `BaseAgent` shape around `speech.whisper_client.
WhisperTranscriber` (section 7.14). Adds no speech logic of its own:
`transcribe()` is a direct delegation, translating `speech.errors.
SpeechRuntimeError` into `AgentState` transitions
(`PROCESSING`/`TRANSCRIBING` while running, `ERROR` on failure, back to
`IDLE` on success) so Mission Control's "Whisper" row in the phase
brief's agent-status example has something real to show.

Why this agent never touches `schemas.task`/`language`/`planner`
------------------------------------------------------------------------
Enforced structurally: this file has no import of any of those
packages. `api/routes/speech.py` calls `SpeechAgent.transcribe()` and
returns the transcript; a *separate*, subsequent `POST /api/v1/tasks`
call (with `input_source="speech"`) is what turns that transcript into
a task, through the exact same `LanguageAgent`/`Orchestrator` path text
input already uses -- section 7.14's "there must not be separate
speech and text planning systems," satisfied by this agent simply
having no path into planning at all.
"""

from __future__ import annotations

from agents.base import BaseAgent
from agents.contracts import AgentError, AgentRequest, AgentResponse, AgentState
from speech.errors import SpeechRuntimeError
from speech.models import TranscriptionResult
from speech.whisper_client import WhisperTranscriber


class SpeechAgent(BaseAgent):
    """Thin `BaseAgent` wrapper around `speech.whisper_client.WhisperTranscriber`.
    See module docstring."""

    name = "speech"

    def __init__(self, transcriber: WhisperTranscriber) -> None:
        super().__init__()
        self._transcriber = transcriber

    def is_available(self) -> bool:
        return self._transcriber.is_available()

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        self._state = AgentState.ACTIVE
        try:
            result = self._transcriber.transcribe(audio_bytes)
        except SpeechRuntimeError:
            self._state = AgentState.ERROR
            raise
        self._state = AgentState.IDLE
        return result

    def process(self, request: AgentRequest) -> AgentResponse:
        """
        Supports one generic operation: `"transcribe"`, taking
        `payload={"audio_hex": "<hex-encoded audio bytes>"}` -- hex,
        not raw bytes, since `AgentRequest.payload` is a JSON-safe
        `Dict[str, Any]` (matches every other wrapper's `process()`
        contract); `api/routes/speech.py` calls `transcribe()` directly
        with the real `UploadFile` bytes instead, exactly like every
        other route in this project bypasses the generic `process()`
        entry point in favor of an agent's typed methods.
        """
        if request.operation != "transcribe":
            return AgentResponse(
                request_id=request.request_id,
                success=False,
                error=AgentError(
                    agent=self.name,
                    message=f"unsupported operation: {request.operation!r}",
                ),
            )
        audio_hex = request.payload.get("audio_hex")
        if not audio_hex:
            return AgentResponse(
                request_id=request.request_id,
                success=False,
                error=AgentError(
                    agent=self.name, message="payload.audio_hex is required"
                ),
            )
        try:
            result = self.transcribe(bytes.fromhex(audio_hex))
        except SpeechRuntimeError as exc:
            return AgentResponse(
                request_id=request.request_id,
                success=False,
                error=AgentError(
                    agent=self.name,
                    message=exc.message,
                    details={"code": exc.code.value},
                ),
            )
        return AgentResponse(
            request_id=request.request_id,
            success=True,
            data=result.model_dump(mode="json"),
        )
