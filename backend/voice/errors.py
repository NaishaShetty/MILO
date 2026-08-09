"""
errors.py (backend/voice)

Purpose
-------
The exception vocabulary for `backend/voice/` -- mirrors `speech/
errors.py`'s "one closed hierarchy, one subclass per failure mode" shape
exactly, extended with the TTS-side failure modes Whisper-only
`speech/errors.py` never needed (ElevenLabs is STT *and* TTS).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class VoiceErrorCode(str, Enum):
    """Every category of voice-pipeline failure this package can report."""

    EMPTY_AUDIO = "EMPTY_AUDIO"
    INVALID_AUDIO_FORMAT = "INVALID_AUDIO_FORMAT"
    VOICE_UNAVAILABLE = "VOICE_UNAVAILABLE"
    TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
    UNINTELLIGIBLE = "UNINTELLIGIBLE"
    EMPTY_TEXT = "EMPTY_TEXT"
    SYNTHESIS_FAILED = "SYNTHESIS_FAILED"


class VoiceRuntimeError(Exception):
    """Base class for every exception raised anywhere in `backend/voice/`."""

    def __init__(self, code: VoiceErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class VoiceUnavailableError(VoiceRuntimeError):
    """
    Raised when ElevenLabs was never enabled/configured (`VOICE_ENABLE_
    ELEVENLABS` unset, or no API key present) -- mirrors `speech.errors.
    ModelUnavailableError`'s "not configured" state, not a runtime
    failure of an otherwise-working integration.
    """

    def __init__(self, message: str = "Voice is not available.") -> None:
        super().__init__(VoiceErrorCode.VOICE_UNAVAILABLE, message)


class EmptyAudioError(VoiceRuntimeError):
    """Raised for a zero-byte audio payload."""

    def __init__(self, message: str = "Audio payload is empty.") -> None:
        super().__init__(VoiceErrorCode.EMPTY_AUDIO, message)


class InvalidAudioFormatError(VoiceRuntimeError):
    """Raised when ElevenLabs rejects the uploaded bytes as undecodable audio."""

    def __init__(
        self, message: str = "Uploaded file is not a supported audio format."
    ) -> None:
        super().__init__(VoiceErrorCode.INVALID_AUDIO_FORMAT, message)


class TranscriptionFailedError(VoiceRuntimeError):
    """Raised when the ElevenLabs STT call itself failed (network, non-2xx, ...)."""

    def __init__(self, message: str = "Transcription failed.") -> None:
        super().__init__(VoiceErrorCode.TRANSCRIPTION_FAILED, message)


class UnintelligibleAudioError(VoiceRuntimeError):
    """Raised when ElevenLabs returned a successful but empty transcript."""

    def __init__(self, message: str = "Could not understand the audio.") -> None:
        super().__init__(VoiceErrorCode.UNINTELLIGIBLE, message)


class EmptyTextError(VoiceRuntimeError):
    """Raised when `synthesize()` is called with empty/whitespace-only text."""

    def __init__(self, message: str = "No text to speak.") -> None:
        super().__init__(VoiceErrorCode.EMPTY_TEXT, message)


class SynthesisFailedError(VoiceRuntimeError):
    """Raised when the ElevenLabs TTS call itself failed."""

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(VoiceErrorCode.SYNTHESIS_FAILED, message)
        self.__cause__ = cause
