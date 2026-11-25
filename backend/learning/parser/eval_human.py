"""
eval_human.py (backend/learning/parser)

Score the rule phrasebook and the learned parser on the hand-written test set
(data/parser_test_human.jsonl), which nothing was trained or tuned on.

    cd backend
    python -m learning.parser.eval_human [--parser artifacts/parser]

Reports, per method: coverage, exact accuracy (goal + object + target) and field-level
accuracy (goal, object and target separately). Lines whose keys start with "_" (the
header, the example) are skipped. With fewer than 20 real commands it says the set is
not filled in yet and reports nothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SET = REPO / "data" / "parser_test_human.jsonl"
MIN_COMMANDS = 20

Triple = Tuple[Optional[str], Optional[str], Optional[str]]


def load(path: Path) -> List[Dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if any(k.startswith("_") for k in row):
            continue
        rows.append(row)
    return rows


def field_scores(
    preds: List[Optional[Triple]], golds: List[Triple]
) -> Dict[str, float]:
    n = max(len(golds), 1)
    out = {"coverage": sum(p is not None for p in preds) / n,
           "exact": sum(p == g for p, g in zip(preds, golds)) / n}  # fmt: skip
    for i, name in enumerate(("goal", "object", "target")):
        out[name] = (
            sum(p is not None and p[i] == g[i] for p, g in zip(preds, golds)) / n
        )
    return out


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--set", type=Path, default=DEFAULT_SET)
    ap.add_argument("--parser", type=Path, default=Path("artifacts/parser"))
    a = ap.parse_args(argv)
    rows = load(a.set)
    if len(rows) < MIN_COMMANDS:
        print(f"{a.set} has {len(rows)} real commands; write at least {MIN_COMMANDS} "
              "(100 planned) before scoring. Nothing reported.")  # fmt: skip
        return
    from language.interpreter import InstructionInterpreter
    from learning.parser.eval_parser import rules_triple
    from learning.parser.model import SmallParser

    golds: List[Triple] = [(r["goal"], r.get("object"), r.get("target")) for r in rows]
    interpreter = InstructionInterpreter()
    report: Dict[str, Any] = {"commands": len(rows), "set": str(a.set)}
    report["phrasebook"] = field_scores(
        [rules_triple(interpreter, r["text"]) for r in rows], golds
    )
    model = SmallParser.load(a.parser)
    if model is None:
        report["learned_parser"] = (
            f"not trained here ({a.parser} missing: `make eval-parser` trains it)"
        )
    else:
        parsed = [model.parse(r["text"]) for r in rows]
        report["learned_parser"] = field_scores(
            [(p.goal, p.object, p.target) for p in parsed], golds
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
