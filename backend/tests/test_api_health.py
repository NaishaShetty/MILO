"""
test_api_health.py

Purpose
-------
Verifies `GET /health` reports liveness without ever calling an LLM
provider -- see `api/routes/health.py`'s docstring for why that
distinction matters. Only manipulates environment variables already
owned by `language/config.py`; never mocks `LanguageAgent`, since the
health check never touches it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app


def test_health_reports_ok(monkeypatch) -> None:
    monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_provider_configured"] is True


def test_health_reports_provider_not_configured(monkeypatch) -> None:
    monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["llm_provider_configured"] is False


def test_health_never_exposes_api_key_value(monkeypatch) -> None:
    monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "sk-should-never-appear")

    with TestClient(app) as client:
        response = client.get("/health")

    assert "sk-should-never-appear" not in response.text
