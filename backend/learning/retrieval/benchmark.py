"""
benchmark.py (backend/learning/retrieval)

A memory-retrieval benchmark built from the Phase A episode logs, using
MILO's real memory builders and canonical text (`memory.representation`) so
the embedded strings are exactly what production embeds.

From the episodes of one split it creates a de-duplicated corpus of memories:
  - *facts*     "apple stored_in fridge" (from missions that put things away),
  - *moments*   "Task: store | Outcome: success | Location: fridge | Objects: apple, fridge",
  - *oops*      "Task: pickup | Failure: not reachable ..." (from failed steps).
and natural-language queries (varied phrasings, everyday synonyms such as
tap/faucet or fridge/refrigerator) with their relevant memories:
  - a fact is relevant to a query about the same object,
  - a moment/oops is relevant when it is about the same object AND the same kind of job.

Splits follow Phase A (whole held-out SCENES for test). On top of that a few
object classes (`HELD_OUT_OBJECTS`) never appear in train/val corpora or
queries, so test measures generalisation to objects the model never saw.
"""

from __future__ import annotations

import random
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from learning.build_dataset import assign_splits
from memory.agent import MemoryQueryContext
from memory.models import MemoryProvenance
from memory.representation import canonical_text
from memory.semantics import (
    EpisodicDetails,
    FailureDetails,
    build_episodic_memory,
    build_failure_memory,
    build_semantic_memory,
)

HELD_OUT_OBJECTS = {"plate", "tomato", "bottle"}
#: Everyday words people use for the objects MILO stores under one name.
SYNONYMS = {
    "refrigerator": ["fridge", "icebox"],
    "fridge": ["refrigerator"],
    "faucet": ["tap"],
    "toaster": ["bread toaster"],
    "television": ["tv", "telly"],
    "countertop": ["counter", "worktop"],
    "mug": ["coffee mug"],
    "cup": ["glass"],
    "lightswitch": ["light", "light switch"],
    "sofa": ["couch"],
    "desk": ["work desk"],
    "apple": ["green apple"],
}
_QUERY_TEMPLATES = {
    "pick_up": [
        "pick up the {o}",
        "grab the {o}",
        "could you get hold of the {o}",
        "I need the {o} in my hand",
    ],
    "fetch": [
        "bring me the {o}",
        "could you fetch the {o}",
        "get me the {o}",
        "I want the {o} brought over",
    ],
    "find": [
        "find the {o}",
        "where is the {o}",
        "look for the {o}",
        "where did I leave the {o}",
    ],
    "deliver": [
        "take the {o} to the {t}",
        "carry the {o} over to the {t}",
        "bring the {o} to the {t}",
    ],
    "store": [
        "put the {o} in the {t}",
        "stash the {o} in the {t}",
        "put the {o} away in the {t}",
    ],
    "place": [
        "put the {o} on the {t}",
        "set the {o} down on the {t}",
        "leave the {o} on the {t}",
    ],
    "open": ["open the {o}", "could you open up the {o}", "get the {o} open"],
    "close": ["close the {o}", "shut the {o}"],
    "turn_on": ["turn on the {o}", "switch the {o} on"],
    "turn_off": ["turn off the {o}", "switch the {o} off"],
}
_FAILURE_WORDS = {
    "blocked": "path blocked",
    "not_visible": "object not visible",
    "not_reachable": "object not reachable",
    "wrong_object": "object not found",
    "timeout": "action timed out",
    "other": "action failed",
}


@dataclass
class Mem:
    mem_id: int
    kind: str  # fact | moment | oops
    text: str
    obj: str
    goal: str
    outcome: str = ""
    confidence: float = 0.8
    age_days: float = 0.0
    scene: str = ""


@dataclass
class Query:
    text: str
    obj: str
    goal: str
    relevant: Set[int] = field(default_factory=set)
    novel_object: bool = False


@dataclass
class Bench:
    corpus: Dict[str, List[Mem]]
    queries: Dict[str, List[Query]]


def _read(db_dir: Path):
    episodes, steps = [], []
    for shard in sorted(db_dir.glob("shard-*.db")):
        with closing(sqlite3.connect(str(shard))) as conn:
            conn.row_factory = sqlite3.Row
            episodes += [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM episodes WHERE outcome IS NOT NULL"
                )
            ]
            steps += [
                dict(r)
                for r in conn.execute(
                    "SELECT episode_id, action, target, failure_type, success FROM steps WHERE success=0"
                )
            ]
    return episodes, steps


def _objects(parsed: Dict) -> Tuple[str, Optional[str]]:
    import json

    p = json.loads(parsed) if isinstance(parsed, str) else parsed
    return (p.get("object") or p.get("target") or "").lower(), (
        p.get("target") or p.get("target_location") or None
    )


