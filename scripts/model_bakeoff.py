"""Pick the local model: every candidate on the same 40-command DEV set (never TEST).

    python scripts/model_bakeoff.py --models qwen2.5:7b llama3.1:8b qwen3.5:4b \
        [--runs 3] [--url http://localhost:11434]          (make model-bakeoff)

Per model and run: valid-JSON rate, plan validity (model answers that pass the registry
and validator), correct rate (the plan runs and its goal checks pass in the synthetic
home; ambiguous -> one question, impossible -> a refusal, both without acting), tokens per
second, seconds per command, and peak VRAM (nvidia-smi, sampled every 0.5 s, includes
everything else on the GPU). Temperature 0; seeds 0, 1, 2 for the three runs.

Resumable: each finished (model, run) is saved in results/bakeoff/ and skipped next time.
Expect roughly 5-20 minutes per model per run on an RTX 4050 laptop GPU.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from novel.dev_set import dev_commands, dev_scene  # noqa: E402
from novel.eval_novel import correct, run_one  # noqa: E402
from novel.providers import OllamaProvider  # noqa: E402
from novel.safety import Constraints  # noqa: E402
from novel.skills import SkillLibrary  # noqa: E402

OUT = ROOT / "results" / "bakeoff"


class VramPeak:
    def __init__(self) -> None:
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5).stdout  # fmt: skip
                self.peak = max(self.peak, int(out.split()[0]))
            except Exception:
                pass
            self._stop.wait(0.5)

    def __enter__(self) -> "VramPeak":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join()


def unload(model: str, url: str) -> None:
    """Ask Ollama to drop the model from VRAM now (keep_alive 0)."""
    import urllib.request

    body = json.dumps({"model": model, "keep_alive": 0}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url + "/api/generate", data=body,
                               headers={"Content-Type": "application/json"}), timeout=30).read()  # fmt: skip
    except Exception:
        pass


def one_run(model: str, url: str, seed: int, prompt: str = "v3") -> Dict[str, Any]:
    constraints = Constraints.load()
    provider = OllamaProvider(model=model, url=url, seed=seed, timeout_s=180,
                              prompt_version=prompt)  # fmt: skip
    commands = dev_commands()
    rows = []
    started = time.perf_counter()
    with VramPeak() as vram, tempfile.TemporaryDirectory() as tmp:
        for i, item in enumerate(commands):
            r = run_one(item["command"], provider, SkillLibrary(Path(tmp) / f"{i}.db"),
                        constraints, scene_objects=dev_scene())  # fmt: skip
            rows.append({"command": item["command"], "category": item["category"],
                         "correct": correct(item, r), **{k: r[k] for k in
                         ("status", "model_calls", "caught_unsafe", "caught_infeasible", "acted", "ms")}})  # fmt: skip
            print(
                f"  [{model} seed {seed}] {i + 1:2d}/{len(commands)} {'ok ' if rows[-1]['correct'] else 'BAD'} {item['command']}",
                flush=True,
            )
    calls = sum(r["model_calls"] for r in rows)
    rejected = sum(r["caught_unsafe"] + r["caught_infeasible"] for r in rows)
    s = provider.stats
    return {
        "model": model,
        "seed": seed,
        "prompt": prompt,
        "correct_rate": sum(r["correct"] for r in rows) / len(rows),
        "valid_json_rate": 1 - s["invalid_json"] / max(1, s["calls"]),
        "plan_validity": 1 - rejected / max(1, calls),
        "model_calls_per_command": calls / len(rows),
        "tokens_per_second": (
            s["eval_tokens"] / s["eval_seconds"] if s["eval_seconds"] else None
        ),
        "seconds_per_command": (time.perf_counter() - started) / len(rows),
        "timeouts": s["timeouts"],
        "context_full": s["context_full"],
        "prompt_tokens_max": s["prompt_tokens_max"],
        "num_ctx": provider.num_ctx,
        "peak_vram_mib": vram.peak,
        "rows": rows,
    }


def summary(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"model": runs[0]["model"], "runs": len(runs)}
    out["context_full"] = sum(r.get("context_full", 0) for r in runs)
    out["prompt_tokens_max"] = max(r.get("prompt_tokens_max", 0) for r in runs)
    for key in ("correct_rate", "valid_json_rate", "plan_validity", "model_calls_per_command",
                "tokens_per_second", "seconds_per_command", "peak_vram_mib"):  # fmt: skip
        values = [r[key] for r in runs if r[key] is not None]
        out[key] = round(statistics.mean(values), 3) if values else None
        out[key + "_spread"] = (
            round(max(values) - min(values), 3) if len(values) > 1 else 0.0
        )
    return out


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--url", default="http://localhost:11434")
    p.add_argument("--prompt", default="v3", choices=["v2", "v3"],
                   help="v3 (default): the answer starts with a plan/ask/refuse decision")  # fmt: skip
    p.add_argument(
        "--out", type=Path, default=OUT, help="results folder (default results/bakeoff)"
    )
    a = p.parse_args()
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    table = []
    for model in a.models:
        runs = []
        for seed in range(a.runs):
            path = out / f"{model.replace(':', '_').replace('/', '_')}_seed{seed}.json"
            if path.exists():
                runs.append(json.loads(path.read_text()))
                continue
            print(f"{model}, run {seed + 1}/{a.runs}", flush=True)
            result = one_run(model, a.url.rstrip("/"), seed, a.prompt)
            path.write_text(json.dumps(result, indent=1))
            runs.append(result)
        unload(model, a.url.rstrip("/"))
        table.append(summary(runs))
    table.sort(key=lambda r: (-r["correct_rate"], r["seconds_per_command"]))
    (out / "summary.json").write_text(json.dumps(table, indent=2))
    for row in table:
        print(json.dumps(row))


if __name__ == "__main__":
    main()
