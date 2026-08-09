"""
test_memory_config.py

Purpose
-------
Unit tests for `memory.config.MemoryConfig.from_env()` -- defaults and
environment-variable overrides, matching `test_language_config.py`'s
pattern for `LLMRuntimeConfig.from_env()`.
"""

from __future__ import annotations

from pathlib import Path

from memory.config import MemoryConfig


def test_from_env_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("MEMORY_ENABLED", raising=False)
    monkeypatch.delenv("MEMORY_DATABASE_PATH", raising=False)
    monkeypatch.delenv("MEMORY_VECTOR_STORE_PATH", raising=False)

    config = MemoryConfig.from_env()

    assert config.enabled is True
    assert config.database_path.name == "memory.db"
    assert config.database_path.parent.name == "memory"
    assert config.vector_store_path.name == "vector_store"


def test_from_env_reads_overrides(monkeypatch, tmp_path):
    db_path = tmp_path / "custom.db"
    vector_path = tmp_path / "custom_vectors"
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    monkeypatch.setenv("MEMORY_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_VECTOR_STORE_PATH", str(vector_path))

    config = MemoryConfig.from_env()

    assert config.enabled is False
    assert config.database_path == db_path
    assert config.vector_store_path == vector_path


def test_memory_config_is_frozen():
    config = MemoryConfig(
        enabled=True,
        database_path=Path("a.db"),
        vector_store_path=Path("vectors"),
    )
    try:
        config.enabled = False
        raised = False
    except Exception:
        raised = True
    assert raised
