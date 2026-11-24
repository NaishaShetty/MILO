"""
promote.py (backend/learning)

Retrain from the latest logs, evaluate against the model in service, and only
promote the new one if it wins on the held-out test scenes. The previous
version is kept (`current.json` records `previous`) so it can be rolled back.

    cd backend
    python -m learning.promote            # retrain, compare, maybe promote
    python -m learning.promote --rollback # go back to the previous version
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

from learning.train_outcome import train


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text()) if path.exists() else {}


def wins(new: Dict[str, Any], old: Optional[Dict[str, Any]]) -> bool:
    """Better AUROC by a real margin without worse calibration (ECE must stay < 0.05)."""
    if old is None:
        return new["ece"] < 0.05
    return new["auroc"] > old["auroc"] + 0.002 and new["ece"] <= max(old["ece"], 0.05)


def promote(data: Path, out: Path) -> Dict[str, Any]:
    pointer = out / "current.json"
    current = _read(pointer)
    old_metrics = None
    if current.get("version") and (out / current["version"] / "metrics.json").exists():
        old_metrics = _read(out / current["version"] / "metrics.json")["trees"]
    result = train(data, out)
    new_version = result["registry"]["version"]
    ok = wins(result["trees"], old_metrics)
    if ok:
        pointer.write_text(
            json.dumps(
                {"version": new_version, "previous": current.get("version")}, indent=2
            )
        )
    return {
        "candidate": new_version,
        "promoted": ok,
        "in_service": new_version if ok else current.get("version"),
        "candidate_metrics": result["registry"]["metrics"],
        "previous_metrics": old_metrics,
    }


def rollback(out: Path) -> Optional[str]:
    pointer = out / "current.json"
    current = _read(pointer)
    if not current.get("previous"):
        return None
    pointer.write_text(
        json.dumps({"version": current["previous"], "previous": None}, indent=2)
    )
    return current["previous"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=Path("data/dataset"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/outcome"))
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        print("rolled back to", rollback(args.out))
    else:
        print(json.dumps(promote(args.data, args.out), indent=2))


if __name__ == "__main__":
    main()
