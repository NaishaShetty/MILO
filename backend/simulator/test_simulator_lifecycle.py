"""
test_simulator_lifecycle.py

Purpose
-------
Regression tests for the Phase 4 stability bug where repeated
`Simulator.start()` calls (each FastAPI/Uvicorn `--reload` cycle, in
practice) launched a new AI2-THOR/Unity `Controller` without the
previous one ever being stopped, eventually accumulating 10+ Unity
windows and crashing WSL. These tests never construct a real
`ai2thor.controller.Controller` (that would launch Unity, defeating the
point of an automated test) -- `ai2thor_env.Controller` is monkeypatched
with a lightweight fake that just records how many times it was
constructed and stopped.
"""

from __future__ import annotations

import simulator.ai2thor_env as ai2thor_env
from simulator.simulator import Simulator


class _FakeController:
    """Stand-in for `ai2thor.controller.Controller` that never touches
    Unity -- counts constructions/stops so tests can assert on them."""

    instances_created = 0

    def __init__(self, **kwargs):
        _FakeController.instances_created += 1
        self.stopped = False

    def stop(self):
        self.stopped = True


def _patch_controller(monkeypatch):
    _FakeController.instances_created = 0
    monkeypatch.setattr(ai2thor_env, "Controller", _FakeController)


def test_duplicate_start_does_not_create_second_controller(monkeypatch):
    _patch_controller(monkeypatch)
    sim = Simulator()

    sim.start()
    sim.start()

    assert _FakeController.instances_created == 1


def test_stop_clears_controller_reference(monkeypatch):
    _patch_controller(monkeypatch)
    sim = Simulator()

    sim.start()
    sim.stop()

    assert sim.env.controller is None


def test_double_stop_does_not_raise(monkeypatch):
    _patch_controller(monkeypatch)
    sim = Simulator()

    sim.start()
    sim.stop()
    sim.stop()  # must not raise


def test_restart_after_stop_creates_new_controller(monkeypatch):
    _patch_controller(monkeypatch)
    sim = Simulator()

    sim.start()
    first_controller = sim.env.controller
    sim.stop()
    sim.start()

    assert _FakeController.instances_created == 2
    assert sim.env.controller is not None
    assert sim.env.controller is not first_controller
