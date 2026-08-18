"""
test_api_tasks.py

Purpose
-------
Verifies the Phase 7 Task API (`api/routes/tasks.py`) behaves as a
thin HTTP wrapper around `LanguageAgent` + `orchestration.orchestrator.
Orchestrator`: request validation, the 409/503/404/422 error-mapping
table, that `POST /tasks` backgrounds the run (202, poll for
completion -- see that route's docstring for why), `/plan`, `/memory`,
and `/cancel`. Mirrors `test_api_execution.py`/`test_api_language.py`'s
existing "`app.dependency_overrides`, never a real LanguageAgent/
simulator" discipline -- no LLM call, no AI2-THOR.
"""

from __future__ import annotations

import threading
import time
from typing import Iterator, Union
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.app import app
from api.routes.tasks import (
    _store,
    build_orchestrator,
    get_language_agent,
    get_simulator,
)
from schemas.task import MultiTask, SingleTask
from tests._execution_test_helpers import FakeSimulator


@pytest.fixture(autouse=True)
def _clear_overrides_and_store():
    yield
    app.dependency_overrides.clear()
    _store._states.clear()
    _store._active_task_id = None


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _wire(
    fake_sim, parsed_task: Union[SingleTask, MultiTask], *, memory_agent=None
) -> None:
    # `fake_sim` is deliberately unannotated: it is a `FakeSimulator`
    # (test double), not a `simulator.simulator.Simulator`, and
    # `build_orchestrator`'s parameter is typed against the real class
    # -- same "leave the fake's parameter unannotated so mypy skips
    # this function's body" convention `test_api_execution.py::
    # _override_simulator` already establishes for the identical
    # situation.
    build_orchestrator(fake_sim, memory_agent=memory_agent)
    app.dependency_overrides[get_simulator] = lambda: fake_sim
    fake_language_agent = MagicMock()
    fake_language_agent.parse.return_value = parsed_task
    app.dependency_overrides[get_language_agent] = lambda: fake_language_agent


def _memory_agent(tmp_path):
    from agents.memory_agent import MemoryAgentWrapper
    from memory.agent import MemoryAgent
    from memory.config import MemoryConfig

    config = MemoryConfig(
        enabled=True,
        database_path=tmp_path / "memory.db",
        vector_store_path=tmp_path / "vector_store",
    )
    return MemoryAgentWrapper(MemoryAgent.from_config(config))


def _mug_table_scene():
    return [
        {
            "objectId": "Mug|1",
            "objectType": "Mug",
            "distance": 1.0,
            "isOpen": None,
            "parentReceptacle": "Table|1",
        },
        {"objectId": "Table|1", "objectType": "Table", "distance": 2.0, "isOpen": None},
    ]


def _fridge_scene():
    return [
        {
            "objectId": "Fridge|1",
            "objectType": "Fridge",
            "distance": 1.0,
            "isOpen": False,
        }
    ]


