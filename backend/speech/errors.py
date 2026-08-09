"""
errors.py (backend/speech)

Purpose
-------
The exception vocabulary for `backend/speech/` -- mirrors `language/
exceptions.py`'s "one closed hierarchy, one subclass per pipeline
stage that can fail" shape exactly, so `SpeechRuntimeError` is the one
thing a caller (`agents.speech_agent.SpeechAgent`, `api/routes/
speech.py`) needs to catch to handle any speech failure, with more
specific subclasses available where a caller wants to react
differently (e.g. map `EmptyAudioError` to a 422, `ModelUnavailableError`
to a 503).

Why microphone/permission errors are NOT modeled here
------------------------------------------------------------
Section 7.15's failure list also includes "microphone unavailable" and
"microphone permission failure" -- both are physically detectable only
in the browser (this is a server-side package that receives audio
bytes over HTTP; it never touches a microphone). Inventing a backend
error code for a browser-only failure would be exactly the kind of
"invent data instead of exposing what's real" this project's
instructions forbid. Those two states belong entirely to Session 3's
frontend `SpeechState` machine, documented there, not here.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class SpeechErrorCode(str, Enum):
    """
    Every category of speech-pipeline failure this backend package can
    report -- section 7.15's list, minus the two browser-only states
    (see module docstring).
    """

    EMPTY_AUDIO = "EMPTY_AUDIO"
    INVALID_AUDIO_FORMAT = "INVALID_AUDIO_FORMAT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
    UNINTELLIGIBLE = "UNINTELLIGIBLE"


class SpeechRuntimeError(Exception):
    """Base class for every exception raised anywhere in `backend/speech/`."""

    def __init__(self, code: SpeechErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EmptyAudioError(SpeechRuntimeError):
    """Raised for a zero-byte or silence-only audio payload."""

    def __init__(
        self, message: str = "Audio payload is empty or contains no speech."
    ) -> None:
        super().__init__(SpeechErrorCode.EMPTY_AUDIO, message)


class InvalidAudioFormatError(SpeechRuntimeError):
    """Raised when the uploaded bytes cannot be decoded as audio at all."""

    def __init__(
        self, message: str = "Uploaded file is not a supported audio format."
    ) -> None:
        super().__init__(SpeechErrorCode.INVALID_AUDIO_FORMAT, message)


class ModelUnavailableError(SpeechRuntimeError):
    """
    Raised when Whisper was never enabled/configured (mirrors
    `VisionSystem`'s "not configured" state, not a runtime failure of
    an otherwise-working model -- see `ModelLoadFailedError` for that).
    """

    def __init__(self, message: str = "Speech transcription is not available.") -> None:
        super().__init__(SpeechErrorCode.MODEL_UNAVAILABLE, message)


class ModelLoadFailedError(SpeechRuntimeError):
    """Raised when Whisper was enabled but the model failed to load."""

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(SpeechErrorCode.MODEL_LOAD_FAILED, message)
        self.__cause__ = cause


class TranscriptionFailedError(SpeechRuntimeError):
    """Raised when a loaded Whisper model raised while transcribing."""

    def __init__(self, message: str = "Transcription failed.") -> None:
        super().__init__(SpeechErrorCode.TRANSCRIPTION_FAILED, message)


class UnintelligibleAudioError(SpeechRuntimeError):
    """
    Raised when Whisper ran successfully but produced an empty/
    whitespace-only transcript -- not a crash, but not usable speech
    either (silence, noise, or genuinely unintelligible audio).
    """

    def __init__(self, message: str = "Could not understand the audio.") -> None:
        super().__init__(SpeechErrorCode.UNINTELLIGIBLE, message)
