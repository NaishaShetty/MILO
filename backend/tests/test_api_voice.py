"""
test_api_voice.py

Purpose
-------
Verifies `POST /api/v1/voice/transcribe` and `POST /api/v1/voice/speak`
(Phase 8.2). Never makes a real network call to ElevenLabs (no test
should depend on network access or a real API key) -- unavailable-state
tests rely on the default `VOICE_ENABLE_ELEVENLABS=false`; behavior
once "available" is tested via `app.dependency_overrides`, the same
pattern `test_api_vision.py` uses for `get_vision_system`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agents.voice_agent import VoiceAgent
from api.app import app
from api.routes.voice import get_voice_agent
from voice.elevenlabs_client import TranscriptionResult
from voice.errors import EmptyTextError, SynthesisFailedError


class _FakeClient:
    """Matches `ElevenLabsClient`'s public surface without any network access."""

    def __init__(self, *, transcription=None, audio=b"", raise_on_speak=False):
        self._transcription = transcription
        self._audio = audio
        self._raise_on_speak = raise_on_speak

    def is_available(self) -> bool:
        return True

    def transcribe(self, audio_bytes: bytes):
        assert self._transcription is not None, "test must supply a transcription"
        return self._transcription

    def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise EmptyTextError()
        if self._raise_on_speak:
            raise SynthesisFailedError("boom")
        return self._audio


def test_transcribe_reports_503_when_voice_disabled(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_ENABLE_ELEVENLABS", raising=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/voice/transcribe", files={"file": ("a.wav", b"123", "audio/wav")}
        )

    assert response.status_code == 503
    assert response.json()["category"] == "voice_unavailable"


def test_speak_reports_503_when_voice_disabled(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_ENABLE_ELEVENLABS", raising=False)

    with TestClient(app) as client:
        response = client.post("/api/v1/voice/speak", json={"text": "hi"})

    assert response.status_code == 503


def test_speak_with_text_returns_real_audio_bytes_from_the_agent() -> None:
    fake_agent = VoiceAgent(_FakeClient(audio=b"fake-mp3-bytes"))  # type: ignore[arg-type]
    app.dependency_overrides[get_voice_agent] = lambda: fake_agent
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/voice/speak", json={"text": "Hello!"})
        assert response.status_code == 200
        assert response.content == b"fake-mp3-bytes"
        assert response.headers["content-type"] == "audio/mpeg"
    finally:
        app.dependency_overrides.pop(get_voice_agent, None)


def test_speak_requires_exactly_one_of_task_id_or_text() -> None:
    fake_agent = VoiceAgent(_FakeClient())  # type: ignore[arg-type]
    app.dependency_overrides[get_voice_agent] = lambda: fake_agent
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/voice/speak", json={"task_id": "t-1", "text": "hi"}
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_voice_agent, None)


def test_speak_with_unknown_task_id_returns_404() -> None:
    fake_agent = VoiceAgent(_FakeClient())  # type: ignore[arg-type]
    app.dependency_overrides[get_voice_agent] = lambda: fake_agent
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/voice/speak", json={"task_id": "no-such-task"}
            )
        assert response.status_code == 404
        assert response.json()["category"] == "task_not_found"
    finally:
        app.dependency_overrides.pop(get_voice_agent, None)


def test_speak_maps_synthesis_failure_to_502() -> None:
    fake_agent = VoiceAgent(_FakeClient(raise_on_speak=True))  # type: ignore[arg-type]
    app.dependency_overrides[get_voice_agent] = lambda: fake_agent
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/voice/speak", json={"text": "hi"})
        assert response.status_code == 502
        assert response.json()["category"] == "synthesis_failed"
    finally:
        app.dependency_overrides.pop(get_voice_agent, None)


def test_transcribe_returns_real_transcription_from_the_agent() -> None:
    transcription = TranscriptionResult(
        text="bring me the mug", language_code="en", latency_ms=12.5
    )
    fake_agent = VoiceAgent(_FakeClient(transcription=transcription))  # type: ignore[arg-type]
    app.dependency_overrides[get_voice_agent] = lambda: fake_agent
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/voice/transcribe",
                files={"file": ("a.wav", b"real-audio-bytes", "audio/wav")},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["text"] == "bring me the mug"
        assert body["language_code"] == "en"
    finally:
        app.dependency_overrides.pop(get_voice_agent, None)
