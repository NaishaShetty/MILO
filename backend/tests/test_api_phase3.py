"""
test_api_phase3.py

API hardening and task control:

- choosing a planner per task, validated and reported on the task;
- live cancel: stops between steps, leaves a clean state, visible on the
  task immediately;
- server-sent events for one task / all tasks (no polling needed);
- the optional API key and rate limit, the audio-upload cap, and error
  messages written to be shown as-is;
- a plain-language `explanation` on each step and MILO's running
  "thoughts", built from reflection verdicts;
- "forget this" for memories.

FakeSimulator + dependency overrides; no LLM, no AI2-THOR.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Iterator, List, Tuple
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agents.speech_agent import SpeechAgent
from api.app import app
from api.routes.memory import get_memory_agent
from api.routes.speech import get_speech_agent
from api.routes.tasks import (
    _store,
    build_orchestrator,
    get_language_agent,
    get_simulator,
)
from api.security import limiter
from speech.whisper_client import WhisperTranscriber
from tests._execution_test_helpers import FakeSimulator
from tests.test_task_scenarios import kitchen, memory


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("API_KEY", "RATE_LIMIT_PER_MINUTE", "SPEECH_MAX_UPLOAD_BYTES"):
        monkeypatch.delenv(name, raising=False)
    limiter.reset()
    yield
    app.dependency_overrides.clear()
    _store._states.clear()
    _store._active_task_id = None
    limiter.reset()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _wire(sim=None, mem=None):
    sim = sim or FakeSimulator(objects=kitchen())
    build_orchestrator(sim, memory_agent=mem)
    app.dependency_overrides[get_simulator] = lambda: sim
    app.dependency_overrides[get_language_agent] = lambda: MagicMock()
    return sim


def _wait(client, task_id, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/api/v1/tasks/{task_id}").json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        time.sleep(0.01)
    raise AssertionError("task did not finish")


def _post(client, text, **extra):
    return client.post("/api/v1/tasks", json={"instruction": text, **extra})


# -- planner choice ---------------------------------------------------------


@pytest.mark.parametrize("planner", ["rule_based", "react", "behavior_tree", "htn"])
def test_each_planner_can_be_chosen_and_is_reported(client, planner):
    _wire()
    response = _post(client, "put the apple in the fridge", planner=planner)

    assert response.status_code == 202
    assert response.json()["planner"] == planner
    final = _wait(client, response.json()["task_id"])
    assert final["status"] == "succeeded", final["failures"]
    assert final["planner"] == planner


def test_the_default_planner_is_rule_based(client):
    _wire()
    body = _post(client, "find the mug").json()
    assert body["planner"] == "rule_based"


def test_an_unknown_planner_is_rejected_with_a_helpful_message(client):
    _wire()
    response = _post(client, "find the mug", planner="magic")

    assert response.status_code == 422
    body = response.json()
    assert body["category"] == "invalid_request"
    assert body["message"] == (
        "I don't know that planner. Choose one of: rule_based, react, "
        "behavior_tree, htn."
    )


def test_react_without_a_language_model_says_it_fell_back(client):
    _wire()
    body = _post(client, "find the mug", planner="react").json()
    final = _wait(client, body["task_id"])

    assert final["planner"] == "react"
    assert "rule-based planner made this plan" in final["planner_note"]


def test_a_goal_no_planner_can_execute_fails_with_a_plain_reason(client):
    sim = _wire(
        FakeSimulator(
            objects=kitchen()
            + [{"objectId": "Window|1", "objectType": "Window", "distance": 4.0}]
        )
    )
    # "clean" is not something the interpreter knows; the model parses it.
    from schemas.task import SingleTask

    agent = MagicMock()
    agent.parse.return_value = SingleTask(goal="clean", object="window")
    app.dependency_overrides[get_language_agent] = lambda: agent
    body = _post(client, "Wipe down the window", planner="htn").json()
    final = _wait(client, body["task_id"])

    # Neither HTN nor its rule-based fallback has a real action for "clean":
    # the plan is refused before anything runs, instead of "succeeding".
    assert final["status"] == "failed"
    assert "I don't have a way to do 'clean' yet" in str(final)
    del sim


# -- live cancel ------------------------------------------------------------


def test_cancel_stops_the_task_and_leaves_a_clean_state(client):
    reached = threading.Event()
    release = threading.Event()
    navigations: List[str] = []

    def block_on_the_way_back() -> None:
        navigations.append("n")
        if len(navigations) == 2:  # second walk: back to the user, mug in hand
            reached.set()
            release.wait(5)

    sim = FakeSimulator(objects=kitchen(), hooks={"navigate": block_on_the_way_back})
    _wire(sim)
    body = _post(client, "bring me the mug").json()
    assert reached.wait(5), "the task never reached the blocking step"
    assert [i["objectType"] for i in sim.inventory_objects] == ["Mug"]

    cancelled = client.post(f"/api/v1/tasks/{body['task_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["cancel_requested"] is True  # visible immediately
    assert cancelled.json()["status"] != "succeeded"

    release.set()
    final = _wait(client, body["task_id"])
    assert final["status"] == "cancelled"
    assert final["cancel_summary"] == "I put down the mug."
    assert sim.inventory_objects == []  # hands are empty again
    assert final["thoughts"][-1]["text"] == "Okay, I stopped. I put down the mug."
    # Cancelling never writes a lesson.
    assert final["learned"] == []


def test_cancelling_an_unknown_task_is_a_friendly_404(client):
    _wire()
    response = client.post("/api/v1/tasks/nope/cancel")
    assert response.status_code == 404
    assert "don't have a job with that id" in response.json()["message"]


def test_the_next_task_runs_normally_after_a_cancel(client):
    _wire()
    first = _post(client, "find the mug").json()
    client.post(f"/api/v1/tasks/{first['task_id']}/cancel")
    _wait(client, first["task_id"])
    second = _post(client, "find the book").json()
    assert _wait(client, second["task_id"])["status"] == "succeeded"


# -- server-sent events ----------------------------------------------------------


def _read_sse(client, url) -> List[Tuple[str, dict]]:
    events: List[Tuple[str, dict]] = []
    with client.stream("GET", url) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        name = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: ") and name:
                events.append((name, json.loads(line[6:])))
                if name == "end":
                    break
    return events


def test_a_task_stream_pushes_state_and_events_until_it_ends(client):
    _wire()
    body = _post(client, "put the mug on the shelf").json()

    events = _read_sse(client, f"/api/v1/tasks/{body['task_id']}/stream")

    names = [n for n, _ in events]
    assert names[0] == "state" and names[-1] == "end"
    assert "task_event" in names
    states = [d for n, d in events if n == "state"]
    assert states[-1]["status"] == "succeeded"
    assert states[-1]["planner"] == "rule_based"
    assert events[-1][1] == {"status": "succeeded"}
    kinds = [d["event"] for n, d in events if n == "task_event"]
    assert kinds[0] == "TASK_CREATED" and "TASK_COMPLETED" in kinds


def test_streaming_an_unknown_task_is_a_404_before_any_stream_opens(client):
    response = client.get("/api/v1/tasks/nope/stream")
    assert response.status_code == 404
    assert response.json()["category"] == "task_not_found"


def test_the_all_tasks_stream_starts_with_a_snapshot(client):
    _wire()
    _wait(client, _post(client, "find the mug").json()["task_id"])
    with client.stream("GET", "/api/v1/tasks/stream?once=true") as response:
        assert response.status_code == 200
        lines = []
        for line in response.iter_lines():
            lines.append(line)
            if line.startswith("data: "):
                break
    snapshot = json.loads(lines[-1][6:])
    assert snapshot[0]["goal"] == "find" and snapshot[0]["status"] == "succeeded"


# -- API key and rate limit ------------------------------------------------------


def test_with_an_api_key_set_guarded_routes_need_it(client, monkeypatch):
    _wire()
    monkeypatch.setenv("API_KEY", "s3cret")

    denied = client.get("/api/v1/tasks")
    assert denied.status_code == 401
    assert denied.json()["category"] == "unauthorized"
    assert "API key" in denied.json()["message"]
    assert (
        client.get("/api/v1/tasks", headers={"X-API-Key": "wrong"}).status_code == 401
    )
    assert (
        client.get("/api/v1/tasks", headers={"X-API-Key": "s3cret"}).status_code == 200
    )
    assert client.get("/api/v1/lab/stats").status_code == 401
    assert client.post("/api/v1/memory/x/forget").status_code == 401
    # Health is not guarded, so a load balancer can still check it.
    assert client.get("/health").status_code == 200


def test_the_stream_routes_also_accept_the_key_as_a_query_parameter(
    client, monkeypatch
):
    _wire()
    task = _post(client, "find the mug").json()
    monkeypatch.setenv("API_KEY", "s3cret")

    assert client.get(f"/api/v1/tasks/{task['task_id']}/stream").status_code == 401
    with client.stream(
        "GET", f"/api/v1/tasks/{task['task_id']}/stream?api_key=s3cret"
    ) as ok:
        assert ok.status_code == 200
    # ...but only the stream routes: a plain route ignores the query key.
    assert client.get("/api/v1/tasks?api_key=s3cret").status_code == 401


def test_without_an_api_key_nothing_changes(client):
    _wire()
    assert client.get("/api/v1/tasks").status_code == 200


def test_the_rate_limit_answers_429_with_retry_after(client, monkeypatch):
    _wire()
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")

    codes = [client.get("/api/v1/tasks").status_code for _ in range(4)]

    assert codes == [200, 200, 200, 429]
    blocked = client.get("/api/v1/tasks")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    body = blocked.json()
    assert body["category"] == "rate_limited"
    assert "Please wait" in body["message"]


def test_rate_limits_are_per_caller_when_keys_differ(client, monkeypatch):
    _wire()
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("API_KEY", "a")
    assert client.get("/api/v1/tasks", headers={"X-API-Key": "a"}).status_code == 200
    assert client.get("/api/v1/tasks", headers={"X-API-Key": "a"}).status_code == 429


def test_limiter_window_rolls_forward():
    from api.security import SlidingWindowLimiter

    lim = SlidingWindowLimiter(window=10.0)
    assert lim.hit("k", 2, now=0.0) is None
    assert lim.hit("k", 2, now=1.0) is None
    wait = lim.hit("k", 2, now=2.0)
    assert wait is not None and 7.9 < wait < 8.1
    assert lim.hit("k", 2, now=10.5) is None  # the first hit has aged out


# -- audio upload cap ----------------------------------------------------------------


class _FakeModel:
    def transcribe(self, path):
        return {"text": "find the mug", "language": "en"}


def test_an_oversized_recording_is_refused_with_a_clear_message(client, monkeypatch):
    app.dependency_overrides[get_speech_agent] = lambda: SpeechAgent(
        WhisperTranscriber(model=_FakeModel())
    )
    monkeypatch.setenv("SPEECH_MAX_UPLOAD_BYTES", "1000")

    big = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("clip.wav", b"x" * 5000, "audio/wav")},
    )
    assert big.status_code == 413
    assert big.json()["category"] == "audio_too_large"
    assert "too long to send" in big.json()["message"]

    small = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("clip.wav", b"x" * 500, "audio/wav")},
    )
    assert small.status_code == 200


# -- readable errors ------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {"instruction": ""},
            "Please tell MILO what to do -- the instruction can't be empty.",
        ),
        (
            {"instruction": "x" * 2001},
            "That instruction is too long. Please keep it under 2000 characters.",
        ),
        ({}, "Please tell MILO what to do -- the instruction can't be empty."),
    ],
)
def test_validation_errors_are_sentences_a_person_can_act_on(client, payload, message):
    _wire()
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 422
    assert response.json() == {"category": "invalid_request", "message": message}


def test_unknown_paths_use_the_same_error_shape(client):
    response = client.get("/api/v1/nothing-here")
    assert response.status_code == 404
    assert set(response.json()) == {"category", "message"}


def test_no_simulator_message_is_plain(client):
    app.dependency_overrides.pop(get_simulator, None)
    response = _post(client, "find the mug")
    assert response.status_code == 503
    assert "practice room" in response.json()["message"]


# -- explanations and thoughts ---------------------------------------------------------


def test_steps_explain_themselves_while_the_task_runs(client):
    _wire()
    body = _post(client, "put the apple in the fridge").json()
    final = _wait(client, body["task_id"])

    steps = {s["step_id"]: s for s in final["current_plan"]["steps"]}
    assert steps[1]["explanation"] == "I can see the apple."
    assert steps[3]["explanation"] == "Got the apple."
    assert steps[7]["explanation"] == "The apple is in the fridge."
    texts = [t["text"] for t in final["thoughts"]]
    assert texts[0] == "Plan ready: 8 small steps."
    assert "Got the apple." in texts
    assert texts[-2:] == ["The fridge is closed.", "All done!"]


def test_a_replan_is_explained_in_plain_language(client):
    navigations = {"n": 0}

    def fail_the_walk_to_the_fridge() -> None:
        navigations["n"] += 1
        if navigations["n"] == 2:
            sim._fail_actions.add("navigate")
        elif navigations["n"] == 3:
            sim._fail_actions.discard("navigate")

    sim = FakeSimulator(
        objects=kitchen(), hooks={"navigate": fail_the_walk_to_the_fridge}
    )
    _wire(sim)
    body = _post(client, "put the apple in the fridge").json()
    final = _wait(client, body["task_id"])

    assert final["status"] == "succeeded"
    texts = [t["text"] for t in final["thoughts"]]
    assert "I couldn't reach the fridge, so I'm trying another route." in texts
    assert any(t.startswith("Plan ready:") and "already done" in t for t in texts)


def test_a_retry_is_explained_in_plain_language(client):
    opens = {"n": 0}

    def flaky_open() -> None:
        opens["n"] += 1
        if opens["n"] >= 2:
            sim._fail_actions.discard("open")

    sim = FakeSimulator(
        objects=kitchen(), fail_actions={"open"}, hooks={"open": flaky_open}
    )
    _wire(sim)
    final = _wait(
        client, _post(client, "put the apple in the fridge").json()["task_id"]
    )

    assert final["status"] == "succeeded"
    assert "That didn't quite work, so I'm trying it again." in [
        t["text"] for t in final["thoughts"]
    ]


def test_giving_up_is_explained_too(client):
    sim = FakeSimulator(objects=kitchen(), fail_actions={"pickup"})
    _wire(sim)
    final = _wait(
        client, _post(client, "put the apple in the fridge").json()["task_id"]
    )

    assert final["status"] == "failed"
    reflect = [t["text"] for t in final["thoughts"] if t["kind"] == "reflect"]
    assert reflect[-1].startswith("I had to stop")
    failed = next(s for s in final["current_plan"]["steps"] if s["status"] == "failed")
    assert failed["explanation"].startswith("I had to stop")


def test_memory_that_helped_shows_up_in_the_thoughts(client, tmp_path):
    mem = memory(tmp_path)
    mem.remember_preference("mug", "located_on", "shelf")
    _wire(mem=mem)
    final = _wait(client, _post(client, "find the mug").json()["task_id"])
    memory_thoughts = [t["text"] for t in final["thoughts"] if t["kind"] == "memory"]
    assert memory_thoughts and memory_thoughts[0].startswith("I remember:")


# -- forget this ------------------------------------------------------------------------


def test_forgetting_a_memory_archives_it_and_stops_it_being_used(client, tmp_path):
    mem = memory(tmp_path)
    app.dependency_overrides[get_memory_agent] = lambda: mem._memory_agent
    made = mem.remember_preference("mug", "located_on", "shelf")
    assert made is not None
    assert "mug" in mem.usual_places()

    response = client.post(f"/api/v1/memory/{made.memory_id}/forget")
    assert response.status_code == 200
    assert response.json()["status"] == "archived"
    assert "mug" not in mem.usual_places()
    # Still listed (so the UI can show it as forgotten), and safe to repeat.
    listed = client.get("/api/v1/memory").json()["memories"]
    assert [m["status"] for m in listed if m["memory_id"] == made.memory_id] == [
        "archived"
    ]
    assert client.post(f"/api/v1/memory/{made.memory_id}/forget").status_code == 200


def test_forgetting_something_that_is_not_there_is_a_friendly_404(client, tmp_path):
    app.dependency_overrides[get_memory_agent] = lambda: memory(tmp_path)._memory_agent
    response = client.post("/api/v1/memory/not-a-real-id/forget")
    assert response.status_code == 404
    assert response.json()["category"] == "memory_not_found"
    assert "don't have a memory like that" in response.json()["message"]