def _wait_for_terminal_status(client: TestClient, task_id: str, timeout_s: float = 5.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = client.get(f"/api/v1/tasks/{task_id}")
        body = response.json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not finish within {timeout_s}s")


def test_create_task_runs_to_completion_and_is_retrievable(client: TestClient) -> None:
    _wire(
        FakeSimulator(objects=_mug_table_scene()),
        SingleTask(goal="find", object="mug"),
    )

    response = client.post("/api/v1/tasks", json={"instruction": "find the mug"})

    assert response.status_code == 202
    body = response.json()
    task_id = body["task_id"]
    assert body["goal"] == "find"

    final = _wait_for_terminal_status(client, task_id)
    assert final["status"] == "succeeded"

    get_response = client.get(f"/api/v1/tasks/{task_id}")
    assert get_response.status_code == 200
    assert get_response.json()["task_id"] == task_id

    state_response = client.get(f"/api/v1/tasks/{task_id}/state")
    assert state_response.json() == get_response.json()

    events_response = client.get(f"/api/v1/tasks/{task_id}/events")
    assert events_response.status_code == 200
    event_names = [e["event"] for e in events_response.json()]
    assert "TASK_CREATED" in event_names
    assert "TASK_COMPLETED" in event_names


def test_list_tasks_returns_empty_list_when_none_have_run(client: TestClient) -> None:
    response = client.get("/api/v1/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_list_tasks_returns_newest_first_and_matches_get_shape(
    client: TestClient,
) -> None:
    _wire(
        FakeSimulator(objects=_mug_table_scene()),
        SingleTask(goal="find", object="mug"),
    )
    first = client.post("/api/v1/tasks", json={"instruction": "find the mug"})
    first_id = first.json()["task_id"]
    _wait_for_terminal_status(client, first_id)

    _wire(
        FakeSimulator(objects=_fridge_scene()),
        SingleTask(goal="find", object="fridge"),
    )
    second = client.post("/api/v1/tasks", json={"instruction": "find the fridge"})
    second_id = second.json()["task_id"]
    _wait_for_terminal_status(client, second_id)

    list_response = client.get("/api/v1/tasks")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert [task["task_id"] for task in listed] == [second_id, first_id]

    get_response = client.get(f"/api/v1/tasks/{second_id}")
    assert listed[0] == get_response.json()


def test_create_task_rejects_whitespace_only_instruction(client: TestClient) -> None:
    # Wired with a simulator so this exercises body validation itself,
    # not the (also-422-free) 503 "no simulator" path -- see
    # `get_simulator`'s docstring: a missing simulator is checked as a
    # dependency and can otherwise short-circuit before body validation.
    _wire(
        FakeSimulator(objects=_mug_table_scene()), SingleTask(goal="find", object="mug")
    )
    response = client.post("/api/v1/tasks", json={"instruction": "   "})
    assert response.status_code == 422


def test_create_task_without_simulator_returns_503(client: TestClient) -> None:
    fake_language_agent = MagicMock()
    fake_language_agent.parse.return_value = SingleTask(goal="find", object="mug")
    app.dependency_overrides[get_language_agent] = lambda: fake_language_agent

    response = client.post("/api/v1/tasks", json={"instruction": "find the mug"})

    assert response.status_code == 503
    assert response.json()["category"] == "execution_unavailable"


def test_create_task_rejects_multi_task_instructions(client: TestClient) -> None:
    multi_task = MultiTask(
        subtasks=[
            SingleTask(goal="find", object="mug"),
            SingleTask(goal="find", object="cup"),
        ]
    )
    _wire(FakeSimulator(objects=_mug_table_scene()), multi_task)

    response = client.post(
        "/api/v1/tasks", json={"instruction": "find the mug and the cup"}
    )

    assert response.status_code == 422
    assert response.json()["category"] == "multi_task_not_supported"


def test_get_unknown_task_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/tasks/does-not-exist")
    assert response.status_code == 404


def test_get_task_plan_returns_the_current_plan(client: TestClient) -> None:
    _wire(
        FakeSimulator(objects=_mug_table_scene()),
        SingleTask(goal="find", object="mug"),
    )
    response = client.post("/api/v1/tasks", json={"instruction": "find the mug"})
    task_id = response.json()["task_id"]
    _wait_for_terminal_status(client, task_id)

    plan_response = client.get(f"/api/v1/tasks/{task_id}/plan")
    assert plan_response.status_code == 200
    assert plan_response.json()["task_id"] == task_id
    assert len(plan_response.json()["steps"]) > 0


def test_get_task_plan_404s_for_unknown_task(client: TestClient) -> None:
    response = client.get("/api/v1/tasks/does-not-exist/plan")
    assert response.status_code == 404


def test_get_task_memory_reports_created_memory(client: TestClient, tmp_path) -> None:
    _wire(
        FakeSimulator(objects=_mug_table_scene()),
        SingleTask(goal="find", object="mug"),
        memory_agent=_memory_agent(tmp_path),
    )
    response = client.post("/api/v1/tasks", json={"instruction": "find the mug"})
    task_id = response.json()["task_id"]
    _wait_for_terminal_status(client, task_id)

    memory_response = client.get(f"/api/v1/tasks/{task_id}/memory")
    assert memory_response.status_code == 200
    body = memory_response.json()
    assert "retrieved" in body and "created" in body
    assert len(body["created"]) == 1


def test_get_task_robot_state_reflects_current_simulator_metadata(
    client: TestClient,
) -> None:
    fake_sim = FakeSimulator(objects=_mug_table_scene())
    _wire(fake_sim, SingleTask(goal="find", object="mug"))
    response = client.post("/api/v1/tasks", json={"instruction": "find the mug"})
    task_id = response.json()["task_id"]
    _wait_for_terminal_status(client, task_id)

    robot_response = client.get(f"/api/v1/tasks/{task_id}/robot")
    assert robot_response.status_code == 200
    body = robot_response.json()
    assert body["position"] == {"x": 0, "y": 0, "z": 0}
    assert body["held_object"] is None
    assert body["visible_objects"] == []


def test_get_task_robot_state_reports_held_object(client: TestClient) -> None:
    fake_sim = FakeSimulator(objects=_mug_table_scene())
    _wire(fake_sim, SingleTask(goal="find", object="mug"))
    response = client.post("/api/v1/tasks", json={"instruction": "find the mug"})
    task_id = response.json()["task_id"]
    _wait_for_terminal_status(client, task_id)

    fake_sim.objects[0]["isPickedUp"] = True
    robot_response = client.get(f"/api/v1/tasks/{task_id}/robot")
    body = robot_response.json()
    assert body["held_object"] == {"object_id": "Mug|1", "object_type": "Mug"}


def test_get_task_robot_state_without_simulator_returns_503(
    client: TestClient,
) -> None:
    fake_sim = FakeSimulator(objects=_mug_table_scene())
    _wire(fake_sim, SingleTask(goal="find", object="mug"))
    response = client.post("/api/v1/tasks", json={"instruction": "find the mug"})
    task_id = response.json()["task_id"]
    _wait_for_terminal_status(client, task_id)

    app.dependency_overrides[get_simulator] = lambda: (_ for _ in ()).throw(
        HTTPException(
            status_code=503,
            detail={"category": "execution_unavailable", "message": "no sim"},
        )
    )
    robot_response = client.get(f"/api/v1/tasks/{task_id}/robot")
    assert robot_response.status_code == 503


def test_get_task_robot_state_404s_for_unknown_task(client: TestClient) -> None:
    # Simulator must be wired for the dependency itself to resolve before
    # the route body's 404 check ever runs -- same ordering as every
    # other simulator-backed route in this module.
    _wire(
        FakeSimulator(objects=_mug_table_scene()), SingleTask(goal="find", object="mug")
    )
    response = client.get("/api/v1/tasks/does-not-exist/robot")
    assert response.status_code == 404


def test_second_create_task_while_one_is_running_returns_409(
    client: TestClient,
) -> None:
    gate = threading.Event()

    def _block_until_released() -> None:
        gate.wait(timeout=5.0)

    sim = FakeSimulator(
        objects=_fridge_scene(), hooks={"navigate": _block_until_released}
    )
    _wire(sim, SingleTask(goal="find", object="fridge"))

    first = client.post("/api/v1/tasks", json={"instruction": "find the fridge"})
    assert first.status_code == 202
    task_id = first.json()["task_id"]

    time.sleep(0.05)  # let the background thread reach the blocking hook
    second = client.post("/api/v1/tasks", json={"instruction": "find the fridge"})
    assert second.status_code == 409
    assert second.json()["category"] == "task_in_progress"

    gate.set()
    _wait_for_terminal_status(client, task_id)


def test_cancel_running_task_ends_it_cancelled_with_no_memory_written(
    client: TestClient,
) -> None:
    gate = threading.Event()

    def _block_until_released() -> None:
        gate.wait(timeout=5.0)

    sim = FakeSimulator(
        objects=_fridge_scene(), hooks={"navigate": _block_until_released}
    )
    _wire(sim, SingleTask(goal="find", object="fridge"))

    start_response = client.post(
        "/api/v1/tasks", json={"instruction": "find the fridge"}
    )
    task_id = start_response.json()["task_id"]

    time.sleep(0.05)  # let the background thread reach the blocking hook
    cancel_response = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancel_response.status_code == 200
    gate.set()

    final = _wait_for_terminal_status(client, task_id)
    assert final["status"] == "cancelled"
    assert final["created_memories"] == []

    events_response = client.get(f"/api/v1/tasks/{task_id}/events")
    event_names = [e["event"] for e in events_response.json()]
    assert "TASK_CANCELLED" in event_names
    assert "TASK_COMPLETED" not in event_names
    assert "TASK_FAILED" not in event_names


def test_cancel_unknown_task_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/tasks/does-not-exist/cancel")
    assert response.status_code == 404


def test_cancel_already_finished_task_is_a_safe_no_op(client: TestClient) -> None:
    _wire(
        FakeSimulator(objects=_mug_table_scene()),
        SingleTask(goal="find", object="mug"),
    )
    response = client.post("/api/v1/tasks", json={"instruction": "find the mug"})
    task_id = response.json()["task_id"]
    _wait_for_terminal_status(client, task_id)

    cancel_response = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "succeeded"
