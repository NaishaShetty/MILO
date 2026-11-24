"""
model.py (backend/learning/parser)

A very small instruction parser: an intent classifier (TF-IDF word+char n-grams ->
logistic regression) plus a token tagger (OBJ / TGT / O; logistic regression over
word-shape and neighbouring-word features, so words never seen in training are still
tagged from their context). CPU only, trains in seconds, about a millisecond to run.

`parse(text)` returns `Parsed(goal, object, target, confidence)`; `confidence` is the
lowest of the intent probability and the slot probabilities the goal needs, so the
caller can fall back to the rules/LLM when it is unsure.
"""

from __future__ import annotations

import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion

from learning.parser.data import Example

NEEDS_OBJ = {
    "fetch",
    "deliver",
    "store",
    "place",
    "pick_up",
    "open",
    "close",
    "turn_on",
    "turn_off",
    "find",
    "clear_table",
}
NEEDS_TGT = {"deliver", "store", "place", "navigate_to", "clear_table"}
_STOP = {"the", "a", "an", "my", "to", "in", "on", "into", "onto", "inside", "of"}
_PREPS = ("to", "in", "on", "into", "onto", "inside", "at")


@dataclass
class Parsed:
    goal: str
    object: Optional[str]
    target: Optional[str]
    confidence: float


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _tok_features(tokens: List[str], i: int) -> Dict[str, Any]:
    w = tokens[i]
    f: Dict[str, Any] = {
        "bias": 1,
        "w": w,
        "suf2": w[-2:],
        "suf3": w[-3:],
        "stop": w in _STOP,
        "pos": min(i, 6),
        "rpos": min(len(tokens) - 1 - i, 6),
    }
    for off in (-3, -2, -1, 1, 2):
        j = i + off
        f[f"w{off}"] = tokens[j] if 0 <= j < len(tokens) else "<pad>"
    f["p-1+w"] = (tokens[i - 1] if i else "<s>") + "_" + w
    for k in range(i - 1, -1, -1):  # nearest preposition on the left: thing vs place
        if tokens[k] in _PREPS:
            f["prep"] = tokens[k]
            break
    f["after_det"] = i > 0 and tokens[i - 1] in ("the", "a", "an", "my")
    return f


def _labels(ex: Example, tokens: List[str]) -> List[str]:
    out = ["O"] * len(tokens)
    for slot, label in ((ex.object, "OBJ"), (ex.target, "TGT")):
        if slot and slot in tokens:
            out[tokens.index(slot)] = label
    return out


class SmallParser:
    def __init__(self) -> None:
        self._intent_vec: Any = None
        self._intent: Any = None
        self._tag_vec: Any = None
        self._tag: Any = None
        self.goals: List[str] = []

    def fit(self, examples: Sequence[Example]) -> "SmallParser":
        self._intent_vec = FeatureUnion(
            [
                ("w", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
                (
                    "c",
                    TfidfVectorizer(
                        analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True
                    ),
                ),
            ]
        )
        x = self._intent_vec.fit_transform([e.text for e in examples])
        self._intent = LogisticRegression(max_iter=2000, C=10.0).fit(
            x, [e.goal for e in examples]
        )
        self.goals = list(self._intent.classes_)
        feats: List[Dict[str, Any]] = []
        labels: List[str] = []
        for e in examples:
            toks = tokenize(e.text)
            labels += _labels(e, toks)
            feats += [_tok_features(toks, i) for i in range(len(toks))]
        self._tag_vec = DictVectorizer()
        self._tag = LogisticRegression(max_iter=3000, C=5.0).fit(
            self._tag_vec.fit_transform(feats), labels
        )
        return self

    def parse(self, text: str) -> Parsed:
        toks = tokenize(text)
        probs = self._intent.predict_proba(self._intent_vec.transform([text]))[0]
        k = int(np.argmax(probs))
        goal, conf = str(self.goals[k]), float(probs[k])
        obj: Optional[str] = None
        tgt: Optional[str] = None
        if toks:
            tp = self._tag.predict_proba(
                self._tag_vec.transform(
                    [_tok_features(toks, i) for i in range(len(toks))]
                )
            )
            cls = list(self._tag.classes_)
            for label, need in (
                ("OBJ", goal in NEEDS_OBJ),
                ("TGT", goal in NEEDS_TGT),
            ):
                if not need or label not in cls:
                    continue
                col = tp[:, cls.index(label)]
                j = int(np.argmax(col))
                conf = min(conf, float(col[j]))
                if label == "OBJ":
                    obj = toks[j]
                else:
                    tgt = toks[j]
        return Parsed(goal, obj, tgt, conf)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            pickle.dumps(
                (self._intent_vec, self._intent, self._tag_vec, self._tag, self.goals)
            )
        )

    @classmethod
    def load(cls, path: Path) -> Optional["SmallParser"]:
        try:
            m = cls()
            m._intent_vec, m._intent, m._tag_vec, m._tag, m.goals = pickle.loads(
                Path(path).read_bytes()
            )
            return m
        except Exception:
            return None
