"""
dev_set.py (backend/novel)

The DEV set for the local language model: 30 commands, used ONLY to pick a model and
tune prompts and few-shot examples. The 60-command TEST set in `novel.eval_novel` is
touched once per final result.

DEV and TEST are disjoint by construction, and `tests/test_novel_dev_split.py` fails if
they ever overlap:
- a different room: no object type appears in both scenes;
- different commands and phrasing families (the command with its object words removed);
- different leading verbs.

Same shape as `eval_novel.commands()`: {command, category, answer, twin}.
"""

from __future__ import annotations

from typing import Any, Dict, List

from novel.eval_novel import P, S, plan

# (type, openable)
DEV_RECEPTACLES = [("Cooler", True), ("Desk", False), ("Bed", False), ("Safe", True),
                   ("Armchair", False), ("Sink", False), ("Box", True)]  # fmt: skip
DEV_TOGGLES = ["Lamp", "Radio", "Kettle"]
DEV_ITEMS = {"Lettuce": "Desk", "Bread": "Desk", "Spoon": "Sink", "Pen": "Desk",
             "Vase": "Armchair", "Pillow": "Bed", "Pan": "Sink", "Newspaper": "Armchair",
             "Candle": "Desk", "Watch": "Bed"}  # fmt: skip


def dev_scene() -> List[Dict[str, Any]]:
    objects: List[Dict[str, Any]] = []
    for i, (name, openable) in enumerate(DEV_RECEPTACLES):
        o: Dict[str, Any] = {"objectId": f"{name}|1", "objectType": name,
                             "distance": 2.1 + 0.3 * i, "visible": True, "pickupable": False}  # fmt: skip
        if openable:
            o.update(openable=True, isOpen=False)
        objects.append(o)
    for i, name in enumerate(DEV_TOGGLES):
        objects.append({"objectId": f"{name}|1", "objectType": name, "distance": 2.4 + 0.2 * i,
                        "visible": True, "pickupable": False, "isToggled": name == "Radio"})  # fmt: skip
    for i, (name, place) in enumerate(DEV_ITEMS.items()):
        objects.append({"objectId": f"{name}|1", "objectType": name, "distance": 2.3 + 0.1 * i,
                        "visible": True, "pickupable": True,
                        "parentReceptacles": [f"{place}|1"]})  # fmt: skip
    return objects


def _into(obj: str, rec: str, openable: bool) -> List[Dict[str, str]]:
    pre = [S("locate", rec), S("navigate", rec), S("open", rec)] if openable else []
    post = [S("close", rec)] if openable else []
    return (pre + [S("locate", obj), S("navigate", obj), S("pickup", obj),
                   S("locate", rec), S("navigate", rec), S("place", obj, rec)] + post)  # fmt: skip


def _toggle(obj: str, on: bool) -> List[Dict[str, str]]:
    return [
        S("locate", obj),
        S("navigate", obj),
        S("turn_on" if on else "turn_off", obj),
    ]


def _openit(rec: str) -> List[Dict[str, str]]:
    return [S("locate", rec), S("navigate", rec), S("open", rec)]


