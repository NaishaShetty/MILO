"""
elevenlabs_client.py (backend/voice)

Purpose
-------
`ElevenLabsClient` -- the one component in this package that actually
calls the ElevenLabs API. Mirrors `speech.whisper_client.WhisperTranscriber`'s
shape (constructor takes already-resolved config, `from_config()` is the
one production factory, never raises) and reuses `language.llm_client`'s
"plain `requests`, simple bounded retry, redact the secret from any
error text" transport pattern -- see that module's docstring for why
this project deliberately avoids a provider SDK.

Why this does not reuse `language.llm_client.post_json_with_retries`
verbatim
------------------------------------------------------------------------
That helper assumes a JSON request body and hands back the raw
`requests.Response` for the caller to interpret as JSON. `transcribe()`
here needs a multipart upload (`files=`), and `synthesize()` needs to
treat the response body as raw audio bytes, not JSON -- neither fits
the JSON-in assumption. `_post_with_retries` below reproduces the same
bounded-retry, no-backoff policy (documented in `llm_client.py` as a
considered choice for this project's load profile) for both request
shapes instead of forcing them through a JSON-only helper.

Credential handling policy
---------------------------------
Identical to `language.llm_client.OpenAICompatibleLLMClient`: the API
key is resolved from `os.environ[config.api_key_env_var]` inside each
call, never stored on `self`, and stripped from any exception text via
`_redact` before it can appear in a log or an HTTP error response.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

from voice.config import VoiceConfig
from voice.errors import (
    EmptyAudioError,
    EmptyTextError,
    InvalidAudioFormatError,
    SynthesisFailedError,
    TranscriptionFailedError,
    UnintelligibleAudioError,
    VoiceUnavailableError,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.elevenlabs.io/v1"
_STT_MODEL_ID = "scribe_v1"
_TTS_MODEL_ID = "eleven_multilingual_v2"
_MAX_ERROR_DETAIL_CHARS = 500


def _redact(text: str, secret: Optional[str]) -> str:
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")


def _safe_error_detail(body: str, secret: Optional[str]) -> str:
    redacted = _redact(body, secret)
    if len(redacted) > _MAX_ERROR_DETAIL_CHARS:
        return redacted[:_MAX_ERROR_DETAIL_CHARS] + "... [truncated]"
    return redacted


def _post_with_retries(
    *,
    url: str,
    headers: dict,
    timeout_seconds: float,
    max_retries: int,
    redact_secret: Optional[str],
    **kwargs,
) -> requests.Response:
    """Bounded-retry POST (no backoff/jitter) -- see module docstring."""
    attempts = max_retries + 1
    last_exc: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            return requests.post(
                url, headers=headers, timeout=timeout_seconds, **kwargs
            )
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt == attempts - 1:
                raise SynthesisFailedError(
                    f"ElevenLabs request failed after {attempts} attempt(s): "
                    f"{_redact(str(exc), redact_secret)}",
                    cause=exc,
                ) from exc
    raise AssertionError("unreachable") from last_exc


class TranscriptionResult:
    """One successful `transcribe()` result -- plain object, not pydantic,
    matching `speech.whisper_client`'s collaborator-return convention;
    `voice/models.py`'s `VoiceTranscription` is the pydantic envelope the
    API route actually returns (see that module)."""

    __slots__ = ("text", "language_code", "latency_ms")

    def __init__(
        self, text: str, language_code: Optional[str], latency_ms: float
    ) -> None:
        self.text = text
        self.language_code = language_code
        self.latency_ms = latency_ms


class ElevenLabsClient:
    """Wraps ElevenLabs STT + TTS. See module docstring."""

    def __init__(self, config: Optional[VoiceConfig]) -> None:
        # `config is None` is the "unavailable" state -- see
        # `from_config()`. Every public method checks this first.
        self._config = config

    @classmethod
    def from_config(cls, config: VoiceConfig) -> "ElevenLabsClient":
        """
        Production entry point. Never raises: if `config.enabled` is
        `False`, returns a client with `is_available() == False` --
        the actual API key is only checked (and only matters) at call
        time, per this package's credential policy, so a missing key
        with `enabled=True` still constructs fine here and fails
        per-call with a clear `VoiceUnavailableError` instead.
        """
        if not config.enabled:
            return cls(config=None)
        return cls(config=config)

    def is_available(self) -> bool:
        return self._config is not None

    def _resolve_api_key(self) -> str:
        assert self._config is not None
        api_key = os.environ.get(self._config.api_key_env_var)
        if not api_key:
            raise VoiceUnavailableError(
                f"{self._config.api_key_env_var} is not set -- voice is "
                "enabled (VOICE_ENABLE_ELEVENLABS=true) but no API key "
                "was found."
            )
        return api_key

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """
        Transcribes `audio_bytes` via ElevenLabs' speech-to-text
        endpoint. Raises a `voice.errors.VoiceRuntimeError` subclass for
        every documented failure mode -- never lets a raw `requests`
        exception escape this method. Mirrors `WhisperTranscriber.
        transcribe()`'s validation order (unavailable -> empty -> call
        -> empty-result) so the two packages behave predictably alike.
        """
        if self._config is None:
            raise VoiceUnavailableError()
        if not audio_bytes:
            raise EmptyAudioError()
        api_key = self._resolve_api_key()

        started_at = time.perf_counter()
        response = _post_with_retries(
            url=f"{_BASE_URL}/speech-to-text",
            headers={"xi-api-key": api_key},
            timeout_seconds=self._config.timeout_seconds,
            max_retries=self._config.max_retries,
            redact_secret=api_key,
            data={"model_id": _STT_MODEL_ID},
            files={"file": ("audio", audio_bytes, "application/octet-stream")},
        )
        if not response.ok:
            detail = _safe_error_detail(response.text, api_key)
            if response.status_code in (400, 422):
                raise InvalidAudioFormatError(
                    f"ElevenLabs rejected the uploaded audio: {detail}"
                )
            raise TranscriptionFailedError(
                f"ElevenLabs speech-to-text returned {response.status_code}: {detail}"
            )
        body = response.json()
        text = str(body.get("text", "")).strip()
        if not text:
            raise UnintelligibleAudioError()
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        return TranscriptionResult(
            text=text, language_code=body.get("language_code"), latency_ms=latency_ms
        )

    def synthesize(self, text: str) -> bytes:
        """
        Synthesizes `text` as spoken audio (MP3 bytes) via ElevenLabs'
        text-to-speech endpoint, using `config.voice_id` (MILO's fixed
        voice, `ISnQja0Ank6t1FE2Wj07` by default -- see `voice/config.py`).
        """
        if self._config is None:
            raise VoiceUnavailableError()
        text = text.strip()
        if not text:
            raise EmptyTextError()
        api_key = self._resolve_api_key()

        response = _post_with_retries(
            url=f"{_BASE_URL}/text-to-speech/{self._config.voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            timeout_seconds=self._config.timeout_seconds,
            max_retries=self._config.max_retries,
            redact_secret=api_key,
            json={
                "text": text,
                "model_id": _TTS_MODEL_ID,
                "output_format": self._config.output_format,
            },
        )
        if not response.ok:
            detail = _safe_error_detail(response.text, api_key)
            raise SynthesisFailedError(
                f"ElevenLabs text-to-speech returned {response.status_code}: {detail}"
            )
        return response.content
