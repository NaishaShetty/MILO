"""
test_api_tasks_interpreter.py

`POST /api/v1/tasks` now understands natural phrasing itself and answers
in the right *shape*: a running task (202), a spoken answer for plain
questions, a remembered preference, or a clear question/reason when it
can't act. Plus `GET /api/v1/tasks/library`. Fake simulator, no LLM.
"""

from __future__ import annotations

import time
from typing import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routes.tasks import (
    _store,
    build_orchestrator,
    get_language_agent,
    get_simulator,
)
from language.exceptions import LanguageRuntimeError
from tests._execution_test_helpers import FakeSimulator
from tests.test_task_scenarios import kitchen, memory


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.clear()
    _store._states.clear()
    _store._active_task_id = None


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _wire(sim=None, mem=None, language_agent=None):
    sim = sim or FakeSimulator(objects=kitchen())
    build_orchestrator(sim, memory_agent=mem)
    app.dependency_overrides[get_simulator] = lambda: sim
    agent = language_agent or MagicMock()
    app.dependency_overrides[get_language_agent] = lambda: agent
    return sim, agent


def _wait(client, task_id, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/api/v1/tasks/{task_id}").json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        time.sleep(0.01)
    raise AssertionError("task did not finish")


def test_natural_phrasing_runs_a_task_without_the_language_model(client):
    sim, agent = _wire()
    response = client.post(
        "/api/v1/tasks", json={"instruction": "could you grab me the mug?"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "task" and body["understood_as"] == "Fetch the mug"
    assert body["goal"] == "fetch"
    assert _wait(client, body["task_id"])["status"] == "succeeded"
    agent.parse.assert_not_called()


def test_a_plain_question_is_answered_without_acting(client):
    sim, _ = _wire()
    response = client.post("/api/v1/tasks", json={"instruction": "is the fridge open?"})

    assert response.status_code == 200
    assert response.json() == {
        "kind": "answer",
        "answer": "No, the fridge is closed.",
        "understood_as": "Is the fridge open?",
    }
    assert sim.calls == [] and _store.list_all() == []


def test_where_is_it_question(client):
    _wire()
    body = client.post(
        "/api/v1/tasks", json={"instruction": "where is the mug?"}
    ).json()
    assert body["answer"] == "The mug is on the table."


def test_an_ambiguous_request_comes_back_as_a_question(client):
    _wire()
    body = client.post("/api/v1/tasks", json={"instruction": "clear the table"}).json()
    assert body["kind"] == "clarify"
    assert body["message"] == "Where should I put the things from the table?"


def test_an_impossible_request_comes_back_with_a_reason(client):
    _, agent = _wire()
    agent.parse.side_effect = LanguageRuntimeError("model offline")
    response = client.post("/api/v1/tasks", json={"instruction": "fly to the moon"})

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "unsupported"
    assert "I don't know how to" in body["message"] and "I can" in body["message"]


def test_unrecognised_phrasing_is_handed_to_the_language_model(client):
    from schemas.task import SingleTask

    _, agent = _wire()
    agent.parse.return_value = SingleTask(goal="find", object="mug")
    response = client.post(
        "/api/v1/tasks", json={"instruction": "Hunt down my favourite mug"}
    )

    assert response.status_code == 202
    agent.parse.assert_called_once()


def test_telling_milo_a_preference_remembers_it(client, tmp_path):
    mem = memory(tmp_path)
    _wire(mem=mem)
    # `routes/tasks.py` reads the raw MemoryAgent off app.state.
    app.state.memory_agent = mem._memory_agent
    try:
        response = client.post(
            "/api/v1/tasks", json={"instruction": "the mug goes on the shelf"}
        )
        body = response.json()
        assert body["kind"] == "remembered"
        assert "I'll remember" in body["message"]
        assert mem.usual_places()["mug"] == ("shelf", "located_on")

        # ...and "put it away" now knows where.
        run = client.post("/api/v1/tasks", json={"instruction": "put the mug away"})
        assert run.status_code == 202 and run.json()["goal"] == "place"
    finally:
        del app.state.memory_agent


def test_a_clear_the_table_request_runs_as_one_multi_object_task(client):
    sim, _ = _wire()
    body = client.post(
        "/api/v1/tasks", json={"instruction": "clear the table onto the counter"}
    ).json()
    final = _wait(client, body["task_id"])

    assert final["status"] == "succeeded"
    assert len(final["sub_goals"]) == 3
    assert final["goal"] == "clear_table"


def test_the_task_library_lists_everything_milo_can_do(client):
    response = client.get("/api/v1/tasks/library")
    assert response.status_code == 200
    ids = [entry["id"] for entry in response.json()]
    assert ids[:2] == ["fetch", "deliver"] and "tidy_up" in ids
    assert all(entry["examples"] for entry in response.json())
