"""
eval_parser.py (backend/learning/parser)

Train the small parser on TRAIN phrasings and score it on held-out *phrasings* (with
held-out object/place words), against the rule phrasebook and the two combined
("rules first, learned parser when the rules do not understand").

    cd backend
    python -m learning.parser.eval_parser --out artifacts/parser

Reports per method: coverage (produced a task), exact accuracy (goal + object + target
all right), accuracy when answering, plus the learned parser's calibration (ECE) and a
confidence-threshold sweep for the combined system.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from language.interpreter import InstructionInterpreter
from learning.metrics import ece
from learning.parser.data import OBJECTS_HELD_OUT, Example, generate
from learning.parser.model import Parsed, SmallParser
from schemas.task import SingleTask

Triple = Tuple[Optional[str], Optional[str], Optional[str]]


def gold(e: Example) -> Triple:
    return (e.goal, e.object, e.target)


def rules_triple(interpreter: InstructionInterpreter, text: str) -> Optional[Triple]:
    r = interpreter.interpret(text)
    if r.kind != "task" or not isinstance(r.task, SingleTask):
        return None
    t = r.task
    if t.goal == "clear_table":
        return (t.goal, t.source_location, t.target_location)
    return (t.goal, t.object, t.target)


def learned_triple(p: Parsed) -> Triple:
    return (p.goal, p.object, p.target)


def score(preds: List[Optional[Triple]], golds: List[Triple]) -> Dict[str, float]:
    answered = [i for i, p in enumerate(preds) if p is not None]
    right = sum(preds[i] == golds[i] for i in answered)
    n = max(len(golds), 1)
    return {
        "coverage": len(answered) / n,
        "exact_accuracy": right / n,
        "accuracy_when_answering": right / max(len(answered), 1),
    }


def run(
    out: Path, n_train: int = 6000, n_test: int = 1500, seed: int = 0
) -> Dict[str, Any]:
    train = generate("train", n_train, seed)
    val = generate("val", 1000, seed + 1)  # same phrasings as train, new draws
    test = generate("test", n_test, seed)  # phrasings never seen in training
    model = SmallParser().fit(train)
    interpreter = InstructionInterpreter()
    texts = [e.text for e in test]
    golds = [gold(e) for e in test]

    t0 = time.perf_counter()
    parsed = [model.parse(t) for t in texts]
    per_ms = (time.perf_counter() - t0) / len(texts) * 1000
    learned: List[Optional[Triple]] = [learned_triple(p) for p in parsed]
    rules = [rules_triple(interpreter, t) for t in texts]
    correct = np.array([learned[i] == golds[i] for i in range(len(golds))], dtype=float)
    conf = np.array([p.confidence for p in parsed])

    report: Dict[str, Any] = {
        "n_train": len(train),
        "n_test": len(test),
        "latency_ms_per_parse": per_ms,
        "val_exact_seen_phrasing": score(
            [learned_triple(model.parse(e.text)) for e in val], [gold(e) for e in val]
        )["exact_accuracy"],
        "rules": score(rules, golds),
        "learned_alone": score(learned, golds),
        "ece_exact": float(ece(correct, conf)),
        "combined_rules_then_learned": {},
    }
    for thr in (0.0, 0.5, 0.7, 0.85, 0.95):
        comb = [
            r if r is not None else (learned[i] if conf[i] >= thr else None)
            for i, r in enumerate(rules)
        ]
        report["combined_rules_then_learned"][str(thr)] = score(comb, golds)
    # Learned first when confident, rules otherwise -- on novel phrasings (test) and on
    # the phrasings the rules were written for (val), to check it does not regress them.
    val_golds = [gold(e) for e in val]
    val_rules = [rules_triple(interpreter, e.text) for e in val]
    val_parsed = [model.parse(e.text) for e in val]
    report["learned_first"] = {}
    for thr in (0.5, 0.7, 0.85, 0.95):
        on_test = [
            learned[i] if conf[i] >= thr else rules[i] for i in range(len(texts))
        ]
        on_val = [
            learned_triple(p) if p.confidence >= thr else val_rules[i]
            for i, p in enumerate(val_parsed)
        ]
        report["learned_first"][str(thr)] = {
            "novel_phrasing": score(on_test, golds),
            "seen_phrasing": score(on_val, val_golds),
        }
    report["rules_on_seen_phrasing"] = score(val_rules, val_golds)
    by_goal: Dict[str, List[float]] = {}
    for e, c in zip(test, correct):
        by_goal.setdefault(e.goal, []).append(float(c))
    report["learned_by_goal"] = {
        g: float(np.mean(v)) for g, v in sorted(by_goal.items())
    }
    unseen = [i for i, e in enumerate(test) if e.object in OBJECTS_HELD_OUT]
    report["learned_unseen_object_exact"] = (
        float(correct[unseen].mean()) if unseen else None
    )
    out.mkdir(parents=True, exist_ok=True)
    model.save(out / "parser.pkl")
    (out / "eval.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=Path("artifacts/parser"))
    parser.add_argument("--train", type=int, default=6000)
    parser.add_argument("--test", type=int, default=1500)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.out, args.train, args.test), indent=2))


if __name__ == "__main__":
    main()
