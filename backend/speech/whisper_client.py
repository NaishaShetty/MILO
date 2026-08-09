"""
whisper_client.py (backend/speech)

Purpose
-------
`WhisperTranscriber` -- the one component in this package that
actually calls a Whisper model. Section 7.14's entire "Whisper ->
Text" contract lives here; nothing above this file (`agents.
speech_agent.SpeechAgent`, `api/routes/speech.py`) knows this project
uses `openai-whisper` specifically, or how a model is loaded --
exactly the same "implementation detail stays inside the owning
package" boundary `language/llm_client.py` already establishes for the
LLM provider.

Why the `whisper` package is imported lazily, inside `from_config()`
------------------------------------------------------------------------
`openai-whisper` is a heavy, optional dependency (see `requirements.txt`'s
comment on it) -- importing it at module load time would mean this
whole package, and everything that transitively imports it
(`agents.speech_agent`, `api/routes/speech.py`, `api/app.py`), fails to
import at all in an environment where it isn't installed. Mirrors
`vision/factory.py`'s identical rationale for its own optional heavy
imports. `from_config()` never raises for a missing/failed import --
it returns a `WhisperTranscriber` with `is_available() == False`,
same graceful-degradation contract as `memory.agent.MemoryAgent.
from_config()`.

Why the loaded model is injected via `__init__`, not built inside
`transcribe()`
------------------------------------------------------------------------
Keeps this class trivially testable: a test constructs
`WhisperTranscriber(model=<fake with a .transcribe(path) method>)`
directly and asserts on `transcribe()`'s behavior with zero network
access, zero GPU, and zero real model weights -- mirrors `language.
agent.LanguageAgent`'s "constructor takes already-constructed
collaborators" testability rationale exactly. `from_config()` is the
one production factory that does the real, heavyweight loading.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Any, Optional

from speech.config import SpeechConfig
from speech.errors import (
    EmptyAudioError,
    InvalidAudioFormatError,
    ModelUnavailableError,
    TranscriptionFailedError,
    UnintelligibleAudioError,
)
from speech.models import TranscriptionResult

logger = logging.getLogger(__name__)


class WhisperTranscriber:
    """Wraps one loaded Whisper model. See module docstring."""

    def __init__(self, model: Optional[Any]) -> None:
        # `model is None` is the "unavailable" state -- see
        # `from_config()`. Every public method checks this first.
        self._model = model

    @classmethod
    def from_config(cls, config: SpeechConfig) -> "WhisperTranscriber":
        """
        Production entry point. Never raises: if `config.enabled` is
        `False`, or the `whisper` package/model fails to import/load
        for any reason, returns a `WhisperTranscriber` with
        `is_available() == False` instead of taking down whatever is
        starting up the API -- see module docstring.
        """
        if not config.enabled:
            return cls(model=None)
        try:
            import whisper  # deliberately lazy import -- see module docstring

            model = whisper.load_model(config.model_size, device=config.device)
        except Exception:
            logger.warning("whisper_client.unavailable", exc_info=True)
            return cls(model=None)
        return cls(model=model)

    def is_available(self) -> bool:
        return self._model is not None

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """
        Transcribes `audio_bytes` (an arbitrary audio file's raw
        bytes, e.g. a `.wav`/`.webm` upload) into a `TranscriptionResult`.
        Raises a `speech.errors.SpeechRuntimeError` subclass for every
        documented failure mode (section 7.15) -- never lets a raw
        `whisper`/`ffmpeg` exception escape this method.
        """
        if self._model is None:
            raise ModelUnavailableError()
        if not audio_bytes:
            raise EmptyAudioError()

        started_at = time.perf_counter()
        tmp_path = self._write_temp_file(audio_bytes)
        try:
            result = self._model.transcribe(tmp_path)
        except Exception as exc:
            # `whisper`/its `ffmpeg` subprocess raises a broad range of
            # exception types for "this isn't decodable audio" (a
            # missing ffmpeg binary, a corrupt/unsupported container) --
            # narrowed here to this package's own vocabulary rather
            # than requiring every caller to know whisper's internals.
            message = str(exc) or exc.__class__.__name__
            if "ffmpeg" in message.lower() or "format" in message.lower():
                raise InvalidAudioFormatError(
                    f"Could not decode uploaded audio: {message}"
                ) from exc
            raise TranscriptionFailedError(message) from exc
        finally:
            os.remove(tmp_path)
        latency_ms = (time.perf_counter() - started_at) * 1000.0

        text = str(result.get("text", "")).strip()
        if not text:
            raise UnintelligibleAudioError()

        return TranscriptionResult(
            text=text,
            language=result.get("language"),
            duration_seconds=None,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _write_temp_file(audio_bytes: bytes) -> str:
        # `whisper.load_audio()` (called internally by `model.
        # transcribe()`) shells out to `ffmpeg` on a file path, not an
        # in-memory buffer -- a temp file is the interface it expects.
        # `delete=False` + explicit `os.remove()` in `transcribe()`'s
        # `finally` (rather than a `with` block) since the file must
        # still exist on disk for `ffmpeg` to read after this function
        # returns the path.
        fd, path = tempfile.mkstemp(suffix=".audio")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(audio_bytes)
        except Exception:
            os.remove(path)
            raise
        return path
