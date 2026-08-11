"""
test_speech_whisper_client.py

Purpose
-------
Unit tests for `speech.whisper_client.WhisperTranscriber`: every
documented failure mode (section 7.15) plus a successful transcription,
using a fake in-memory model (never `openai-whisper`/`ffmpeg`/network)
-- mirrors this suite's existing "inject a fake collaborator, never
call from_config() in tests" discipline (`test_language_agent.py`,
`test_memory_agent.py`).
"""

from __future__ import annotations

from typing import Optional

import pytest

from speech.config import SpeechConfig
from speech.errors import (
    EmptyAudioError,
    InvalidAudioFormatError,
    ModelUnavailableError,
    TranscriptionFailedError,
    UnintelligibleAudioError,
)
from speech.whisper_client import WhisperTranscriber


class _FakeWhisperModel:
    def __init__(self, result=None, exc: Optional[Exception] = None) -> None:
        self._result = result if result is not None else {"text": "find the mug"}
        self._exc = exc
        self.received_path: Optional[str] = None

    def transcribe(self, path: str):
        self.received_path = path
        if self._exc is not None:
            raise self._exc
        return self._result


def test_transcribe_returns_text_and_language():
    model = _FakeWhisperModel(
        result={"text": "Bring me the red mug.", "language": "en"}
    )
    transcriber = WhisperTranscriber(model=model)

    result = transcriber.transcribe(b"fake-audio-bytes")

    assert result.text == "Bring me the red mug."
    assert result.language == "en"
    assert result.latency_ms >= 0.0
    assert model.received_path is not None


def test_transcribe_unavailable_when_no_model():
    transcriber = WhisperTranscriber(model=None)
    with pytest.raises(ModelUnavailableError):
        transcriber.transcribe(b"anything")


def test_transcribe_rejects_empty_audio():
    transcriber = WhisperTranscriber(model=_FakeWhisperModel())
    with pytest.raises(EmptyAudioError):
        transcriber.transcribe(b"")


def test_transcribe_maps_ffmpeg_failure_to_invalid_audio_format():
    model = _FakeWhisperModel(exc=RuntimeError("ffmpeg exited with code 1"))
    transcriber = WhisperTranscriber(model=model)
    with pytest.raises(InvalidAudioFormatError):
        transcriber.transcribe(b"not-real-audio")


def test_transcribe_maps_other_failures_to_transcription_failed():
    model = _FakeWhisperModel(exc=RuntimeError("out of memory"))
    transcriber = WhisperTranscriber(model=model)
    with pytest.raises(TranscriptionFailedError):
        transcriber.transcribe(b"some-audio-bytes")


def test_transcribe_raises_unintelligible_for_empty_transcript():
    model = _FakeWhisperModel(result={"text": "   "})
    transcriber = WhisperTranscriber(model=model)
    with pytest.raises(UnintelligibleAudioError):
        transcriber.transcribe(b"some-audio-bytes")


def test_from_config_disabled_is_unavailable():
    config = SpeechConfig(
        enabled=False, model_size="base", device="cpu", stt_provider="whisper"
    )
    transcriber = WhisperTranscriber.from_config(config)
    assert transcriber.is_available() is False


def test_from_config_enabled_without_whisper_installed_degrades_gracefully():
    # `openai-whisper` is not guaranteed to be installed in every
    # environment this suite runs in (see requirements.txt's comment) --
    # from_config() must never raise even when enabled=True and the
    # import/load fails.
    config = SpeechConfig(
        enabled=True, model_size="base", device="cpu", stt_provider="whisper"
    )
    transcriber = WhisperTranscriber.from_config(config)
    assert isinstance(transcriber.is_available(), bool)
