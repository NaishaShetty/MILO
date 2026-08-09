"""
config.py (backend/speech)

Purpose
-------
Deployment-level configuration for `backend/speech/`, read from the
environment -- mirrors `memory/config.py`/`language/config.py`'s
`from_env()` pattern (frozen dataclass, no hardcoded values scattered
through the rest of this package).

Why `enabled` defaults to `False`
--------------------------------------
Same rationale as `VISION_ENABLE_SIMULATOR` in `api/app.py`: loading a
Whisper model is a heavyweight operation (downloads/loads a
multi-hundred-MB-to-GB model on first use) that should never happen
implicitly just because the API process started. A deployment that
wants speech opts in explicitly via `SPEECH_ENABLE_WHISPER=true`;
everything else in this package still constructs and imports cleanly
without it (see `whisper_client.py`'s lazy import of the `whisper`
package itself).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Every model size the `openai-whisper` package ships -- validated at
#: config-read time (a typo here should fail loudly at startup, not
#: three calls deep inside a transcription attempt).
_VALID_MODEL_SIZES = ("tiny", "base", "small", "medium", "large")


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class SpeechConfig:
    """Everything `WhisperTranscriber.from_config()` needs. See module docstring."""

    #: Master enable/disable switch -- see module docstring.
    enabled: bool

    #: Whisper model size, e.g. "base", "small". Defaults to "base" --
    #: the project's own reasonable speed/accuracy tradeoff for a
    #: development machine without a dedicated GPU.
    model_size: str

    #: "cpu" or "cuda" -- passed straight through to `whisper.load_model()`.
    device: str

    @classmethod
    def from_env(cls) -> "SpeechConfig":
        model_size = os.environ.get("WHISPER_MODEL_SIZE", "base").strip().lower()
        if model_size not in _VALID_MODEL_SIZES:
            valid = ", ".join(_VALID_MODEL_SIZES)
            raise ValueError(
                f"WHISPER_MODEL_SIZE={model_size!r} is not one of: {valid}."
            )
        return cls(
            enabled=_parse_bool_env("SPEECH_ENABLE_WHISPER", False),
            model_size=model_size,
            device=os.environ.get("WHISPER_DEVICE", "cpu").strip().lower(),
        )
