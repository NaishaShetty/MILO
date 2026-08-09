"""
test_api_app_lifecycle.py

Purpose
-------
Regression test for the Phase 4 simulator lifecycle bug: `_lifespan`
(`api/app.py`) used to construct a `Simulator` as a local variable and
never call `.stop()` on shutdown, so under `uvicorn --reload` every
reload launched another, never-stopped AI2-THOR/Unity subprocess. This
verifies the fix -- `app.state.simulator` is set exactly once at
startup and `.stop()` is called exactly once at shutdown -- without
ever launching real Unity: `api.app.Simulator` is monkeypatched with a
fake that just counts starts/stops, and `api.app.build_vision_system`
is monkeypatched to a no-op so the (unrelated, model-loading) vision
pipeline is never touched.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import api.app as app_module


class _FakeSimulator:
    instances = 0

    def __init__(self, **kwargs):
        _FakeSimulator.instances += 1
        self.started = False
        self.stop_calls = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stop_calls += 1


def test_lifespan_starts_exactly_one_simulator_and_stops_it_once(monkeypatch):
    _FakeSimulator.instances = 0
    monkeypatch.setattr(app_module, "Simulator", _FakeSimulator)
    monkeypatch.setattr(
        app_module, "build_vision_system", lambda simulator, depth_source: None
    )
    monkeypatch.setenv("VISION_ENABLE_SIMULATOR", "true")
    monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with TestClient(app_module.app) as client:
        simulator = client.app.state.simulator
        assert simulator is not None
        assert _FakeSimulator.instances == 1
        assert simulator.started is True
        assert simulator.stop_calls == 0

    # After the `with` block exits, TestClient triggers FastAPI shutdown.
    assert simulator.stop_calls == 1
    assert client.app.state.simulator is None


def test_lifespan_leaves_simulator_none_when_disabled(monkeypatch):
    _FakeSimulator.instances = 0
    monkeypatch.setattr(app_module, "Simulator", _FakeSimulator)
    monkeypatch.setenv("VISION_ENABLE_SIMULATOR", "false")
    monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with TestClient(app_module.app) as client:
        assert client.app.state.simulator is None
        assert _FakeSimulator.instances == 0
