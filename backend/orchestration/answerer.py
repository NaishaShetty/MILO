"""
answerer.py (backend/orchestration)

Purpose
-------
Answers plain questions MILO can settle by *looking* -- "is the fridge
open?", "where is the mug?", "what are you holding?", "what can you see?"
-- from the simulator's current metadata, falling back to what MILO
remembers, without moving or touching anything. Also used after a "find"
mission to say where the thing was found.

Every answer is a short, friendly sentence. When MILO cannot tell, it says
so and what it would need ("I can't see a mug right now"), never a guess.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from execution.resolver import ObjectResolver
from language.interpreter import Question

MetadataProvider = Callable[[], Dict[str, Any]]
#: `object name -> (place, relation)` from memory; see `memory.habits`.
Recall = Callable[[str], Optional[Tuple[str, str]]]

_resolver = ObjectResolver()


def _label(obj: Dict[str, Any]) -> str:
    name = str(obj.get("objectType") or "thing")
    # "CounterTop" -> "counter top" -> "countertop" reads fine either way;
    # split camel case so "DiningTable" -> "dining table".
    out = ""
    for i, ch in enumerate(name):
        if i and ch.isupper() and not name[i - 1].isupper():
            out += " "
        out += ch
    return out.lower()


def _nearest(name: str, metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    object_id = _resolver.resolve(name, metadata)
    if object_id is None or "@" in object_id:
        return None
    return next(
        (o for o in metadata.get("objects") or [] if o.get("objectId") == object_id),
        None,
    )


def where_is(name: str, metadata: Dict[str, Any]) -> Optional[str]:
    """`"on the countertop"` / `"in the fridge"` for the nearest `name`, or
    None if it is not in the scene or its resting place is unknown."""
    parts = where_parts(name, metadata)
    return None if parts is None else f"{parts[0]} the {parts[1]}"


def where_parts(name: str, metadata: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """`("on", "countertop")` / `("in", "fridge")` -- what the nearest
    `name` rests on or in, or None."""
    obj = _nearest(name, metadata)
    if obj is None:
        return None
    objects = {o.get("objectId"): o for o in metadata.get("objects") or []}
    parents = obj.get("parentReceptacles") or (
        [obj["parentReceptacle"]] if obj.get("parentReceptacle") else []
    )
    for parent_id in parents:
        parent = objects.get(parent_id)
        if parent is None:
            continue
        preposition = "in" if parent.get("openable") else "on"
        return preposition, _label(parent)
    return None


class QuestionAnswerer:
    def __init__(self, metadata: MetadataProvider, recall: Optional[Recall] = None):
        self._metadata = metadata
        self._recall = recall

    def answer(self, question: Question) -> str:
        meta = self._metadata() or {}
        kind = question.kind
        if kind in ("is_open", "is_on"):
            return self._state(question, meta)
        if kind == "where":
            return self._where(question.subject or "that", meta)
        if kind == "holding":
            held = meta.get("inventoryObjects") or []
            if not held:
                return "My hands are empty."
            names = [
                (
                    _label(h)
                    if h.get("objectType")
                    else str(h.get("objectId", "")).split("|")[0].lower()
                )
                for h in held
            ]
            return "I'm holding the " + " and the ".join(names) + "."
        if kind == "see":
            seen: List[str] = []
            for obj in meta.get("objects") or []:
                if obj.get("visible"):
                    label = _label(obj)
                    if label not in seen:
                        seen.append(label)
            if not seen:
                return "I can't see anything in particular right now."
            shown = seen[:8]
            more = f", and {len(seen) - 8} more things" if len(seen) > 8 else ""
            return "I can see " + ", ".join(shown) + more + "."
        return "I'm not sure how to answer that one."

    def _state(self, q: Question, meta: Dict[str, Any]) -> str:
        subject = q.subject or "that"
        obj = _nearest(subject, meta)
        if obj is None:
            return f"I can't see a {subject} right now, so I can't tell."
        if q.kind == "is_open":
            value, word, opposite = obj.get("isOpen"), "open", "closed"
            if value is None:
                return f"The {subject} can't be opened or closed."
        else:
            value, word, opposite = obj.get("isToggled"), "on", "off"
            if value is None:
                return f"The {subject} doesn't have an on/off switch."
        actual = word if value else opposite
        asked = word if q.expected else opposite
        yes = "Yes" if actual == asked else "No"
        return f"{yes}, the {subject} is {actual}."

    def _where(self, subject: str, meta: Dict[str, Any]) -> str:
        place = where_is(subject, meta)
        if place is not None:
            return f"The {subject} is {place}."
        if _nearest(subject, meta) is not None:
            return f"I can see the {subject}, but I'm not sure what it's resting on."
        if self._recall is not None:
            known = self._recall(subject)
            if known is not None:
                where, relation = known
                prep = "in" if relation == "stored_in" else "on"
                return (
                    f"I can't see a {subject} right now, but I remember it "
                    f"usually being {prep} the {where}."
                )
        return f"I can't see a {subject} right now, and I haven't seen one before."
