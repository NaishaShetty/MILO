"""DEV (prompt tuning, model choice) and TEST (final results) must never overlap."""

from __future__ import annotations

import re

from novel.dev_set import dev_commands, dev_scene, few_shot_commands
from novel.eval_novel import commands as held_out_commands
from novel.eval_novel import scene as held_out_scene


def _types(objects):
    return {o["objectType"].lower() for o in objects}


def _family(command: str, object_words: set) -> str:
    """The phrasing pattern: the command with its object and place words blanked."""
    words = re.findall(r"[a-z']+", command.lower())
    return " ".join("X" if w in object_words else w for w in words)


def test_sizes():
    assert len(dev_commands()) == 40
    assert len(held_out_commands()) == 60


def test_scenes_share_no_object_type():
    assert _types(dev_scene()) & _types(held_out_scene()) == set()


def test_commands_are_disjoint():
    dev = {c["command"] for c in dev_commands()}
    test = {c["command"] for c in held_out_commands()}
    assert dev & test == set()


def test_phrasing_families_are_disjoint():
    objects = (
        _types(dev_scene())
        | _types(held_out_scene())
        | {"telly", "tap", "fruit", "counter", "room", "light", "water"}
    )
    dev = {_family(c["command"], objects) for c in dev_commands()}
    test = {_family(c["command"], objects) for c in held_out_commands()}
    assert dev & test == set(), sorted(dev & test)


def test_leading_verbs_are_disjoint():
    def first(cmds):
        return {c["command"].split()[0].lower() for c in cmds}

    assert first(dev_commands()) & first(held_out_commands()) == set()


def test_few_shot_examples_come_from_dev_only():
    dev = {c["command"] for c in dev_commands()}
    test = {c["command"] for c in held_out_commands()}
    for cmd in few_shot_commands():
        assert cmd in dev or any(d.startswith(cmd) for d in dev), cmd
        assert cmd not in test
