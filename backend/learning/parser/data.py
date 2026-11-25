"""
data.py (backend/learning/parser)

Synthetic instruction data for the small parser. Every example is
`(text, goal, object, target)` with the gold labels coming straight from the
template that produced it (NOT from the rule interpreter, so the rules can be
scored fairly).

Held-out evaluation is by *phrasing*: the test split uses paraphrase templates
that never appear in training, and a held-out set of object words. A noise
pass (typos, fillers, politeness, casing) is applied to every split.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

GOALS = [
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
    "navigate_to",
    "clear_table",
    "tidy_up",
]
OBJECTS_TRAIN = [
    "mug", "apple", "book", "bowl", "cup", "egg", "potato", "spoon", "fork", "knife",
    "pan", "pot", "remote", "keys", "phone", "towel", "newspaper", "banana", "orange",
    "glass", "laptop", "pen", "can", "box", "toy", "sponge", "teapot", "kettle",
]  # fmt: skip
OBJECTS_HELD_OUT = ["plate", "tomato", "bottle", "lettuce", "candle", "vase", "pillow"]
PLACES_TRAIN = [
    "fridge", "table", "counter", "shelf", "desk", "drawer", "cabinet", "sofa",
    "kitchen", "bedroom", "sink", "stove", "bed", "microwave",
]  # fmt: skip
PLACES_HELD_OUT = ["pantry", "dresser", "nightstand"]
TOGGLES = [
    "light",
    "lights",
    "tap",
    "faucet",
    "toaster",
    "tv",
    "television",
    "lamp",
    "fan",
]
OPENABLES = ["door", "fridge", "drawer", "cabinet", "microwave", "window", "pantry"]

# {o} object, {t} target place. Train and test phrasings are disjoint.
TRAIN: Dict[str, List[str]] = {
    "fetch": ["bring me the {o}", "get me the {o}", "fetch the {o}", "i need the {o}",
              "can you get the {o} for me", "hand me the {o}"],
    "deliver": ["take the {o} to the {t}", "bring the {o} to the {t}", "carry the {o} to the {t}",
                "deliver the {o} to the {t}", "move the {o} over to the {t}"],
    "store": ["put the {o} in the {t}", "place the {o} inside the {t}", "store the {o} in the {t}",
              "stick the {o} in the {t}"],
    "place": ["put the {o} on the {t}", "place the {o} on the {t}", "set the {o} on the {t}",
              "leave the {o} on the {t}"],
    "pick_up": ["pick up the {o}", "grab the {o}", "pick the {o} up", "lift the {o}"],
    "open": ["open the {o}", "open up the {o}", "please open the {o}"],
    "close": ["close the {o}", "shut the {o}", "close up the {o}"],
    "turn_on": ["turn on the {o}", "switch on the {o}", "turn the {o} on", "switch the {o} on"],
    "turn_off": ["turn off the {o}", "switch off the {o}", "turn the {o} off", "switch the {o} off"],
    "find": ["find the {o}", "look for the {o}", "where is the {o}", "locate the {o}"],
    "navigate_to": ["go to the {t}", "walk to the {t}", "head to the {t}"],
    "clear_table": ["clear the {o} onto the {t}", "clear off the {o} and put things on the {t}",
                    "empty the {o} into the {t}"],
    "tidy_up": ["tidy up", "clean up", "tidy up the room", "put everything away"],
}  # fmt: skip
TEST: Dict[str, List[str]] = {
    "fetch": ["could you possibly bring the {o} over to me", "i'd love the {o} brought to me",
              "go and get me the {o}", "let me have the {o}", "bring the {o} here"],
    "deliver": ["i want the {o} at the {t}", "the {o} needs to go to the {t}",
                "get the {o} over to the {t}", "run the {o} to the {t}"],
    "store": ["the {o} should go into the {t}", "tuck the {o} into the {t}",
              "pop the {o} in the {t}"],
    "place": ["the {o} belongs on the {t}", "rest the {o} on the {t}", "drop the {o} onto the {t}"],
    "pick_up": ["take hold of the {o}", "get hold of the {o}", "snatch up the {o}", "collect the {o}"],
    "open": ["can you open the {o}", "i want the {o} opened", "pull open the {o}"],
    "close": ["would you close the {o}", "make sure the {o} is closed", "push the {o} shut"],
    "turn_on": ["can you turn the {o} on", "get the {o} running", "i want the {o} on",
                "power up the {o}"],
    "turn_off": ["can you turn the {o} off", "kill the {o}", "i want the {o} off",
                 "shut off the {o}"],
    "find": ["see if you can spot the {o}", "hunt for the {o}", "i can't find the {o}",
             "tell me where the {o} is"],
    "navigate_to": ["move over to the {t}", "come to the {t}", "make your way to the {t}"],
    "clear_table": ["get everything off the {o} and onto the {t}", "clear the {o} and stack it on the {t}"],
    "tidy_up": ["make the place tidy", "sort out this mess", "straighten up the room"],
}  # fmt: skip

_FILLERS_PRE = ["", "", "", "please ", "hey milo, ", "milo ", "ok so ", "um "]
_FILLERS_POST = ["", "", "", " please", " thanks", " now", " when you can"]


@dataclass(frozen=True)
class Example:
    text: str
    goal: str
    object: Optional[str]
    target: Optional[str]


def _typo(rng: random.Random, word: str) -> str:
    if len(word) < 5:
        return word
    i = rng.randrange(1, len(word) - 1)
    return word[:i] + word[i + 1] + word[i] + word[i + 2 :]  # swap two letters


def _slots(
    goal: str, rng: random.Random, objs: List[str], places: List[str]
) -> Tuple[Optional[str], Optional[str]]:
    if goal in ("open", "close"):
        return rng.choice(OPENABLES), None
    if goal in ("turn_on", "turn_off"):
        return rng.choice(TOGGLES), None
    if goal == "navigate_to":
        return None, rng.choice(places)
    if goal == "clear_table":
        return rng.choice(["table", "counter", "desk", "sofa"]), rng.choice(places)
    if goal == "tidy_up":
        return None, None
    if goal in ("fetch", "pick_up", "find"):
        return rng.choice(objs), None
    return rng.choice(objs), rng.choice(places)


def generate(split: str, n: int, seed: int = 0, noise: float = 0.15) -> List[Example]:
    """`train` / `val` use TRAIN phrasing and train words (disjoint seeds); `test`
    uses TEST phrasing and may use held-out object/place words."""
    rng = random.Random(f"parser-{split}-{seed}")
    templates = TEST if split == "test" else TRAIN
    objs = OBJECTS_TRAIN + (OBJECTS_HELD_OUT if split == "test" else [])
    places = PLACES_TRAIN + (PLACES_HELD_OUT if split == "test" else [])
    out: List[Example] = []
    for _ in range(n):
        goal = rng.choice(GOALS)
        obj, tgt = _slots(goal, rng, objs, places)
        words = rng.choice(templates[goal]).split()
        if rng.random() < noise:  # typo in a non-slot word only (slots stay matchable)
            idx = [k for k, w in enumerate(words) if "{" not in w]
            if idx:
                k = rng.choice(idx)
                words[k] = _typo(rng, words[k])
        text = " ".join(words).format(o=obj, t=tgt)
        text = rng.choice(_FILLERS_PRE) + text + rng.choice(_FILLERS_POST)
        if rng.random() < noise:
            text = text.capitalize() + "."
        out.append(Example(text, goal, obj, tgt))
    return out
