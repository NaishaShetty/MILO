"""
test_agents_speech_agent.py

Purpose
-------
Unit tests for `agents.speech_agent.SpeechAgent`: delegation to
`speech.whisper_client.WhisperTranscriber`, `AgentState` transitions
on success/failure, and the generic `process()` "transcribe" operation.
"""

from __future__ import annotations

from agents.contracts import AgentRequest, AgentState
from agents.speech_agent import SpeechAgent
from speech.whisper_client import WhisperTranscriber


class _FakeModel:
    def __init__(self, text: str = "find the mug") -> None:
        self._text = text

    def transcribe(self, path: str):
        return {"text": self._text, "language": "en"}


def test_transcribe_delegates_and_resets_state_to_idle():
    agent = SpeechAgent(WhisperTranscriber(model=_FakeModel()))
    assert agent.get_state() == AgentState.IDLE

    result = agent.transcribe(b"some-bytes")

    assert result.text == "find the mug"
    assert agent.get_state() == AgentState.IDLE


def test_transcribe_sets_error_state_on_failure():
    agent = SpeechAgent(WhisperTranscriber(model=None))
    import pytest

    from speech.errors import ModelUnavailableError

    with pytest.raises(ModelUnavailableError):
        agent.transcribe(b"some-bytes")
    assert agent.get_state() == AgentState.ERROR


def test_is_available_reflects_transcriber():
    assert SpeechAgent(WhisperTranscriber(model=None)).is_available() is False
    assert SpeechAgent(WhisperTranscriber(model=_FakeModel())).is_available() is True


def test_process_transcribe_operation_returns_data():
    agent = SpeechAgent(WhisperTranscriber(model=_FakeModel()))
    response = agent.process(
        AgentRequest(operation="transcribe", payload={"audio_hex": b"abc".hex()})
    )
    assert response.success is True
    assert response.data["text"] == "find the mug"


def test_process_unavailable_model_returns_structured_error():
    agent = SpeechAgent(WhisperTranscriber(model=None))
    response = agent.process(
        AgentRequest(operation="transcribe", payload={"audio_hex": b"abc".hex()})
    )
    assert response.success is False
    assert response.error.details["code"] == "MODEL_UNAVAILABLE"


def test_process_requires_audio_hex_payload():
    agent = SpeechAgent(WhisperTranscriber(model=_FakeModel()))
    response = agent.process(AgentRequest(operation="transcribe", payload={}))
    assert response.success is False


def test_process_rejects_unsupported_operation():
    agent = SpeechAgent(WhisperTranscriber(model=_FakeModel()))
    response = agent.process(AgentRequest(operation="listen"))
    assert response.success is False
