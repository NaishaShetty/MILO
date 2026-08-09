"""
speech.py (backend/api/routes)

Purpose
-------
Implements `POST /api/v1/speech/transcribe` -- the HTTP entry point for
the Phase 7.14 speech subsystem. Mirrors `routes/vision.py`'s shape and
"503 when unavailable, never a crash" boundary discipline exactly: a
thin HTTP wrapper around `agents.speech_agent.SpeechAgent`, no
transcription logic of its own.

Why this endpoint only transcribes -- it never creates a task
------------------------------------------------------------------------
Section 7.14's "there must not be separate speech and text planning
systems" rule means the only thing this route is allowed to produce is
a transcript. Turning that transcript into a task is a second, explicit
`POST /api/v1/tasks` call (with `input_source="speech"`) through the
exact same `LanguageAgent`/`Orchestrator` path text input already
uses -- see `routes/tasks.py`. Session 3's frontend chains the two
calls; this route has no knowledge that a "task" concept exists at all
(no import of `schemas.task`, `orchestration`, or `agents.task_state`
anywhere in this file).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from agents.speech_agent import SpeechAgent
from speech.errors import SpeechRuntimeError

logger = logging.getLogger(__name__)

router = APIRouter()

_SPEECH_UNAVAILABLE_MESSAGE = (
    "Speech transcription is not available on this server "
    "(SPEECH_ENABLE_WHISPER is not set, or the Whisper model failed to "
    "load). See backend/speech/config.py."
)

#: `SpeechErrorCode` -> HTTP status. `MODEL_UNAVAILABLE` is a startup-
#: time fact (503, matching `routes/vision.py`'s identical convention);
#: every other code describes something wrong with *this request's*
#: audio (422) -- never a client's fault vs. server's fault confusion.
_STATUS_FOR_CODE = {
    "MODEL_UNAVAILABLE": 503,
    "MODEL_LOAD_FAILED": 503,
    "EMPTY_AUDIO": 422,
    "INVALID_AUDIO_FORMAT": 422,
    "TRANSCRIPTION_FAILED": 502,
    "UNINTELLIGIBLE": 422,
}


def get_speech_agent(request: Request) -> SpeechAgent:
    """FastAPI dependency returning the `SpeechAgent` constructed at
    application startup. Raises 503 if none was constructed -- same
    "dependency function, not a module-level global" testability
    rationale as `routes/vision.py::get_vision_system`."""
    speech_agent = request.app.state.speech_agent
    if speech_agent is None:
        raise HTTPException(
            status_code=503,
            detail={
                "category": "speech_unavailable",
                "message": _SPEECH_UNAVAILABLE_MESSAGE,
            },
        )
    return speech_agent


@router.post(
    "/transcribe",
    summary="Transcribe an audio recording to text",
    description=(
        "Accepts an audio file upload and returns its transcript via "
        "the configured Whisper model. Does not parse, plan, or create "
        "a task -- see this module's docstring."
    ),
    responses={
        422: {"description": "Empty, invalid, or unintelligible audio."},
        502: {"description": "The Whisper model raised while transcribing."},
        503: {"description": "Speech transcription is not available."},
    },
)
async def transcribe(
    file: UploadFile,
    speech_agent: SpeechAgent = Depends(get_speech_agent),
) -> dict:
    audio_bytes = await file.read()
    try:
        result = speech_agent.transcribe(audio_bytes)
    except SpeechRuntimeError as exc:
        logger.warning("speech_api.transcribe_failed", extra={"code": exc.code.value})
        raise HTTPException(
            status_code=_STATUS_FOR_CODE.get(exc.code.value, 500),
            detail={"category": exc.code.value.lower(), "message": exc.message},
        ) from None
    return result.model_dump(mode="json")
