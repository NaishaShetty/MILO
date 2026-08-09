"""
voice_agent.py (backend/agents)

Purpose
-------
`VoiceAgent` -- the `BaseAgent` shape around `voice.elevenlabs_client.
ElevenLabsClient`, mirroring `agents.speech_agent.SpeechAgent`'s shape
exactly (see that module's docstring): `transcribe()`/`speak()` are
direct delegations, translating `voice.errors.VoiceRuntimeError` into
`AgentState` transitions so Mission Control's agent-status list has a
real "voice" row alongside "speech".

Why this agent never touches `schemas.task`/`language`/`planner`
directly for transcription, but IS allowed to call `voice.
response_composer`
------------------------------------------------------------------------
`transcribe()` follows `SpeechAgent`'s exact "audio in, transcript out,
nothing else" boundary. `speak(task_state, memories)`, however, is
this package's TTS half -- it legitimately needs `voice.
response_composer.compose_spoken_response()` (which reads `TaskState`/
`MemoryResult`, see that module's docstring) to have real text to
synthesize. Turning a transcript into a task remains entirely
`language.agent.LanguageAgent`'s job; this agent never does that
itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Sequence

from agents.base import BaseAgent
from agents.contracts import AgentError, AgentRequest, AgentResponse, AgentState
from voice.elevenlabs_client import ElevenLabsClient
from voice.errors import VoiceRuntimeError
from voice.models import VoiceTranscription
from voice.response_composer import compose_spoken_response

if TYPE_CHECKING:
    from agents.task_state import TaskState
    from memory.retrieval import MemoryResult


class VoiceAgent(BaseAgent):
    """Thin `BaseAgent` wrapper around `voice.elevenlabs_client.ElevenLabsClient`.
    See module docstring."""

    name = "voice"

    def __init__(self, client: ElevenLabsClient) -> None:
        super().__init__()
        self._client = client

    def is_available(self) -> bool:
        return self._client.is_available()

    def transcribe(self, audio_bytes: bytes) -> VoiceTranscription:
        self._state = AgentState.ACTIVE
        try:
            result = self._client.transcribe(audio_bytes)
        except VoiceRuntimeError:
            self._state = AgentState.ERROR
            raise
        self._state = AgentState.IDLE
        return VoiceTranscription(
            text=result.text,
            language_code=result.language_code,
            latency_ms=result.latency_ms,
        )

    def compose_response_text(
        self,
        task_state: "TaskState",
        memories: Optional[Sequence["MemoryResult"]] = None,
    ) -> str:
        """Real, grounded spoken text for `task_state` -- see
        `voice.response_composer` for the grounding policy. Never raises
        (that module's own fallback contract)."""
        return compose_spoken_response(task_state, memories)

    def speak(self, text: str) -> bytes:
        """Synthesizes `text` as MP3 bytes via ElevenLabs TTS."""
        self._state = AgentState.ACTIVE
        try:
            audio = self._client.synthesize(text)
        except VoiceRuntimeError:
            self._state = AgentState.ERROR
            raise
        self._state = AgentState.IDLE
        return audio

    def process(self, request: AgentRequest) -> AgentResponse:
        """
        Generic dispatch entry point (see `BaseAgent`) -- not the real
        call path. `api/routes/voice.py` calls `transcribe()`/`speak()`
        directly with real bytes/text, exactly like `SpeechAgent`
        bypasses this for its own route. Kept only to satisfy
        `BaseAgent`'s contract for `AgentRegistry` walks.
        """
        return AgentResponse(
            request_id=request.request_id,
            success=False,
            error=AgentError(
                agent=self.name,
                message=f"unsupported operation: {request.operation!r} "
                "-- use transcribe()/speak() directly",
            ),
        )
