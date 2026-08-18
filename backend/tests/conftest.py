"""
conftest.py (backend/tests)

Purpose
-------
Forces `VISION_ENABLE_SIMULATOR=false` for every test under this
directory, regardless of what a local `.env` sets it to for
interactive/dev use. `api.app`'s `load_dotenv()` call only fills gaps
in `os.environ` (never overrides an already-set value), so setting it
here -- at conftest import time, before any test module in this
directory is collected and therefore before any `TestClient`'s
lifespan can read it -- reliably wins over `.env`'s
`VISION_ENABLE_SIMULATOR=true`.

Why this matters
-----------------
Without this, running `pytest` from a shell with a local `.env`
present (the normal interactive-dev setup -- see the root README's
Quick Start) wires a REAL AI2-THOR/Unity simulator into every
`TestClient`'s `app.state`, not the "no simulator configured" case
three tests exist specifically to exercise
(`test_api_agents.py::test_list_agents_without_registry_returns_503`,
`test_api_execution.py::test_start_execution_without_simulator_
returns_503`, `test_api_tasks.py::test_create_task_without_simulator_
returns_503`) -- they'd see a working simulator instead of the
`503`/"unavailable" case they assert on, and fail for a reason that
has nothing to do with the code under test. Fixed at the source here
rather than left as a "remember to unset the env var" instruction.

`test_api_app_lifecycle.py`'s own tests are unaffected: they use
`monkeypatch.setenv(...)`, which always wins over whatever this
conftest sets and is automatically reverted per-test by pytest.

Tests that genuinely want a real simulator
(`simulator/test_execution_e2e.py`) live outside this directory and
are unaffected -- they have their own explicit `RUN_SIMULATOR_TESTS=true`
opt-in gate and never depended on `VISION_ENABLE_SIMULATOR` at all.
"""

import os

os.environ["VISION_ENABLE_SIMULATOR"] = "false"
