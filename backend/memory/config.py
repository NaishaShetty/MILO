"""
config.py (backend/memory)

Purpose
-------
Deployment-level configuration for `backend/memory/`, read from the
environment -- mirrors `language/config.py`'s `LLMRuntimeConfig.
from_env()` pattern exactly (frozen dataclass, `from_env()` classmethod,
no hardcoded paths scattered through the rest of this package).
`MemoryManager.from_config()` (`manager.py`) is the intended production
entry point; tests construct `SQLiteMemoryStore`/`MemoryManager`
directly against a `tmp_path` and never call `from_env()`, matching
`LanguageRuntimeConfig.from_env()`'s own "tests should generally not
call this" convention.

Why the database path defaults under `backend/outputs/`
------------------------------------------------------------
`backend/outputs/` is this project's existing, gitignored scratch
directory for generated runtime artifacts (see `backend/outputs/
.gitkeep`) -- reused here rather than inventing a second "where does
this project write local data" location.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: backend/memory/config.py -> parents[1] is backend/ -- mirrors
#: `language/config.py`'s own `.resolve().parent.parent` pattern.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DATABASE_PATH = _BACKEND_DIR / "outputs" / "memory" / "memory.db"
#: Not read from by anything in Phase 6.1 (no concrete `VectorStore`
#: ships yet -- see `store.py`'s docstring) -- declared now so a
#: deployment can already point Phase 6.2's concrete adapter at a
#: stable, documented location without a Phase 6.1 config change.
_DEFAULT_VECTOR_STORE_PATH = _BACKEND_DIR / "outputs" / "memory" / "vector_store"


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class MemoryConfig:
    """
    Everything `MemoryManager.from_config()` needs to construct a
    `SQLiteMemoryStore` (and, once Phase 6.2 adds one, a concrete
    `VectorStore`). Frozen (matches `ModelConfig`/`LLMRuntimeConfig`)
    so a config object handed to a manager cannot be mutated out from
    under it mid-use.
    """

    #: Master enable/disable switch. `MemoryManager.from_config()`
    #: still constructs normally when `False` -- this flag is for a
    #: future caller (e.g. `api/app.py`'s lifespan, once Phase 6
    #: wiring exists) to decide whether to construct a manager at all,
    #: matching `VISION_ENABLE_SIMULATOR`'s opt-in gate precedent.
    #: Nothing in Phase 6.1 reads this flag itself.
    enabled: bool

    #: Path to the SQLite database file `SQLiteMemoryStore` reads/
    #: writes. Parent directories are created on first use if missing.
    database_path: Path

    #: Reserved for a future Phase 6.2 concrete `VectorStore` adapter.
    #: Unused by anything in Phase 6.1.
    vector_store_path: Path

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        """
        Builds this config from environment variables, defaulting to
        this repository's `backend/outputs/memory/` location. See
        `backend/.env.example` for the documented variable names.
        """
        return cls(
            enabled=_parse_bool_env("MEMORY_ENABLED", True),
            database_path=Path(
                os.environ.get("MEMORY_DATABASE_PATH", str(_DEFAULT_DATABASE_PATH))
            ),
            vector_store_path=Path(
                os.environ.get(
                    "MEMORY_VECTOR_STORE_PATH", str(_DEFAULT_VECTOR_STORE_PATH)
                )
            ),
        )
