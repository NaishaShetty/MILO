"""
reranker.py (backend/learning/retrieval)

A lightweight learned reranker over the embedder's top candidates. One feature
function (`features`) serves training (benchmark `Mem`s) and serving
(`RetrievalReranker.rescore` on `memory.retrieval.MemoryResult`s):

    similarity, rank, kind (fact/moment/oops), confidence, age in days,
    whether the memory records a success, object match (the query names the
    memory's object, with everyday synonyms), job match (the memory is about
    the same kind of job).

Model: gradient-boosted trees (scikit-learn HistGradientBoosting) predicting
P(relevant). `rescore` returns candidates re-ordered by that probability; any
failure leaves the embedder's own order untouched.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from learning.retrieval.benchmark import SYNONYMS

logger = logging.getLogger(__name__)
KINDS = ["fact", "moment", "oops"]
_JOB_WORDS = {
    "pick_up": ["pick", "grab", "hold"],
    "fetch": ["bring", "fetch", "get me"],
    "find": ["find", "where", "look"],
    "deliver": ["take", "carry", "bring"],
    "store": ["put", "stash", "away"],
    "place": ["put", "set", "leave"],
    "open": ["open"],
    "close": ["close", "shut"],
    "turn_on": ["turn on", "on"],
    "turn_off": ["turn off", "off"],
}


def names_of(obj: str) -> List[str]:
    return [obj] + SYNONYMS.get(obj, []) + [k for k, v in SYNONYMS.items() if obj in v]


def object_match(query: str, obj: str) -> float:
    q = query.lower()
    return float(any(n in q for n in names_of(obj.lower())))


def job_match(query: str, goal: str) -> float:
    q = query.lower()
    return float(
        bool(goal)
        and (
            goal.replace("_", " ") in q or any(w in q for w in _JOB_WORDS.get(goal, []))
        )
    )


def features(
    sim: float,
    rank: int,
    kind: str,
    confidence: float,
    age_days: float,
    success: bool,
    obj_match: float,
    goal_match: float,
) -> List[float]:
    return [
        sim,
        float(rank),
        *[1.0 if kind == k else 0.0 for k in KINDS],
        confidence,
        age_days,
        float(success),
        obj_match,
        goal_match,
    ]


def from_mem(query: str, sim: float, rank: int, m: Any) -> List[float]:
    return features(
        sim,
        rank,
        m.kind,
        m.confidence,
        m.age_days,
        m.outcome in ("success", "succeeded"),
        object_match(query, m.obj),
        job_match(query, m.goal),
    )


class RetrievalReranker:
    def __init__(self, model: HistGradientBoostingClassifier) -> None:
        self._model = model

    @classmethod
    def fit(
        cls, rows: Sequence[List[float]], labels: Sequence[int]
    ) -> "RetrievalReranker":
        return cls(
            HistGradientBoostingClassifier(max_iter=150, random_state=0).fit(
                np.array(rows), np.array(labels)
            )
        )

    def score(self, rows: Sequence[List[float]]) -> np.ndarray:
        return self._model.predict_proba(np.array(rows))[:, 1]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(self._model))

    @classmethod
    def load(cls, path: Path) -> Optional["RetrievalReranker"]:
        try:
            return cls(pickle.loads(Path(path).read_bytes()))
        except Exception:
            logger.warning("retrieval_reranker.load_failed", exc_info=True)
            return None

    def rescore(self, query: str, results: List[Any]) -> List[Any]:
        """Re-order production `MemoryResult`s (never raises; failure = unchanged order)."""
        try:
            import time as _t

            now = _t.time()
            rows = []
            for rank, r in enumerate(results):
                memory = r.memory
                meta = memory.metadata if isinstance(memory.metadata, dict) else {}
                subject = str(meta.get("subject") or "")
                text = memory.content.lower()
                kind = (
                    "fact"
                    if "subject" in meta
                    else ("oops" if memory.memory_type.value == "failure" else "moment")
                )
                obj = subject or next(
                    (w.strip() for w in text.split("objects:")[-1].split(",")), ""
                )
                rows.append(
                    features(
                        r.similarity,
                        rank,
                        kind,
                        memory.confidence,
                        (now - memory.created_at) / 86400.0,
                        "outcome: success" in text,
                        object_match(query, obj),
                        1.0,
                    )
                )
            order = np.argsort(-self.score(rows), kind="stable")
            ranked = [results[i] for i in order]
            for new_rank, r in enumerate(ranked):
                r.retrieval_metadata["rank"] = new_rank
                r.retrieval_metadata["reranked"] = True
            return ranked
        except Exception:
            logger.warning("retrieval_reranker.rescore_failed", exc_info=True)
            return results


_ = Dict
