"""The local-model evaluation pipeline, with a mocked Ollama that answers like the
reference plans: it must then score 60/60 with no unsafe actions, and skills must cut
model calls on repeats."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from novel.eval_novel import commands, evaluate_local


@pytest.fixture
def perfect_model():
    answers = {i["command"]: i["answer"] for i in commands()}
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            command = json.loads(body["messages"][-1]["content"])["command"]
            calls.append(command)
            reply = {"message": {"content": json.dumps(answers[command])}, "eval_count": 10,
                     "eval_duration": 10_000_000, "prompt_eval_count": 900}  # fmt: skip
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", calls
    server.shutdown()


def test_local_eval_with_a_perfect_model(perfect_model, tmp_path):
    url, calls = perfect_model
    report = evaluate_local("fake:1b", runs=1, url=url, out_dir=tmp_path)
    assert report["source"].startswith("fake:1b via Ollama")
    assert report["correct_rate"]["mean"] == 1.0
    assert report["unsafe_actions_executed"]["mean"] == 0
    assert report["skills_same_command_again"]["model_calls"]["mean"] == 0
    assert report["skills_transfer_other_object"]["used_skill"]["mean"] == 1.0
    curve = report["skills_curve"]
    assert [p["model_calls"] for p in curve][1:] == [0] * (len(curve) - 1)
    # resumable: a second call reuses the saved run instead of asking the model again
    before = len(calls)
    evaluate_local("fake:1b", runs=1, url=url, out_dir=tmp_path)
    assert len(calls) == before
