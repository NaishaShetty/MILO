"""Model-written parser phrasings: slots checked, duplicates dropped, families held out."""

from __future__ import annotations

import learning.parser.llm_phrasings as lp
from learning.parser.data import TRAIN


def test_templates_must_use_exactly_their_goals_slots():
    assert lp.valid("store", "shove the {o} in the {t} pls")
    assert not lp.valid("store", "shove the {o} in there")  # place missing
    assert not lp.valid("fetch", "gimme the {o} from the {t}")  # extra slot
    assert not lp.valid("fetch", "gimme the {o} and the {o}")  # slot twice
    assert not lp.valid("fetch", "gimme the {thing}")  # unknown slot
    assert not lp.valid("fetch", "i need you to {o} something for me")  # slot as a verb
    assert not lp.valid("fetch", "hey {o} this to me please")
    assert lp.valid("turn_off", "{o} off please")
    assert lp.valid("tidy_up", "this place is a tip, sort it")
    assert not lp.valid("tidy_up", "tidy the {o}")


def test_collect_drops_known_and_duplicate_templates_and_holds_some_out(monkeypatch):
    known = TRAIN["fetch"][0]

    def fake_ask(goal, n, model, url, seed):
        if goal != "fetch":
            return []
        return [known, "yo grab me the {o}", "Yo grab me the {o}!", "{o} pls"] + [
            f"could u get the {{o}} number {i}" for i in range(20)
        ]

    monkeypatch.setattr(lp, "ask", fake_ask)
    got = lp.collect("m", "http://x", per_goal=24)
    fetch = got["train"]["fetch"] + got["held_out"]["fetch"]
    assert lp.norm(known) not in fetch
    assert fetch.count("yo grab me the {o}") == 1
    assert got["held_out"]["fetch"] and got["train"]["fetch"]
    assert not set(got["train"]["fetch"]) & set(got["held_out"]["fetch"])
    assert got["stats"]["fetch"]["accepted"] == len(fetch)


def test_filled_examples_take_their_labels_from_the_slots():
    examples = lp._fill({"store": ["shove the {o} in the {t} pls"]}, "train", 5, 0)
    for e in examples:
        assert e.goal == "store" and e.object and e.target
        assert e.object in e.text.lower() and e.target in e.text.lower()
