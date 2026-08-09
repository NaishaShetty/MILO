"""
voice.py (backend/api/routes)

Purpose
-------
Implements `POST /api/v1/voice/transcribe` and `POST /api/v1/voice/speak`
-- the HTTP entry points for Phase 8.2's ElevenLabs voice subsystem.
Mirrors `routes/speech.py`'s "503 when unavailable, never a crash"
boundary discipline exactly: a thin HTTP wrapper around `agents.
voice_agent.VoiceAgent`, no ElevenLabs logic of its own.

Why `/speak` accepts EITHER a `task_id` OR raw `text`
------------------------------------------------------------------------
The primary caller (per the Phase 8.2 plan's voice pipeline) already
has a `task_id` and wants MILO's real spoken summary of that task --
`task_id` mode looks the real `TaskState` up via `routes.tasks._store`
(the same store `GET /api/v1/tasks/{id}` reads) and composes grounded
text via `VoiceAgent.compose_response_text()`. `text` mode exists for
callers that already have text to speak (e.g. a fixed UI prompt) and
should not need to fabricate a fake task just to hear it -- both modes
end at the same `VoiceAgent.speak()` call.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, model_validator

from agents.voice_agent import VoiceAgent
from voice.errors import VoiceRuntimeError

logger = logging.getLogger(__name__)

router = APIRouter()

_VOICE_UNAVAILABLE_MESSAGE = (
    "Voice is not available on this server (VOICE_ENABLE_ELEVENLABS is "
    "not set, or ELEVENLABS_API_KEY is missing). See backend/voice/config.py."
)

_STATUS_FOR_CODE = {
    "VOICE_UNAVAILABLE": 503,
    "EMPTY_AUDIO": 422,
    "INVALID_AUDIO_FORMAT": 422,
    "TRANSCRIPTION_FAILED": 502,
    "UNINTELLIGIBLE": 422,
    "EMPTY_TEXT": 422,
    "SYNTHESIS_FAILED": 502,
}


class VoiceStatusResponse(BaseModel):
    """Response body for `GET /voice` -- real, current configuration.
    Never includes the API key (see `voice/config.py`'s security note:
    the key is never stored on `VoiceConfig` in the first place)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    available: bool
    provider: str = "elevenlabs"
    voice_id: str


@router.get(
    "",
    summary="Real ElevenLabs voice configuration status",
    description=(
        "Never 503s -- reports the real configured state (enabled/"
        "available/voice_id) so a caller (e.g. Settings' Speech & "
        "Voice section) can show an honest disabled state rather than "
        "treating 'not configured' as an error."
    ),
)
def get_voice_status(request: Request) -> VoiceStatusResponse:
    config = request.app.state.voice_config
    voice_agent: VoiceAgent = request.app.state.voice_agent
    return VoiceStatusResponse(
        enabled=config.enabled,
        available=voice_agent.is_available(),
        voice_id=config.voice_id,
    )


def get_voice_agent(request: Request) -> VoiceAgent:
    """FastAPI dependency returning the `VoiceAgent` constructed at
    application startup. Raises 503 if unavailable -- same pattern as
    `routes/speech.py::get_speech_agent`."""
    voice_agent = request.app.state.voice_agent
    if voice_agent is None or not voice_agent.is_available():
        raise HTTPException(
            status_code=503,
            detail={
                "category": "voice_unavailable",
                "message": _VOICE_UNAVAILABLE_MESSAGE,
            },
        )
    return voice_agent


def _map_error(exc: VoiceRuntimeError) -> HTTPException:
    logger.warning("voice_api.request_failed", extra={"code": exc.code.value})
    return HTTPException(
        status_code=_STATUS_FOR_CODE.get(exc.code.value, 500),
        detail={"category": exc.code.value.lower(), "message": exc.message},
    )


@router.post(
    "/transcribe",
    summary="Transcribe an audio recording to text via ElevenLabs",
    responses={
        422: {"description": "Empty, invalid, or unintelligible audio."},
        502: {"description": "ElevenLabs raised while transcribing."},
        503: {"description": "Voice is not available."},
    },
)
async def transcribe(
    file: UploadFile,
    voice_agent: VoiceAgent = Depends(get_voice_agent),
) -> dict:
    audio_bytes = await file.read()
    try:
        result = voice_agent.transcribe(audio_bytes)
    except VoiceRuntimeError as exc:
        raise _map_error(exc) from None
    return result.model_dump(mode="json")


class SpeakRequest(BaseModel):
    """Body for `POST /voice/speak` -- exactly one of `task_id`/`text`. See
    module docstring."""

    model_config = ConfigDict(extra="forbid")

    task_id: Optional[str] = None
    text: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "SpeakRequest":
        if bool(self.task_id) == bool(self.text):
            raise ValueError("Exactly one of task_id or text must be provided.")
        return self


@router.post(
    "/speak",
    summary="Synthesize MILO's spoken response as audio",
    responses={
        404: {"description": "task_id does not refer to a known task."},
        422: {"description": "Empty text, or neither/both of task_id/text given."},
        502: {"description": "ElevenLabs raised while synthesizing."},
        503: {"description": "Voice is not available."},
    },
)
def speak(
    body: SpeakRequest,
    voice_agent: VoiceAgent = Depends(get_voice_agent),
) -> Response:
    # Imported here, not at module top, to avoid a circular import
    # (routes/tasks.py registers this app's routers; both modules are
    # only ever imported from api/app.py, but this keeps the direction
    # unambiguous) -- same pattern `routes/agents.py` already uses for
    # `from api.routes.tasks import _store`.
    from api.routes.tasks import _store

    if body.task_id:
        task_state = _store.get(body.task_id)
        if task_state is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "category": "task_not_found",
                    "message": f"No task with id {body.task_id!r}.",
                },
            )
        text = voice_agent.compose_response_text(task_state)
    else:
        text = body.text or ""

    try:
        audio_bytes = voice_agent.speak(text)
    except VoiceRuntimeError as exc:
        raise _map_error(exc) from None
    return Response(content=audio_bytes, media_type="audio/mpeg")
