"""OllamaProvider against a mocked Ollama server (a real HTTP server on localhost)."""

from __future__ import annotations

import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from novel import providers
from novel.eval_novel import S, into, plan, run_one
from novel.providers import OllamaProvider, PlanRequest, ProviderError, build_provider
from novel.safety import Constraints
from novel.skills import SkillLibrary

GOOD = plan("chill the apple", into("apple", "fridge", True), [])


class FakeOllama:
    """Replies to POST /api/chat with the next item of `script`: a dict (JSON reply body),
    a string (raw `message.content`), ("sleep", s) or ("status", code)."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"models": []}')

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                step = outer.script.pop(0) if outer.script else GOOD
                if isinstance(step, tuple) and step[0] == "sleep":
                    time.sleep(step[1])
                    step = GOOD
                if isinstance(step, tuple) and step[0] == "status":
                    self.send_response(step[1])
                    self.end_headers()
                    self.wfile.write(b'{"error": "model not found"}')
                    return
                content = step if isinstance(step, str) else json.dumps(step)
                reply = {"message": {"role": "assistant", "content": content},
                         "eval_count": 40, "eval_duration": 2_000_000_000}  # fmt: skip
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(reply).encode())

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake():
    servers = []

    def make(*script):
        s = FakeOllama(script)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def _request(command="chill the apple"):
    return PlanRequest(
        command=command, scene=[{"objectType": "Apple"}], holding=None, actions=[]
    )


def test_success_sends_schema_temperature_zero_and_dev_examples(fake):
    server = fake(GOOD)
    p = OllamaProvider(model="qwen2.5:7b", url=server.url)
    assert p.propose(_request()) == GOOD
    body = server.requests[0]
    assert body["format"]["type"] == "object"  # the plan JSON schema
    assert body["options"] == {
        "temperature": 0,
        "seed": 0,
        "num_ctx": 8192,  # not Ollama's 4096 default, which cut long prompts
        "num_predict": 1024,
    }
    assert "\n" not in body["messages"][-1]["content"]  # compact JSON prompt
    assert body["stream"] is False
    examples = [m["content"] for m in body["messages"][1:-1] if m["role"] == "user"]
    from novel.dev_set import few_shot_commands

    assert len(examples) == len(few_shot_commands())
    assert all(any(cmd in e for cmd in few_shot_commands()) for e in examples)
    assert p.stats["eval_tokens"] == 40 and p.stats["eval_seconds"] == pytest.approx(
        2.0
    )


def test_identical_requests_are_cached(fake):
    server = fake(GOOD, GOOD)
    p = OllamaProvider(url=server.url)
    p.propose(_request())
    p.propose(_request())
    assert len(server.requests) == 1


def test_malformed_json_is_retried_then_succeeds(fake):
    server = fake("not json {", GOOD)
    p = OllamaProvider(url=server.url, retries=2)
    assert p.propose(_request()) == GOOD
    assert p.stats["invalid_json"] == 1 and len(server.requests) == 2


def test_malformed_json_every_time_raises_a_clear_error(fake):
    server = fake("nope", "[1, 2]", "still nope")
    p = OllamaProvider(url=server.url, retries=2)
    with pytest.raises(ProviderError, match="wasn't"):
        p.propose(_request())
    assert len(server.requests) == 3


def test_timeout_is_retried_and_reported(fake):
    server = fake(("sleep", 1.0), ("sleep", 1.0))
    p = OllamaProvider(url=server.url, timeout_s=0.2, retries=1)
    with pytest.raises(ProviderError, match="too long"):
        p.propose(_request())
    assert p.stats["timeouts"] == 2


def test_missing_model_says_how_to_pull_it(fake):
    server = fake(("status", 404))
    with pytest.raises(ProviderError, match="ollama pull qwen3.5:4b"):
        OllamaProvider(model="qwen3.5:4b", url=server.url).propose(_request())


def test_unreachable_server_is_a_clear_error_and_build_falls_back_offline(monkeypatch):
    with pytest.raises(ProviderError, match="couldn't reach"):
        OllamaProvider(url="http://127.0.0.1:9", timeout_s=1).propose(_request())
    monkeypatch.setenv("MILO_NOVEL_PROVIDER", "ollama")
    monkeypatch.setenv("MILO_OLLAMA_URL", "http://127.0.0.1:9")
    assert build_provider().name == "offline"


def test_build_provider_picks_ollama_when_reachable(fake, monkeypatch):
    server = fake()
    monkeypatch.setenv("MILO_NOVEL_PROVIDER", "ollama")
    monkeypatch.setenv("MILO_OLLAMA_URL", server.url)
    monkeypatch.setenv("MILO_OLLAMA_MODEL", "llama3.1:8b")
    p = build_provider()
    assert isinstance(p, providers.OllamaProvider) and p.model == "llama3.1:8b"


def test_repair_round_feeds_the_validator_error_back(fake):
    bad = plan("chill the apple", into("unicorn", "fridge", True), [])
    server = fake(bad, GOOD)
    with tempfile.TemporaryDirectory() as tmp:
        r = run_one("chill the apple", OllamaProvider(url=server.url),
                    SkillLibrary(Path(tmp) / "s.db"), Constraints.load())  # fmt: skip
    assert r["status"] == "succeeded"
    assert r["model_calls"] == 2 and r["caught_infeasible"] == 1
    second_prompt = json.loads(server.requests[1]["messages"][-1]["content"])
    assert any("won't work" in f for f in second_prompt["feedback_from_last_attempt"])


def test_a_plan_with_an_action_outside_the_registry_never_runs(fake):
    # The model insists on an action MILO doesn't have, every time it is asked.
    server = fake(*[plan("x", [S("throw", "apple")], [])] * 10)
    with tempfile.TemporaryDirectory() as tmp:
        r = run_one("chill the apple", OllamaProvider(url=server.url),
                    SkillLibrary(Path(tmp) / "s.db"), Constraints.load())  # fmt: skip
    assert r["status"] == "failed", r
    assert not r["acted"] and r["steps_run"] == 0
    assert (
        r["model_calls"] == len(server.requests) == 4
    )  # stops at the model-call budget
    assert "throw" in r["reason"]


def test_prompt_v3_decides_before_writing_steps(fake):
    server = fake(GOOD)
    OllamaProvider(model="m", url=server.url, prompt_version="v3").propose(_request())
    body = server.requests[0]
    assert list(body["format"]["properties"])[0] == "decision"
    assert body["format"]["required"][0] == "decision"
    assert '"decision"' in body["messages"][0]["content"]
    shown = [json.loads(m["content"]) for m in body["messages"][1:-1]
             if m["role"] == "assistant"]  # fmt: skip
    assert {a["decision"] for a in shown} == {"plan", "ask", "refuse"}
    assert all(list(a)[0] == "decision" for a in shown)


def test_prompt_v2_keeps_the_old_schema(fake):
    server = fake(GOOD)
    OllamaProvider(model="m", url=server.url, prompt_version="v2").propose(_request())
    assert "decision" not in server.requests[0]["format"]["properties"]


def test_decision_ask_drops_any_steps_the_model_also_wrote(fake):
    both = {**GOOD, "decision": "ask", "question": "Which apple?"}
    server = fake(both)
    out = OllamaProvider(model="m", url=server.url, prompt_version="v3").propose(
        _request("deal with it")
    )
    assert out["steps"] == [] and out["question"] == "Which apple?"


def test_decision_refuse_without_a_reason_still_refuses(fake):
    server = fake({**GOOD, "decision": "refuse"})
    out = OllamaProvider(model="m", url=server.url, prompt_version="v3").propose(
        _request("walk the dog")
    )
    assert out["steps"] == [] and out["impossible"]


def test_decision_plan_ignores_a_stray_question(fake):
    server = fake({**GOOD, "decision": "plan", "question": "Sure?"})
    out = OllamaProvider(model="m", url=server.url, prompt_version="v3").propose(
        _request()
    )
    assert out["steps"] == GOOD["steps"] and out["question"] == ""


def test_unknown_prompt_version_is_rejected():
    with pytest.raises(ValueError):
        OllamaProvider(model="m", url="http://127.0.0.1:1", prompt_version="v9")
