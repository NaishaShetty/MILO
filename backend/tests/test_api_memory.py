"""
test_api_memory.py

Purpose
-------
Verifies `GET /api/v1/memory/search` and `GET /api/v1/memory` (Phase
8.2) against a real `MemoryAgent`/SQLite store pointed at a temp
directory via `MEMORY_DATABASE_PATH`/`MEMORY_VECTOR_STORE_PATH` --
mirrors `test_memory_agent.py`'s `_config(tmp_path)` fixture pattern,
but exercised through the HTTP layer, matching `test_api_health.py`'s
"real component, temp-path env vars, no mocking" convention.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app
from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from memory.models import MemoryProvenance, MemoryType
from memory.semantics import EpisodicDetails


def _configure_memory_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MEMORY_DATABASE_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("MEMORY_VECTOR_STORE_PATH", str(tmp_path / "vector_store"))
    monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_search_returns_empty_results_when_nothing_stored(
    monkeypatch, tmp_path
) -> None:
    _configure_memory_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/v1/memory/search", params={"q": "mug"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "mug"
    assert body["results"] == []


def test_search_finds_a_real_stored_memory(monkeypatch, tmp_path) -> None:
    _configure_memory_env(monkeypatch, tmp_path)

    agent = MemoryAgent.from_config(
        MemoryConfig(
            enabled=True,
            database_path=tmp_path / "memory.db",
            vector_store_path=tmp_path / "vector_store",
        )
    )
    agent.remember_episode(
        EpisodicDetails(
            task_summary="Saw red mug on dining table",
            outcome="success",
            location="dining table",
        ),
        episode_id="ep-1",
        provenance=MemoryProvenance.OBSERVATION,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/memory/search", params={"q": "red mug"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert "mug" in body["results"][0]["memory"]["content"].lower()


def test_list_memory_reports_real_counts_by_type(monkeypatch, tmp_path) -> None:
    _configure_memory_env(monkeypatch, tmp_path)

    agent = MemoryAgent.from_config(
        MemoryConfig(
            enabled=True,
            database_path=tmp_path / "memory.db",
            vector_store_path=tmp_path / "vector_store",
        )
    )
    agent.remember_episode(
        EpisodicDetails(
            task_summary="Saw apple in kitchen",
            outcome="success",
            location="kitchen",
        ),
        episode_id="ep-2",
        provenance=MemoryProvenance.OBSERVATION,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/memory")

    assert response.status_code == 200
    body = response.json()
    assert body["counts_by_type"][MemoryType.EPISODIC.value] == 1
    assert len(body["memories"]) == 1


def test_list_memory_filters_by_type(monkeypatch, tmp_path) -> None:
    _configure_memory_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/memory", params={"memory_type": MemoryType.FAILURE.value}
        )

    assert response.status_code == 200
    assert response.json()["memories"] == []
