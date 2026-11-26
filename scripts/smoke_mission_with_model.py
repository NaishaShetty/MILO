"""Smoke test: one real mission with AI2-THOR, the vision models and the local language
model all on the same GPU. Run the backend first with the model as the new-task planner:

    cd backend
    VISION_ENABLE_SIMULATOR=true MILO_NOVEL_PROVIDER=ollama MILO_OLLAMA_MODEL=qwen2.5:7b \
      MILO_OLLAMA_KEEP_ALIVE=0 uvicorn api.app:app --port 8000
    python scripts/smoke_mission_with_model.py ["stash the apple in the fridge"]

It sends a command MILO has no recipe for (so the language model must plan it), polls the
mission to the end, samples nvidia-smi every 0.5 s, and prints the outcome, the time and
the peak VRAM. Exit code 0 only if the mission succeeded and VRAM never ran out.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.request

API = "http://127.0.0.1:8000/api/v1"


def call(method: str, path: str, body: object = None) -> dict:
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})  # fmt: skip
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "stash the apple in the fridge"
    peak, total = [0], [0]
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                                      "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout  # fmt: skip
                used, cap = (int(x) for x in out.split(","))
                peak[0], total[0] = max(peak[0], used), cap
            except Exception:
                pass
            stop.wait(0.5)

    threading.Thread(target=sample, daemon=True).start()
    started = time.time()
    task = call("POST", "/tasks", {"instruction": command})
    if "task_id" not in task:
        print("not started as a mission:", task)
        return 1
    state = task
    approved = []
    while state.get("status") not in ("succeeded", "failed", "cancelled"):
        time.sleep(2)
        state = call("GET", f"/tasks/{task['task_id']}")
        pending = state.get("pending_decision")
        if pending:
            # Answer like a user would (plans MILO works out itself wait for an OK).
            approved.append({"kind": pending.get("kind"),
                             "steps": [f"{s.get('action')} {s.get('target') or ''} {s.get('container') or ''}".strip()
                                       for s in pending.get("steps") or []]})  # fmt: skip
            call("POST", f"/tasks/{task['task_id']}/decision", {"choice": "approve"})
        if time.time() - started > 900:
            print("gave up after 15 minutes")
            break
    stop.set()
    seconds = time.time() - started
    errors = state.get("error") or ""
    oom = "out of memory" in json.dumps(state).lower()
    thoughts = [
        f"{t.get('kind')}: {t.get('text')}" for t in (state.get("thoughts") or [])
    ][-8:]
    failures = [f.get("message") for f in (state.get("failures") or [])][-3:]
    print(json.dumps({"command": command, "status": state.get("status"), "seconds": round(seconds, 1),
                      "peak_vram_mib": peak[0], "vram_total_mib": total[0], "out_of_memory": oom,
                      "error": errors, "approved": approved, "failures": failures,
                      "last_thoughts": thoughts}, indent=2))  # fmt: skip
    return 0 if state.get("status") == "succeeded" and not oom else 1


if __name__ == "__main__":
    sys.exit(main())
