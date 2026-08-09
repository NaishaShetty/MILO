"""
test_api_agents.py

Purpose
-------
Verifies `GET /api/v1/agents` and `GET /api/v1/agents/{name}/status`
read the real `agents.registry.AgentRegistry`
`api/routes/tasks.py::build_orchestrator()` constructs -- 503 when no
registry exists yet, 404 for an unknown agent name, and the actual
registered agent names/states otherwise.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routes.tasks import _store, build_orchestrator
from tests._execution_test_helpers import FakeSimulator


@pytest.fixture(autouse=True)
def _reset_store():
    yield
    _store._orchestrator = None
    _store._states.clear()
    _store._active_task_id = None


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _wire(fake_sim) -> None:
    # `fake_sim` deliberately unannotated -- see `test_api_tasks.py::
    # _wire`'s identical rationale (a `FakeSimulator` test double, not
    # a real `simulator.simulator.Simulator`).
    build_orchestrator(fake_sim)


def test_list_agents_without_registry_returns_503(client: TestClient) -> None:
    response = client.get("/api/v1/agents")
    assert response.status_code == 503
    assert response.json()["category"] == "agents_unavailable"


def test_list_agents_returns_every_registered_agent(client: TestClient) -> None:
    _wire(FakeSimulator(objects=[]))

    response = client.get("/api/v1/agents")

    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert {"planner", "execution", "navigation", "reflection"} <= names
    for row in response.json():
        assert row["state"] in (
            "idle",
            "active",
            "thinking",
            "waiting",
            "error",
            "shutdown",
        )


def test_get_agent_status_returns_one_agent(client: TestClient) -> None:
    _wire(FakeSimulator(objects=[]))

    response = client.get("/api/v1/agents/planner/status")

    assert response.status_code == 200
    assert response.json() == {"name": "planner", "state": "idle"}


def test_get_agent_status_404s_for_unknown_agent(client: TestClient) -> None:
    _wire(FakeSimulator(objects=[]))

    response = client.get("/api/v1/agents/nonexistent/status")

    assert response.status_code == 404
    assert response.json()["category"] == "agent_not_found"