def dev_commands() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def add(cmd: str, cat: str, answer: Dict[str, Any], twin: Any = None) -> None:
        out.append({"command": cmd, "category": cat, "answer": answer, "twin": twin})

    def stow(cmd: str, obj: str, rec: str, openable: bool, twin: Any = None) -> None:
        success = [P("in_receptacle", obj, rec)] + (
            [P("is_closed", rec)] if openable else []
        )
        add(cmd, "new_combination", plan(cmd, _into(obj, rec, openable), success), twin)

    # 18 new verb/object combinations
    for a, b in [("bread", "lettuce")]:
        for x in (a, b):
            stow(
                f"cool the {x} down",
                x,
                "cooler",
                True,
                f"cool the {b if x == a else a} down",
            )
    for a, b in [("watch", "pen")]:
        for x in (a, b):
            stow(
                f"stash the {x} in the safe",
                x,
                "safe",
                True,
                f"stash the {b if x == a else a} in the safe",
            )
    for a, b in [("candle", "newspaper")]:
        for x in (a, b):
            stow(
                f"pop the {x} onto the desk",
                x,
                "desk",
                False,
                f"pop the {b if x == a else a} onto the desk",
            )
    for a, b in [("pillow", "vase")]:
        for x in (a, b):
            stow(
                f"leave the {x} on the bed",
                x,
                "bed",
                False,
                f"leave the {b if x == a else a} on the bed",
            )
    stow("rest the newspaper on the armchair", "newspaper", "armchair", False)
    stow("drop the spoon into the sink for washing", "spoon", "sink", False)
    stow("box up the candle", "candle", "box", True)
    stow("pack the watch into the box", "watch", "box", True)
    add(
        "light up the corner",
        "new_combination",
        plan("switch the lamp on", _toggle("lamp", True), [P("toggled_on", "lamp")]),
    )
    add(
        "silence the radio",
        "new_combination",
        plan(
            "switch the radio off", _toggle("radio", False), [P("toggled_off", "radio")]
        ),
    )
    add(
        "boil some water",
        "new_combination",
        plan(
            "switch the kettle on", _toggle("kettle", True), [P("toggled_on", "kettle")]
        ),
    )
    add(
        "crack the safe open",
        "new_combination",
        plan("open the safe", _openit("safe"), [P("is_open", "safe")]),
    )
    add(
        "peek in the cooler",
        "new_combination",
        plan("open the cooler", _openit("cooler"), [P("is_open", "cooler")]),
    )
    add("carry the pan around with you", "new_combination",
        plan("hold the pan", [S("locate", "pan"), S("navigate", "pan"), S("pickup", "pan")],
             [P("held", "pan")]))  # fmt: skip

    # 6 compositions
    combos = [
        ("cool the bread down and light up the corner",
         _into("bread", "cooler", True) + _toggle("lamp", True),
         [P("in_receptacle", "bread", "cooler"), P("toggled_on", "lamp")]),
        ("silence the radio, then boil some water",
         _toggle("radio", False) + _toggle("kettle", True),
         [P("toggled_off", "radio"), P("toggled_on", "kettle")]),
        ("stash the watch in the safe and leave the pillow on the bed",
         _into("watch", "safe", True) + _into("pillow", "bed", False),
         [P("in_receptacle", "watch", "safe"), P("in_receptacle", "pillow", "bed")]),
        ("relocate the vase from the armchair to the desk",
         _into("vase", "desk", False), [P("in_receptacle", "vase", "desk")]),
        ("crack the safe open, then carry the pen around with you",
         _openit("safe") + [S("locate", "pen"), S("navigate", "pen"), S("pickup", "pen")],
         [P("is_open", "safe"), P("held", "pen")]),
        ("box up the spoon and pop the lettuce onto the desk",
         _into("spoon", "box", True) + _into("lettuce", "desk", False),
         [P("in_receptacle", "spoon", "box"), P("in_receptacle", "lettuce", "desk")]),
    ]  # fmt: skip
    for cmd, steps, success in combos:
        add(cmd, "composition", plan(cmd, steps, success))

    for cmd, q in [("deal with that", "What would you like me to deal with?"),
                   ("sort it out", "What should I sort out?"),
                   ("bring one over", "Which thing should I bring?")]:  # fmt: skip
        add(
            cmd,
            "ambiguous",
            {"goal": "", "success": [], "steps": [], "question": q, "impossible": ""},
        )
    for cmd, why in [("iron my shirt", "I have no iron and no ironing action"),
                     ("walk the dog", "there is no dog here and I can't go outside"),
                     ("sing me a song", "I can't sing")]:  # fmt: skip
        add(
            cmd,
            "impossible",
            {"goal": "", "success": [], "steps": [], "question": "", "impossible": why},
        )
    return out


def few_shot_commands() -> List[str]:
    """DEV commands whose reference answers are shown to the model as examples."""
    return ["cool the bread down", "deal with that", "iron my shirt"]
