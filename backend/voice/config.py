"""
config.py (backend/voice)

Purpose
-------
Deployment-level configuration for `backend/voice/`, read from the
environment -- mirrors `speech/config.py`/`language/config.py`'s
`from_env()` pattern exactly (frozen dataclass, no hardcoded values
scattered through the rest of this package).

Why `enabled` defaults to `False`
--------------------------------------
Same rationale as `SPEECH_ENABLE_WHISPER`/`VISION_ENABLE_SIMULATOR`: a
deployment opts in explicitly. Unlike Whisper (a local model download),
ElevenLabs is a paid third-party API -- defaulting to enabled would mean
an API process silently starts making billable network calls the
moment `ELEVENLABS_API_KEY` happens to be set, with no separate
confirmation. `VOICE_ENABLE_ELEVENLABS=true` is the explicit, separate
opt-in.

Why `api_key_env_var` stores a name, not a value
------------------------------------------------------
Matches `language/config.py::LLMRuntimeConfig`'s security policy
exactly (see that module's "Security note"): the config object only
ever carries the *name* of the environment variable holding the key.
The key itself is resolved from `os.environ` at call time, inside
`ElevenLabsClient`, and never stored on `self` or logged -- so a
`VoiceConfig` instance is always safe to log, pass to a test, or
include in a debug dump.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: MILO's fixed ElevenLabs voice -- see the Phase 8.1 audit's
#: `.env.example` placeholder and the Phase 8.2 spec section 17. Not a
#: secret; safe as a literal default (unlike the API key).
DEFAULT_VOICE_ID = "ISnQja0Ank6t1FE2Wj07"

_DEFAULT_API_KEY_ENV_VAR = "ELEVENLABS_API_KEY"


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class VoiceConfig:
    """Everything `ElevenLabsClient.from_config()` needs. See module docstring."""

    #: Master enable/disable switch -- see module docstring.
    enabled: bool

    #: Name of the environment variable holding the ElevenLabs API key
    #: -- resolved at call time by `ElevenLabsClient`, never stored here.
    api_key_env_var: str

    #: MILO's fixed ElevenLabs voice ID -- configurable (not hardcoded
    #: in the client) but defaults to `DEFAULT_VOICE_ID`.
    voice_id: str

    #: TTS output format ElevenLabs should return (its own model id
    #: string, e.g. "mp3_44100_128") -- kept configurable since
    #: ElevenLabs' supported set changes independently of this project.
    output_format: str

    timeout_seconds: float
    max_retries: int

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        return cls(
            enabled=_parse_bool_env("VOICE_ENABLE_ELEVENLABS", False),
            api_key_env_var=os.environ.get(
                "ELEVENLABS_API_KEY_ENV_VAR", _DEFAULT_API_KEY_ENV_VAR
            ),
            voice_id=os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID).strip()
            or DEFAULT_VOICE_ID,
            output_format=os.environ.get(
                "ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128"
            ).strip(),
            timeout_seconds=float(os.environ.get("VOICE_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.environ.get("VOICE_MAX_RETRIES", "2")),
        )
