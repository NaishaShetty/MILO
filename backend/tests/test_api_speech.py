"""
test_api_speech.py

Purpose
-------
Verifies `POST /api/v1/speech/transcribe` behaves as a thin HTTP
wrapper around `agents.speech_agent.SpeechAgent` (injected via
`app.dependency_overrides`, never a real Whisper model) -- request
handling, the 503/422/502 error-mapping table, and a successful
transcription's JSON shape. Mirrors `test_api_vision.py`'s existing
discipline.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from agents.speech_agent import SpeechAgent
from api.app import app
from api.routes.speech import get_speech_agent
from speech.whisper_client import WhisperTranscriber


class _FakeModel:
    def __init__(self, text: str = "find the mug") -> None:
        self._text = text

    def transcribe(self, path: str):
        return {"text": self._text, "language": "en"}


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _override(agent: SpeechAgent) -> None:
    app.dependency_overrides[get_speech_agent] = lambda: agent


def test_transcribe_returns_transcript(client: TestClient) -> None:
    _override(SpeechAgent(WhisperTranscriber(model=_FakeModel())))

    response = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("clip.wav", b"fake-audio-bytes", "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "find the mug"
    assert body["language"] == "en"
    assert body["latency_ms"] >= 0.0


def test_transcribe_against_real_default_config_is_unavailable(
    client: TestClient,
) -> None:
    # No override applied -- exercises the real `app.state.speech_agent`
    # built at startup. SPEECH_ENABLE_WHISPER defaults to unset/false
    # (see speech/config.py), so this is deterministically 503
    # regardless of whether `openai-whisper` happens to be installed.
    response = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("clip.wav", b"fake-audio-bytes", "audio/wav")},
    )
    assert response.status_code == 503
    assert response.json()["category"] == "model_unavailable"


def test_transcribe_unavailable_model_returns_503(client: TestClient) -> None:
    _override(SpeechAgent(WhisperTranscriber(model=None)))

    response = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("clip.wav", b"fake-audio-bytes", "audio/wav")},
    )

    assert response.status_code == 503
    assert response.json()["category"] == "model_unavailable"


def test_transcribe_empty_audio_returns_422(client: TestClient) -> None:
    _override(SpeechAgent(WhisperTranscriber(model=_FakeModel())))

    response = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("clip.wav", b"", "audio/wav")},
    )

    assert response.status_code == 422
    assert response.json()["category"] == "empty_audio"


def test_transcribe_unintelligible_audio_returns_422(client: TestClient) -> None:
    _override(SpeechAgent(WhisperTranscriber(model=_FakeModel(text="   "))))

    response = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("clip.wav", b"some-bytes", "audio/wav")},
    )

    assert response.status_code == 422
    assert response.json()["category"] == "unintelligible"
