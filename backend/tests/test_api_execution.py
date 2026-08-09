"""
test_api_execution.py

Purpose
-------
Verifies the Phase 5 Execution API (`api/routes/execution.py`) behaves
as a thin HTTP wrapper around `execution.controller.ExecutionController`:
request validation, delegation, the 503/404/409/422 error-mapping
table, and that a full Planner -> Execution flow (real
`/api/v1/planner/plan` output fed straight into
`/api/v1/execution/start`) actually runs to completion -- section 13's
"a planner-generated plan should be executable without manually
converting it inside the frontend or a developer script." Uses
`app.dependency_overrides[get_simulator]` (mirrors
`test_api_vision.py::_override_vision_system`) with `FakeSimulator`, so
no AI2-THOR/Unity process is ever involved.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routes.execution import _store, get_simulator
from tests._execution_test_helpers import FakeSimulator, apple_and_fridge_scene


def _waiter(gate: threading.Event) -> Callable[[], None]:
    """Wraps `Event.wait()` (returns bool) as a `Callable[[], None]` --
    the shape `FakeSimulator`'s `hooks` expects."""

    def _wait() -> None:
        gate.wait()

    return _wait


_STORE_TASK = {
    "task_type": "single",
    "goal": "store",
    "object": "apple",
    "target": "refrigerator",
}


@pytest.fixture(autouse=True)
def _clear_overrides_and_store():
    yield
    # Best-effort cleanup so a leftover background thread from one test
    # (e.g. the 409 "already in progress" test) can never leak into the
    # next -- cancel anything left running and reset the singleton
    # store's "one execution at a time" guard directly.
    for controller in list(_store._controllers.values()):
        controller.cancel()
    time.sleep(0.05)
    _store._active_execution_id = None
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _override_simulator(fake_simulator) -> None:
    app.dependency_overrides[get_simulator] = lambda: fake_simulator


def _wait_for_terminal_status(
    client: TestClient, execution_id: str, timeout_s: float = 5.0
):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = client.get(f"/api/v1/execution/{execution_id}")
        body = response.json()
        if body["status"] in ("success", "failed", "cancelled"):
            return body
        time.sleep(0.01)
    raise AssertionError(f"execution {execution_id} did not finish within {timeout_s}s")


def _generate_plan(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/planner/plan", json={"task": _STORE_TASK, "planner_type": "rule_based"}
    )
    assert response.status_code == 200
    plan = response.json()["plan"]
    assert plan is not None
    return plan


def test_start_execution_without_simulator_returns_503(client: TestClient):
    plan = _generate_plan(client)
    response = client.post("/api/v1/execution/start", json={"plan": plan})
    assert response.status_code == 503
    assert response.json()["category"] == "execution_unavailable"


def test_full_execution_flow_via_api(client: TestClient):
    _override_simulator(FakeSimulator(apple_and_fridge_scene()))
    plan = _generate_plan(client)

    start_response = client.post("/api/v1/execution/start", json={"plan": plan})
    assert start_response.status_code == 202
    body = start_response.json()
    execution_id = body["execution_id"]
    assert body["plan_id"] == plan["plan_id"]
    # With FakeSimulator, the background thread can finish before this
    # response is even inspected -- any non-terminal-or-success status
    # is fine here; the real assertions are on the terminal state below.
    assert body["status"] in ("pending", "running", "success")

    final = _wait_for_terminal_status(client, execution_id)
    assert final["status"] == "success"
    assert len(final["step_results"]) == len(plan["steps"])
    assert all(s["status"] == "completed" for s in final["step_results"])

    steps_response = client.get(f"/api/v1/execution/{execution_id}/steps")
    assert steps_response.status_code == 200
    assert len(steps_response.json()) == len(plan["steps"])

    events_response = client.get(f"/api/v1/execution/{execution_id}/events")
    assert events_response.status_code == 200
    assert len(events_response.json()) > 0


def test_get_unknown_execution_returns_404(client: TestClient):
    response = client.get("/api/v1/execution/does-not-exist")
    assert response.status_code == 404
    assert response.json()["category"] == "execution_not_found"


def test_cancel_unknown_execution_returns_404(client: TestClient):
    response = client.post("/api/v1/execution/does-not-exist/cancel")
    assert response.status_code == 404


def test_start_rejects_plan_with_no_steps(client: TestClient):
    _override_simulator(FakeSimulator(apple_and_fridge_scene()))
    plan = _generate_plan(client)
    plan["steps"] = []

    response = client.post("/api/v1/execution/start", json={"plan": plan})
    assert response.status_code == 422
    assert response.json()["category"] == "plan_not_executable"


def test_second_start_while_one_is_running_returns_409(client: TestClient):
    gate = threading.Event()
    # Block the very first dispatched action (locate has no simulator
    # call, so the first real dispatch is "navigate") until the test
    # releases it, keeping this execution RUNNING long enough to prove
    # a concurrent second start is rejected.
    simulator = FakeSimulator(
        apple_and_fridge_scene(), hooks={"navigate": _waiter(gate)}
    )
    _override_simulator(simulator)
    plan = _generate_plan(client)

    first = client.post("/api/v1/execution/start", json={"plan": plan})
    assert first.status_code == 202
    first_id = first.json()["execution_id"]

    # Give the background thread a moment to actually reach the
    # blocking hook before asserting the guard is active.
    time.sleep(0.05)
    second = client.post("/api/v1/execution/start", json={"plan": plan})
    assert second.status_code == 409
    assert second.json()["category"] == "execution_in_progress"

    gate.set()
    _wait_for_terminal_status(client, first_id)


def test_cancel_running_execution_stops_remaining_steps(client: TestClient):
    gate = threading.Event()
    simulator = FakeSimulator(
        apple_and_fridge_scene(), hooks={"navigate": _waiter(gate)}
    )
    _override_simulator(simulator)
    plan = _generate_plan(client)

    start_response = client.post("/api/v1/execution/start", json={"plan": plan})
    execution_id = start_response.json()["execution_id"]

    time.sleep(0.05)
    cancel_response = client.post(f"/api/v1/execution/{execution_id}/cancel")
    assert cancel_response.status_code == 200

    gate.set()
    final = _wait_for_terminal_status(client, execution_id)
    assert final["status"] == "cancelled"
    statuses = {s["status"] for s in final["step_results"]}
    assert "cancelled" in statuses
