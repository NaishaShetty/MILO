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


def test_simulator_is_stopped_when_startup_wiring_fails_after_start(monkeypatch):
    # Regression test: if `build_vision_system` (or anything after
    # `Simulator.start()`) raised, the startup `except` used to just
    # null out `app.state.simulator` -- leaking the already-running
    # Unity subprocess.
    _FakeSimulator.instances = 0
    created = []

    class _Tracked(_FakeSimulator):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            created.append(self)

    def _boom(simulator, depth_source):
        raise RuntimeError("model weights missing")

    monkeypatch.setattr(app_module, "Simulator", _Tracked)
    monkeypatch.setattr(app_module, "build_vision_system", _boom)
    monkeypatch.setenv("VISION_ENABLE_SIMULATOR", "true")
    monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with TestClient(app_module.app) as client:
        assert client.app.state.simulator is None
        assert client.app.state.vision_system is None
        # Already stopped during startup -- not left running.
        assert created[0].started is True
        assert created[0].stop_calls >= 1

    assert all(sim.stop_calls >= 1 for sim in created)


def test_simulator_is_stopped_even_if_stop_raises_during_teardown(monkeypatch):
    class _BadStop(_FakeSimulator):
        def stop(self):
            super().stop()
            raise RuntimeError("unity already gone")

    monkeypatch.setattr(app_module, "Simulator", _BadStop)
    monkeypatch.setattr(
        app_module, "build_vision_system", lambda simulator, depth_source: None
    )
    monkeypatch.setenv("VISION_ENABLE_SIMULATOR", "true")
    monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with TestClient(app_module.app) as client:
        simulator = client.app.state.simulator
    assert simulator.stop_calls == 1
    assert client.app.state.simulator is None