def build(
    db_dir: Path,
    seed: int = 0,
    per_split_queries: int = 600,
    test_frac: float = 0.2,
    val_frac: float = 0.15,
) -> Bench:

    episodes, failures = _read(db_dir)
    split_of = assign_splits(
        {e["episode_id"]: e["scene_id"] for e in episodes}, test_frac, val_frac, seed
    )
    first_failure: Dict[str, Dict] = {}
    for f in failures:
        first_failure.setdefault(f["episode_id"], f)
    rng = random.Random(seed)
    corpus: Dict[str, Dict[str, Mem]] = {s: {} for s in ("train", "val", "test")}
    by_split_eps: Dict[str, List[Dict]] = {s: [] for s in corpus}
    counter = 0

    def add(
        split: str,
        kind: str,
        text: str,
        obj: str,
        goal: str,
        outcome: str,
        conf: float,
        scene: str,
    ) -> None:
        nonlocal counter
        if text not in corpus[split]:
            counter += 1
            corpus[split][text] = Mem(
                counter, kind, text, obj, goal, outcome, conf, rng.uniform(0, 60), scene
            )

    for e in episodes:
        split = split_of[e["episode_id"]]
        obj, target = _objects(e["parsed_task"])
        goal = (e["task_kind"] or "").lower()
        if not obj or (split != "test" and obj in HELD_OUT_OBJECTS):
            continue
        by_split_eps[split].append(e)
        mo = canonical_text(
            build_episodic_memory(
                EpisodicDetails(
                    task_summary=goal,
                    outcome="success" if e["outcome"] == "succeeded" else "failed",
                    location=target,
                    relevant_objects=[x for x in (obj, target) if x],
                ),
                episode_id=e["episode_id"],
                task_id=e["episode_id"],
            )
        )
        add(split, "moment", mo, obj, goal, e["outcome"], 0.7, e["scene_id"])
        if (
            e["outcome"] == "succeeded"
            and goal in ("store", "place", "put_away")
            and target
        ):
            rel = "stored_in" if goal in ("store", "put_away") else "located_on"
            add(
                split,
                "fact",
                canonical_text(
                    build_semantic_memory(
                        obj, rel, target, provenance=MemoryProvenance.OBSERVATION
                    )
                ),
                obj,
                "",
                "success",
                0.9,
                e["scene_id"],
            )
        f = first_failure.get(e["episode_id"])
        if f and f["failure_type"]:
            ft = build_failure_memory(
                FailureDetails(
                    task=goal,
                    action=f["action"],
                    failure_reason=_FAILURE_WORDS.get(
                        f["failure_type"], "action failed"
                    ),
                    cause=None,
                    recovery=None,
                    outcome="failed",
                    error_code=None,
                ),
                episode_id=e["episode_id"],
                task_id=e["episode_id"],
            )
            add(
                split,
                "oops",
                canonical_text(ft) + f" | Object: {obj}",
                obj,
                goal,
                "failed",
                0.6,
                e["scene_id"],
            )

    queries: Dict[str, List[Query]] = {}
    for split, eps in by_split_eps.items():
        mems = list(corpus[split].values())
        rng.shuffle(eps)
        out: List[Query] = []
        for e in eps:
            if len(out) >= per_split_queries:
                break
            obj, target = _objects(e["parsed_task"])
            goal = (e["task_kind"] or "").lower()
            if goal not in _QUERY_TEMPLATES:
                continue
            word = (
                obj
                if rng.random() < 0.5 or obj not in SYNONYMS
                else rng.choice(SYNONYMS[obj])
            )
            t_word = target or "table"
            text = rng.choice(_QUERY_TEMPLATES[goal]).format(o=word, t=t_word)
            context_text = MemoryQueryContext(
                goal=text, object=word, target=target
            ).to_query_text()
            relevant = {
                m.mem_id
                for m in mems
                if m.obj == obj and (m.kind == "fact" or m.goal == goal)
            }
            if relevant:
                out.append(
                    Query(context_text, obj, goal, relevant, obj in HELD_OUT_OBJECTS)
                )
        queries[split] = out
    return Bench({s: list(c.values()) for s, c in corpus.items()}, queries)


def metrics(
    ranked: List[List[int]], queries: List[Query], ks=(1, 5, 10)
) -> Dict[str, float]:
    """recall@k = |top-k ∩ relevant| / min(|relevant|, k); MRR of the first relevant hit."""
    out: Dict[str, float] = {f"recall@{k}": 0.0 for k in ks}
    mrr = 0.0
    for order, q in zip(ranked, queries):
        for k in ks:
            out[f"recall@{k}"] += len(set(order[:k]) & q.relevant) / min(
                len(q.relevant), k
            )
        for i, mid in enumerate(order, 1):
            if mid in q.relevant:
                mrr += 1.0 / i
                break
    n = max(len(queries), 1)
    return {
        **{k: v / n for k, v in out.items()},
        "mrr": mrr / n,
        "queries": len(queries),
    }
