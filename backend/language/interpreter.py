"""
interpreter.py (backend/language)

Purpose
-------
Turns the way people actually talk ("could you grab me the mug", "take the
book to the desk", "is the fridge open?") into something MILO can act on --
or, when it can't, into a clear question or reason instead of a silent
failure.

It sits *in front of* the LLM-backed `LanguageAgent`: a small,
deterministic, offline phrasebook handles the everyday requests the task
library covers (fast, free, testable without a network), and anything it
does not recognise is handed to an optional `fallback` parser (the LLM) --
so rich or unusual sentences still work when a model is configured, and
the common ones keep working when it is not.

`interpret()` returns an `Interpretation` whose `kind` is exactly one of:

- `"task"`        -- a `SingleTask` / `MultiTask` to run;
- `"question"`    -- something MILO can answer without moving
                     (`is the fridge open?`, `where is the mug?`);
- `"preference"`  -- "the mug goes on the shelf": remember it, don't act;
- `"help"`        -- "what can you do?";
- `"clarify"`     -- understood the verb, missing a detail: `message` is the
                     question to ask the user;
- `"unsupported"` -- understood the request, MILO can't do it (yet):
                     `message` says so, plainly, and what it *can* do.

Every non-`"task"` outcome carries a user-facing `message` written to be
shown as-is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple, Union

from planner.task_library import capabilities_sentence
from schemas.task import MultiTask, SingleTask, TaskAttributes

Interpreted = Union[SingleTask, MultiTask]

# -- vocabulary ---------------------------------------------------------

_POLITE_PREFIXES = (
    "hey milo",
    "hi milo",
    "ok milo",
    "milo",
    "please",
    "could you please",
    "can you please",
    "would you please",
    "will you please",
    "could you",
    "can you",
    "would you",
    "will you",
    "i would like you to",
    "i'd like you to",
    "i want you to",
    "i need you to",
    "i need",
    "i want",
    "go ahead and",
    "go and",
    "go",
    "just",
)
_POLITE_SUFFIXES = ("please", "for me", "thanks", "thank you", "now")

_DETERMINERS = r"(?:the|a|an|my|our|that|this|those|these|some|one of the)"
_COLORS = {
    "red",
    "green",
    "blue",
    "yellow",
    "white",
    "black",
    "brown",
    "orange",
    "pink",
    "purple",
    "grey",
    "gray",
    "silver",
    "gold",
}
_SIZES = {"small", "large", "big", "tiny", "little"}
_VAGUE = {
    "it",
    "that",
    "this",
    "them",
    "those",
    "these",
    "something",
    "stuff",
    "things",
    "thing",
    "one",
}

_CONTAINER_PREPS = ("in", "into", "inside", "inside of")
_SURFACE_PREPS = ("on", "onto", "on top of", "at", "next to", "near", "by")
_ALL_PREPS = _CONTAINER_PREPS + _SURFACE_PREPS

_SURFACES = {"table", "counter", "countertop", "desk", "worktop", "bench", "island"}

_QUESTION_STATES = {
    "open": ("is_open", True),
    "closed": ("is_open", False),
    "shut": ("is_open", False),
    "on": ("is_on", True),
    "off": ("is_on", False),
}


@dataclass
class Question:
    """A question MILO answers from what it can see/remember, without acting."""

    kind: str  # "is_open" | "is_on" | "where" | "holding" | "see"
    subject: Optional[str] = None
    expected: Optional[bool] = None  # for is_open / is_on: what was asked about
    text: str = ""


@dataclass
class Preference:
    """ "The mug goes on the shelf" -- a usual place to remember."""

    object: str
    place: str
    relation: str  # "stored_in" (inside) | "located_on" (on/at)


@dataclass
class Interpretation:
    kind: str
    task: Optional[Interpreted] = None
    question: Optional[Question] = None
    preference: Optional[Preference] = None
    #: User-facing text: the clarifying question, the reason MILO can't do
    #: it, the help text.
    message: str = ""
    #: Short echo of how MILO understood the request ("Fetch the mug").
    understood_as: str = ""
    #: Which part of the system understood it: "rules", "learned" or "model".
    source: str = "rules"
    details: dict = field(default_factory=dict)


FallbackParser = Callable[[str], Optional[Interpreted]]
UsualPlace = Callable[[str], Optional[Tuple[str, str]]]


# -- helpers ----------------------------------------------------------------


def _clean(text: str) -> str:
    t = text.strip().lower()
    t = t.replace("’", "'")
    t = re.sub(r"[!.?]+$", "", t).strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _strip_politeness(t: str) -> str:
    changed = True
    while changed:
        changed = False
        for prefix in _POLITE_PREFIXES:
            if prefix == "go" and t.startswith("go to "):
                continue  # "go to the fridge" is a request, not politeness
            if t == prefix:
                return ""
            if t.startswith(prefix + " ") or t.startswith(prefix + ","):
                t = t[len(prefix) :].lstrip(" ,")
                changed = True
        for suffix in _POLITE_SUFFIXES:
            if t.endswith(" " + suffix):
                t = t[: -len(suffix)].rstrip(" ,")
                changed = True
    return t


def _noun(phrase: str) -> Tuple[Optional[str], Optional[TaskAttributes]]:
    """`"the red mug"` -> (`"mug"`, attributes(color="red")). None for
    vague words ("it", "something")."""
    phrase = re.sub(r"\s+(?:to|in|into|on|onto|inside|at)$", "", phrase.strip())
    words = re.sub(rf"^{_DETERMINERS}\s+", "", phrase).split()
    color = next((w for w in words if w in _COLORS), None)
    size = next((w for w in words if w in _SIZES), None)
    words = [w for w in words if w not in _COLORS and w not in _SIZES]
    name = " ".join(words).strip(" ,")
    if not name or name in _VAGUE:
        return None, None
    attributes = None
    if color or size:
        attributes = TaskAttributes(color=color, size=size)
    return name, attributes


def _make(goal: str, **fields) -> SingleTask:
    attributes = fields.pop("attributes", None)
    task = SingleTask(goal=goal, attributes=attributes, **fields)
    return task


def _echo(task: Interpreted) -> str:
    if isinstance(task, MultiTask):
        return "; then ".join(_echo(s) for s in task.subtasks)
    verb = {
        "fetch": "Fetch the {o}",
        "deliver": "Take the {o} to the {t}",
        "store": "Put the {o} in the {t}",
        "place": "Put the {o} on the {t}",
        "pick_up": "Pick up the {o}",
        "open": "Open the {o}",
        "close": "Close the {o}",
        "turn_on": "Turn on the {o}",
        "turn_off": "Turn off the {o}",
        "find": "Find the {o}",
        "clear_table": "Clear the {s}",
        "tidy_up": "Tidy up",
        "put_away": "Put the {o} away",
        "navigate_to": "Go to the {t}",
    }.get(task.goal or "", (task.goal or "do something").replace("_", " "))
    return verb.format(
        o=task.object or task.target or "thing",
        t=task.target or task.target_location or "place",
        s=task.source_location or "table",
    )


# -- the interpreter ------------------------------------------------------------


class InstructionInterpreter:
    """
    `interpret(text)` -> `Interpretation`. See the module docstring.

    Args:
        fallback: optional parser for sentences the phrasebook does not
            recognise (typically `LanguageAgent.parse`); exceptions it
            raises propagate to the caller, which owns error mapping.
        usual_place: optional `object -> (place, relation)` lookup of where
            MILO remembers that object usually lives ("put it away").
    """

    def __init__(
        self,
        fallback: Optional[FallbackParser] = None,
        usual_place: Optional[UsualPlace] = None,
        learned: Optional[Callable[[str], Optional[SingleTask]]] = None,
    ) -> None:
        #: Optional small learned parser (`learning.parser`), tried after help/question/
        #: preference/chain and before the single-task phrasebook; it only answers when
        #: confident, otherwise the phrasebook and the LLM run exactly as before.
        self._learned = learned
        self._fallback = fallback
        self._usual_place = usual_place

    # public ----------------------------------------------------------------

    def interpret(self, text: str) -> Interpretation:
        raw = text
        t = _strip_politeness(_clean(text))
        if not t:
            return Interpretation(
                kind="clarify",
                message="I didn't catch that. What would you like me to do?",
            )

        for step in (
            self._help,
            self._question,
            self._preference,
            self._chain,
            self._learned_task,
            self._single,
        ):
            result = step(t) if step != self._learned_task else step(raw)
            if result is not None:
                return result

        # Not in the phrasebook: let the model try, if there is one.
        if self._fallback is not None:
            parsed = self._fallback(raw)
            if parsed is not None:
                if getattr(parsed, "needs_clarification", False):
                    return Interpretation(
                        kind="clarify",
                        message=(
                            getattr(parsed, "clarification_reason", None)
                            or "Could you say that another way?"
                        ),
                        source="model",
                    )
                return Interpretation(
                    kind="task",
                    task=parsed,
                    understood_as=_echo(parsed),
                    source="model",
                )
        return self._unsupported(t)

    # steps -------------------------------------------------------------------

    def _learned_task(self, t: str) -> Optional[Interpretation]:
        if self._learned is None:
            return None
        task = self._learned(t)
        if task is None:
            return None
        return Interpretation(
            kind="task", task=task, understood_as=_echo(task), source="learned"
        )

    def _help(self, t: str) -> Optional[Interpretation]:
        if re.fullmatch(
            r"(what can you do|what do you do|help|what are you able to do|what can i ask you(?: to do)?)\??",
            t,
        ):
            return Interpretation(kind="help", message=capabilities_sentence())
        return None

    def _question(self, t: str) -> Optional[Interpretation]:
        m = re.fullmatch(
            rf"(?:is|are) (?:{_DETERMINERS} )?(.+?) (open|closed|shut|on|off)\??", t
        )
        if m:
            subject, _ = _noun(m.group(1))
            state, expected = _QUESTION_STATES[m.group(2)]
            if subject is None:
                return Interpretation(kind="clarify", message="Which one do you mean?")
            return Interpretation(
                kind="question",
                question=Question(state, subject, expected, text=t),
                understood_as=f"Is the {subject} {m.group(2)}?",
            )
        m = re.fullmatch(
            r"(?:where(?:'s| is| are)|where did you (?:put|leave)) (.+?)\??", t
        )
        if m:
            subject, _ = _noun(m.group(1))
            if subject is None:
                return Interpretation(
                    kind="clarify", message="Where is what? Tell me which thing."
                )
            return Interpretation(
                kind="question",
                question=Question("where", subject, text=t),
                understood_as=f"Where is the {subject}?",
            )
        if re.fullmatch(
            r"(?:what (?:are|do) you (?:holding|carrying|have)|are you holding (?:anything|something)|what is in your hand)\??",
            t,
        ):
            return Interpretation(
                kind="question",
                question=Question("holding", text=t),
                understood_as="What am I holding?",
            )
        if re.fullmatch(
            r"(?:what (?:can|do) you see|what(?:'s| is) (?:around|in front of you)|what are you looking at)\??",
            t,
        ):
            return Interpretation(
                kind="question",
                question=Question("see", text=t),
                understood_as="What can I see?",
            )
        return None

    def _preference(self, t: str) -> Optional[Interpretation]:
        t2 = re.sub(r"^(?:remember(?: that)?|note that) ", "", t)
        m = re.fullmatch(
            rf"(?:{_DETERMINERS} )?(.+?) (?:goes|belongs|lives|should go|should be|is supposed to go|is kept|should live) "
            rf"(in|into|inside|on|onto|at|on top of)(?: {_DETERMINERS})? (.+)",
            t2,
        )
        if not m:
            m = re.fullmatch(
                rf"i (?:always )?(?:keep|put|store) (?:{_DETERMINERS} )?(.+?) "
                rf"(in|inside|on|at)(?: {_DETERMINERS})? (.+)",
                t2,
            )
            if m:
                groups = (m.group(1), m.group(2), m.group(3))
            else:
                return None
        else:
            groups = (m.group(1), m.group(2), m.group(3))
        obj, _ = _noun(groups[0])
        place, _ = _noun(groups[2])
        if obj is None or place is None:
            return Interpretation(
                kind="clarify", message="Which thing, and where should it live?"
            )
        relation = "stored_in" if groups[1] in _CONTAINER_PREPS else "located_on"
        return Interpretation(
            kind="preference",
            preference=Preference(obj, place, relation),
            understood_as=f"The {obj} goes {'in' if relation == 'stored_in' else 'on'} the {place}",
            message=f"Got it -- the {obj} goes {'in' if relation == 'stored_in' else 'on'} the {place}. I'll remember.",
        )

    def _chain(self, t: str) -> Optional[Interpretation]:
        parts = re.split(r"\s*(?:,? and then |, then | then |; )\s*", t)
        if len(parts) < 2:
            parts = re.split(
                r" and (?=(?:open|close|turn|switch|put|bring|take|get|grab|find|"
                r"pick|fetch|place|move|give|clear|tidy) )",
                t,
            )
        if len(parts) < 2:
            # "find the mug and the cup" -> find the mug; find the cup
            m = re.fullmatch(
                r"(find|open|close|fetch|get|grab|bring|pick up|look for) (.+?) and (?:%s )?(.+)"
                % _DETERMINERS,
                t,
            )
            if m and not re.search(r"\b(?:%s)\b" % "|".join(_ALL_PREPS + ("to",)), t):
                parts = [f"{m.group(1)} {m.group(2)}", f"{m.group(1)} {m.group(3)}"]
        if len(parts) < 2:
            # "put the apple in the fridge and the mug on the shelf"
            m = re.fullmatch(
                rf"(.+? (?:{'|'.join(_ALL_PREPS)}) .+?) and ((?:{_DETERMINERS} )?.+? (?:{'|'.join(_ALL_PREPS)}) .+)",
                t,
            )
            if m:
                verb = t.split(" ", 1)[0]
                parts = [m.group(1), f"{verb} {m.group(2)}"]
            else:
                return None
        subtasks: List[SingleTask] = []
        previous_verb = ""
        for part in parts:
            part = _strip_politeness(part.strip())
            if not part:
                continue
            found = self._single(part)
            if found is None and previous_verb:
                found = self._single(f"{previous_verb} {part}")
            if (
                found is None
                or found.kind != "task"
                or not isinstance(found.task, SingleTask)
            ):
                # One half is not understood: report *that* instead of a
                # half-run chain.
                if found is not None and found.kind in ("clarify", "unsupported"):
                    return found
                return None
            subtasks.append(found.task)
            previous_verb = part.split(" ", 1)[0]
        if len(subtasks) < 2:
            return None
        multi = MultiTask(goal="multi_step", subtasks=subtasks)
        return Interpretation(kind="task", task=multi, understood_as=_echo(multi))

    def _single(self, t: str) -> Optional[Interpretation]:
        for rule in (
            self._open_close,
            self._toggle,
            self._clear_or_tidy,
            self._find,
            self._go_to,
            self._move,
            self._fetch_or_pick,
            self._put_away,
        ):
            result = rule(t)
            if result is not None:
                return result
        return None

    # task rules ------------------------------------------------------------------

    @staticmethod
    def _task(task: SingleTask) -> Interpretation:
        return Interpretation(kind="task", task=task, understood_as=_echo(task))

    def _open_close(self, t: str) -> Optional[Interpretation]:
        m = re.fullmatch(r"(open|close|shut)(?: up)? (.+)", t)
        if not m:
            return None
        obj, attrs = _noun(m.group(2))
        verb = "open" if m.group(1) == "open" else "close"
        if obj is None:
            return Interpretation(kind="clarify", message=f"What should I {verb}?")
        return self._task(_make(verb, object=obj, attributes=attrs))

    def _toggle(self, t: str) -> Optional[Interpretation]:
        bare = re.fullmatch(r"(?:turn|switch|flick) (on|off)", t)
        if bare:
            return Interpretation(
                kind="clarify",
                message=f"What should I turn {bare.group(1)}? The lights, the tap...?",
            )
        m = re.fullmatch(r"(?:turn|switch|put|flick) (on|off) (.+)", t) or None
        if m:
            state, rest = m.group(1), m.group(2)
        else:
            m = re.fullmatch(r"(?:turn|switch|flick) (.+?) (on|off)", t)
            if not m:
                return None
            rest, state = m.group(1), m.group(2)
        obj, attrs = _noun(rest)
        goal = "turn_on" if state == "on" else "turn_off"
        if obj is None:
            return Interpretation(
                kind="clarify",
                message=f"What should I turn {state}? The lights, the tap...?",
            )
        return self._task(_make(goal, object=obj, attributes=attrs))

    def _clear_or_tidy(self, t: str) -> Optional[Interpretation]:
        if re.fullmatch(
            r"(?:tidy(?: up)?|clean up|tidy up (?:the )?(?:room|house|place|kitchen)|put (?:everything|all of it|things|stuff) (?:away|back)|put (?:everything|things|stuff) back where (?:it|they) belong[s]?)",
            t,
        ):
            return self._task(_make("tidy_up"))
        m = re.fullmatch(
            rf"(?:clear|clean off|clear off|clear out|empty|tidy)(?: up)? (?:{_DETERMINERS} )?(.+?)(?: (?:onto|into|to|in|on) (?:{_DETERMINERS} )?(.+))?",
            t,
        )
        if m:
            source, _ = _noun(m.group(1))
            dest = _noun(m.group(2))[0] if m.group(2) else None
            if source is None:
                return Interpretation(kind="clarify", message="What should I clear?")
            if dest is None:
                return Interpretation(
                    kind="clarify",
                    message=f"Where should I put the things from the {source}?",
                    details={"slot": "target", "goal": "clear_table"},
                )
            return self._task(
                _make("clear_table", source_location=source, target_location=dest)
            )
        return None

    def _go_to(self, t: str) -> Optional[Interpretation]:
        m = re.fullmatch(
            r"(?:go|walk|head|come|move|run) (?:over )?(?:to|towards|toward) (.+)", t
        )
        if not m:
            return None
        place, _ = _noun(m.group(1))
        if place is None:
            return Interpretation(kind="clarify", message="Where should I go?")
        return self._task(_make("navigate_to", target=place))

    def _find(self, t: str) -> Optional[Interpretation]:
        m = re.fullmatch(
            r"(?:find|look for|search for|locate|hunt for|look around for|see if you can find) (.+?)(?: and (?:tell|show) me where (?:it is|they are))?",
            t,
        )
        if not m:
            return None
        obj, attrs = _noun(m.group(1))
        if obj is None:
            return Interpretation(kind="clarify", message="What should I look for?")
        return self._task(_make("find", object=obj, attributes=attrs))

    def _move(self, t: str) -> Optional[Interpretation]:
        """verb OBJ prep DEST -- put/place/move/set/take/bring/carry/deliver/give."""
        dangling = re.fullmatch(
            r"(put|place|set|move|take|bring|carry|deliver|hand|give) (.+?) "
            r"(?:to|into|in|on|onto|inside|over to|back to)",
            t,
        )
        if dangling:
            obj, _ = _noun(dangling.group(2))
            if obj is None:
                return Interpretation(
                    kind="clarify", message="Which thing, and where should it go?"
                )
            return Interpretation(
                kind="clarify",
                message=f"Where should I take the {obj}?",
                details={"slot": "target", "object": obj},
            )
        preps = "|".join(
            sorted(_ALL_PREPS + ("to", "over to", "back to"), key=len, reverse=True)
        )
        m = re.fullmatch(
            rf"(put|place|set|leave|stick|move|take|bring|carry|deliver|hand|give|drop|return) (.+?) ({preps}) (?:{_DETERMINERS} )?(.+)",
            t,
        )
        if not m:
            return None
        verb, obj_text, prep, dest_text = m.groups()
        obj, attrs = _noun(obj_text)
        dest, _ = _noun(dest_text)
        if dest in ("me", "us", "myself", "the user", "user"):
            if obj is None:
                return Interpretation(
                    kind="clarify", message="What should I bring you?"
                )
            return self._task(_make("fetch", object=obj, attributes=attrs))
        if obj is None:
            return Interpretation(
                kind="clarify", message=f"Which thing should I {verb}?"
            )
        if dest is None:
            return Interpretation(
                kind="clarify", message=f"Where should I take the {obj}?"
            )
        if verb in (
            "take",
            "bring",
            "carry",
            "deliver",
            "hand",
            "give",
            "return",
        ) or prep in (
            "to",
            "over to",
            "back to",
        ):
            if verb in ("put", "place", "set", "leave", "stick", "move", "drop"):
                goal = "store" if prep in _CONTAINER_PREPS else "place"
                return self._task(
                    _make(goal, object=obj, target=dest, attributes=attrs)
                )
            return self._task(
                _make("deliver", object=obj, target=dest, attributes=attrs)
            )
        goal = "store" if prep in _CONTAINER_PREPS else "place"
        return self._task(_make(goal, object=obj, target=dest, attributes=attrs))

    def _fetch_or_pick(self, t: str) -> Optional[Interpretation]:
        m = re.fullmatch(
            r"(?:bring|get|fetch|grab|give|hand|pass|carry)(?: me| us)? (.+?)(?: (?:back|here|over)(?: to me)?)?",
            t,
        )
        if m and (
            t.startswith(("bring", "get", "fetch", "give", "hand", "pass"))
            or " me " in f" {t} "
            or t.endswith((" back", " here", " over"))
        ):
            obj, attrs = _noun(m.group(1))
            if obj is None:
                return Interpretation(
                    kind="clarify", message="What should I bring you?"
                )
            return self._task(_make("fetch", object=obj, attributes=attrs))
        m = re.fullmatch(
            r"(?:pick up|pick|grab|take|lift|collect)(?: up)? (.+?)(?: up)?", t
        )
        if m:
            obj, attrs = _noun(m.group(1))
            if obj is None:
                return Interpretation(kind="clarify", message="What should I pick up?")
            return self._task(_make("pick_up", object=obj, attributes=attrs))
        return None

    def _put_away(self, t: str) -> Optional[Interpretation]:
        m = re.fullmatch(
            rf"(?:put|tidy|stash)(?: away)? (?:{_DETERMINERS} )?(.+?)(?: (?:away|back))",
            t,
        )
        if not m:
            m = re.fullmatch(rf"put away (?:{_DETERMINERS} )?(.+)", t)
        if not m:
            return None
        obj, attrs = _noun(m.group(1))
        if obj is None:
            return Interpretation(kind="clarify", message="What should I put away?")
        if self._usual_place is not None:
            known = self._usual_place(obj)
            if known is not None:
                place, relation = known
                goal = "store" if relation == "stored_in" else "place"
                return self._task(
                    _make(goal, object=obj, target=place, attributes=attrs)
                )
        return Interpretation(
            kind="clarify",
            message=f"Where does the {obj} usually go? Tell me and I'll remember "
            f'(for example: "the {obj} goes on the shelf").',
            details={"slot": "target", "object": obj},
        )

    # fallthrough ----------------------------------------------------------------

    def _unsupported(self, t: str) -> Interpretation:
        noun, _ = _noun(t) if re.match(rf"{_DETERMINERS} ", t) else (None, None)
        if noun is not None:
            return Interpretation(
                kind="clarify",
                message=f"What should I do with the {noun}? "
                "I can fetch it, take it somewhere, put it away and more.",
            )
        verb = t.split(" ", 1)[0]
        return Interpretation(
            kind="unsupported",
            message=f'I don\'t know how to "{verb}" yet. {capabilities_sentence()}',
        )
