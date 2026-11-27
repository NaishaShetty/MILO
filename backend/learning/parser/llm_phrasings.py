"""
llm_phrasings.py (backend/learning/parser)

Messier phrasings for the small instruction parser, written by a local language model,
and a before/after evaluation.

    cd backend && MILO_OLLAMA_URL=... python -m learning.parser.llm_phrasings \
        [--model qwen2.5:7b] [--per-goal 25]          (make parser-phrasings)

How labels stay honest: the model writes phrasing *templates* with slots ({o} for the
object, {t} for the place), never filled sentences, so the gold labels still come from
filling the slots, not from the model. Each template is checked: it must use exactly the
slots its goal needs, once each, and no other braces. Templates are lower-cased,
de-duplicated, and anything equal to a hand-written template in `data.py` is dropped.

Phrasing families stay apart: 30% of the accepted templates per goal (chosen by a hash,
so the split is stable) are held out and never trained on. The evaluation trains the
parser on the hand-written TRAIN templates alone ("before") and with the model's
training templates added ("after"), and tests both, and the rules, on two held-out sets:
the hand-written TEST phrasings and the model's held-out phrasings.

Generation uses temperature 0.8 with a fixed seed (temperature 0 would repeat itself);
everything else is deterministic. The human-written test set
(`data/parser_test_human.jsonl`) is scored separately by `eval_human` once it exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from learning.parser.data import GOALS, TEST, TRAIN, Example, generate

REPO = Path(__file__).resolve().parents[3]

#: What each goal means and which slots its phrasings must use.
GOAL_INFO: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "fetch": ("bring an object to the speaker", ("o",)),
    "deliver": ("take an object to a place", ("o", "t")),
    "store": (
        "put an object inside a container such as a fridge or drawer",
        ("o", "t"),
    ),
    "place": ("put an object on top of a surface", ("o", "t")),
    "pick_up": ("pick an object up and hold it", ("o",)),
    "open": ("open a door, fridge, drawer or similar", ("o",)),
    "close": ("close a door, fridge, drawer or similar", ("o",)),
    "turn_on": ("switch a device or light on", ("o",)),
    "turn_off": ("switch a device or light off", ("o",)),
    "find": ("look for an object and say where it is", ("o",)),
    "navigate_to": ("go to a place or room", ("t",)),
    "clear_table": ("move everything off one surface onto another place", ("o", "t")),
    "tidy_up": ("tidy the room in general, no particular object", ()),
}

SCHEMA = {
    "type": "object",
    "properties": {"phrasings": {"type": "array", "items": {"type": "string"}}},
    "required": ["phrasings"],
}


def prompt(goal: str, n: int) -> str:
    meaning, slots = GOAL_INFO[goal]
    uses = {
        ("o",): "Use {o} exactly once for the object.",
        ("t",): "Use {t} exactly once for the place.",
        (
            "o",
            "t",
        ): "Use {o} exactly once for the object and {t} exactly once for the place.",
        (): "Do not mention any particular object or place, and use no braces.",
    }[slots]
    return (
        f"Write {n} different ways a person might ask a home robot to {meaning}. "
        f"{uses} Make them varied and realistic: casual, slangy, indirect, polite or blunt, "
        "some with a typo or an extra clause, as people really talk. Lower case. "
        'Answer as JSON: {"phrasings": [...]}.'
    )


def ask(goal: str, n: int, model: str, url: str, seed: int) -> List[str]:
    body = {
        "model": model,
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": 0.8, "seed": seed, "num_ctx": 4096},
        "messages": [{"role": "user", "content": prompt(goal, n)}],
    }
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        reply = json.loads(resp.read().decode())
    try:
        out = json.loads(reply["message"]["content"]).get("phrasings") or []
    except (KeyError, json.JSONDecodeError, AttributeError):
        return []
    return [str(p) for p in out]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9{} ']", " ", text.lower())).strip()


def valid(goal: str, template: str) -> bool:
    slots = GOAL_INFO[goal][1]
    t = norm(template)
    words = t.split()
    if not 2 <= len(words) <= 25:
        return False
    if re.findall(r"\{[^}]*\}", t) != [] and set(re.findall(r"\{([^}]*)\}", t)) - {
        "o",
        "t",
    }:
        return False
    if t.count("{") != len(slots) or t.count("}") != len(slots):
        return False
    if not all(t.count("{" + s + "}") == 1 for s in slots):
        return False
    # A slot used as a verb ("i need you to {o} something", "{o} this to me") fills in as
    # nonsense ("to mug something") with labels that don't match it.
    for i, w in enumerate(words[:-1]):
        if w in ("{o}", "{t}") and words[i + 1] in _AFTER_A_VERB:
            return False
    return True


#: Words that follow a verb, not a noun: a slot followed by one is being used as a verb.
_AFTER_A_VERB = {"something", "this", "that", "it", "me", "them", "the", "a", "an", "my",
                 "your", "some", "those", "these", "him", "her", "us"}  # fmt: skip


def _held_out(template: str) -> bool:
    return int(hashlib.sha256(template.encode()).hexdigest(), 16) % 10 < 3


def collect(model: str, url: str, per_goal: int, seed: int = 0) -> Dict[str, Any]:
    known = {norm(t) for d in (TRAIN, TEST) for ts in d.values() for t in ts}
    accepted: Dict[str, List[str]] = {}
    stats: Dict[str, Dict[str, int]] = {}
    for gi, goal in enumerate(GOALS):
        raw = ask(goal, per_goal, model, url, seed + gi)
        seen: set = set()
        keep = []
        for r in raw:
            t = norm(r)
            if valid(goal, t) and t not in known and t not in seen:
                seen.add(t)
                keep.append(t)
        accepted[goal] = keep
        stats[goal] = {"asked": per_goal, "returned": len(raw), "accepted": len(keep)}
    split = {
        "train": {g: [t for t in ts if not _held_out(t)] for g, ts in accepted.items()},
        "held_out": {g: [t for t in ts if _held_out(t)] for g, ts in accepted.items()},
    }
    return {
        "source": f"{model} via Ollama, temperature 0.8, seed {seed}",
        "per_goal": per_goal,
        "stats": stats,
        **split,
    }


def _fill(
    templates: Dict[str, List[str]], split: str, n: int, seed: int
) -> List[Example]:
    """`generate()`'s filling and noise, over the given templates (goals without any are
    skipped)."""
    import learning.parser.data as data

    usable = {g: ts for g, ts in templates.items() if ts}
    saved_train, saved_test, saved_goals = data.TRAIN, data.TEST, data.GOALS
    try:
        if split == "test":
            data.TEST = usable
        else:
            data.TRAIN = usable
        data.GOALS = list(usable)
        return generate(split, n, seed)
    finally:
        data.TRAIN, data.TEST, data.GOALS = saved_train, saved_test, saved_goals


def evaluate(phrasings: Dict[str, Any], n_train: int = 6000, n_test: int = 1500,
             seed: int = 0) -> Dict[str, Any]:  # fmt: skip
    from language.interpreter import InstructionInterpreter
    from learning.parser.eval_parser import gold, learned_triple, rules_triple, score
    from learning.parser.model import SmallParser

    base_train = generate("train", n_train, seed)
    extra = _fill(phrasings["train"], "train", n_train // 2, seed + 7)
    tests = {
        "hand_written_test_phrasings": generate("test", n_test, seed),
        "model_held_out_phrasings": _fill(
            phrasings["held_out"], "test", n_test, seed + 3
        ),
    }
    before = SmallParser().fit(base_train)
    after = SmallParser().fit(base_train + extra)
    rules = InstructionInterpreter()
    out: Dict[str, Any] = {"n_train_before": len(base_train),
                           "n_train_after": len(base_train) + len(extra)}  # fmt: skip
    for name, test in tests.items():
        golds = [gold(e) for e in test]
        texts = [e.text for e in test]
        out[name] = {
            "n": len(test),
            "rules": score([rules_triple(rules, t) for t in texts], golds),
            "learned_before": score(
                [learned_triple(before.parse(t)) for t in texts], golds
            ),
            "learned_after": score(
                [learned_triple(after.parse(t)) for t in texts], golds
            ),
        }
    return out


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--model", default=os.environ.get("MILO_OLLAMA_MODEL", "qwen2.5:7b"))
    p.add_argument(
        "--url", default=os.environ.get("MILO_OLLAMA_URL", "http://localhost:11434")
    )
    p.add_argument("--per-goal", type=int, default=25)
    p.add_argument(
        "--phrasings", type=Path, default=REPO / "data" / "parser_llm_phrasings.json"
    )
    p.add_argument(
        "--out", type=Path, default=REPO / "results" / "parser_llm" / "eval.json"
    )
    a = p.parse_args(argv)
    if a.phrasings.exists():  # resumable: reuse what was generated
        phrasings = json.loads(a.phrasings.read_text())
        # re-apply the current checks, so a tightened check needs no new generation
        for part in ("train", "held_out"):
            phrasings[part] = {g: [t for t in ts if valid(g, t)]
                               for g, ts in phrasings[part].items()}  # fmt: skip
        for g in phrasings["stats"]:
            phrasings["stats"][g]["accepted"] = len(
                phrasings["train"].get(g, [])
            ) + len(phrasings["held_out"].get(g, []))
        a.phrasings.write_text(json.dumps(phrasings, indent=1))
    else:
        phrasings = collect(a.model, a.url, a.per_goal)
        a.phrasings.parent.mkdir(parents=True, exist_ok=True)
        a.phrasings.write_text(json.dumps(phrasings, indent=1))
    report = {"phrasings_source": phrasings["source"], "stats": phrasings["stats"],
              **evaluate(phrasings)}  # fmt: skip
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    random.seed(0)
    main()
