"""
test_speech_config.py

Purpose
-------
Unit tests for `speech.config.SpeechConfig.from_env()`: defaults,
env-var overrides, and rejecting an invalid model size.
"""

from __future__ import annotations

import pytest

from speech.config import SpeechConfig


def test_defaults_are_disabled_with_base_model_on_cpu(monkeypatch):
    monkeypatch.delenv("SPEECH_ENABLE_WHISPER", raising=False)
    monkeypatch.delenv("WHISPER_MODEL_SIZE", raising=False)
    monkeypatch.delenv("WHISPER_DEVICE", raising=False)

    config = SpeechConfig.from_env()

    assert config.enabled is False
    assert config.model_size == "base"
    assert config.device == "cpu"


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("SPEECH_ENABLE_WHISPER", "true")
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "small")
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")

    config = SpeechConfig.from_env()

    assert config.enabled is True
    assert config.model_size == "small"
    assert config.device == "cuda"


def test_invalid_model_size_raises(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "gigantic")
    with pytest.raises(ValueError):
        SpeechConfig.from_env()


def test_stt_provider_defaults_to_whisper(monkeypatch):
    monkeypatch.delenv("STT_PROVIDER", raising=False)
    config = SpeechConfig.from_env()
    assert config.stt_provider == "whisper"


def test_stt_provider_accepts_elevenlabs(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "elevenlabs")
    config = SpeechConfig.from_env()
    assert config.stt_provider == "elevenlabs"


def test_invalid_stt_provider_raises(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    with pytest.raises(ValueError):
        SpeechConfig.from_env()
