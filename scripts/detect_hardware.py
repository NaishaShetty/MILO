"""Report this machine's GPU, memory, CPU and Ollama state; write results/hardware.json.

    python scripts/detect_hardware.py [--ollama-url URL]

Works in WSL or Linux. VRAM comes from nvidia-smi; on WSL the GPU is shared with Windows,
so "used by" lists what nvidia-smi can see plus the MILO components that load onto the
GPU when they run (AI2-THOR rendering, Grounding DINO, SAM2, the fast detector).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent

# What MILO itself puts on the GPU, measured on the RTX 4050 laptop (docs/local_model.md).
MILO_GPU_USERS = [
    "AI2-THOR (Unity rendering) when VISION_ENABLE_SIMULATOR=true",
    "Grounding DINO (open-vocabulary detection)",
    "SAM2 (segmentation, Vision panel only)",
    "YOLO11n ONNX fast detector when MILO_FAST_DETECTOR=1",
    "the local language model served by Ollama",
]


def _run(cmd: List[str]) -> Optional[str]:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, check=True
        ).stdout
    except Exception:
        return None


def gpu() -> Dict[str, Any]:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,driver_version",
                "--format=csv,noheader,nounits"])  # fmt: skip
    if not out:
        return {"present": False}
    name, total, used, free, driver = [
        x.strip() for x in out.splitlines()[0].split(",")
    ]
    apps = _run(
        [
            "nvidia-smi",
            "--query-compute-apps=process_name,used_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    return {
        "present": True,
        "name": name,
        "vram_mib": int(total),
        "vram_used_mib": int(used),
        "vram_free_mib": int(free),
        "driver": driver,
        "processes_visible": [
            line.strip() for line in (apps or "").splitlines() if line.strip()
        ],
        "note": "On WSL, Windows processes using the GPU may not be listed individually.",
    }


def memory() -> Dict[str, Any]:
    info: Dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            info[key] = int(value.split()[0])
    except Exception:
        return {}
    return {"ram_gib": round(info.get("MemTotal", 0) / 2**20, 1),
            "ram_available_gib": round(info.get("MemAvailable", 0) / 2**20, 1)}  # fmt: skip


def cpu() -> Dict[str, Any]:
    model = platform.processor()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass
    return {"model": model, "logical_cores": os.cpu_count()}


def ollama(url: str) -> Dict[str, Any]:
    windows_exe = (
        Path("/mnt/c/Users")
        / os.environ.get("WIN_USER", "")
        / "AppData/Local/Programs/Ollama/ollama.exe"
    )
    installed = (
        bool(shutil.which("ollama"))
        or windows_exe.exists()
        or any(Path("/mnt/c/Users").glob("*/AppData/Local/Programs/Ollama/ollama.exe"))
    )
    state: Dict[str, Any] = {
        "installed": installed,
        "url": url,
        "running": False,
        "models": [],
    }
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=3) as r:
            tags = json.loads(r.read())
        state["running"] = True
        state["models"] = [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1),
                            "quantization": (m.get("details") or {}).get("quantization_level")}
                           for m in tags.get("models", [])]  # fmt: skip
        with urllib.request.urlopen(url.rstrip("/") + "/api/ps", timeout=3) as r:
            state["loaded_now"] = [
                m["name"] for m in json.loads(r.read()).get("models", [])
            ]
    except Exception as exc:
        state["error"] = f"not reachable from here: {type(exc).__name__}"
    return state


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--ollama-url",
        default=os.environ.get("MILO_OLLAMA_URL", "http://localhost:11434"),
    )
    p.add_argument("--out", type=Path, default=ROOT / "results" / "hardware.json")
    a = p.parse_args()
    report = {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "os": platform.platform(),
        "wsl": "microsoft" in platform.release().lower(),
        "gpu": gpu(),
        "memory": memory(),
        "cpu": cpu(),
        "ollama": ollama(a.ollama_url),
        "milo_gpu_users": MILO_GPU_USERS,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
