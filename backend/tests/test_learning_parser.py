"""Phase E: small instruction parser -- data splits, model, serving flag, interpreter hook."""

from __future__ import annotations

import pytest

from language.interpreter import InstructionInterpreter
from learning.parser.data import (
    OBJECTS_HELD_OUT,
    TEST,
    TRAIN,
    generate,
)
from learning.parser.model import SmallParser, tokenize
from learning.parser.serving import build_learned_parser
from schemas.task import SingleTask


@pytest.fixture(scope="module")
def model():
    return SmallParser().fit(generate("train", 2500, seed=1))


def test_train_and_test_phrasings_are_disjoint():
    train = {t for ts in TRAIN.values() for t in ts}
    test = {t for ts in TEST.values() for t in ts}
    assert not train & test


def test_generation_is_deterministic_and_labels_are_matchable():
    a, b = generate("test", 200, seed=3), generate("test", 200, seed=3)
    assert a == b
    for e in a:
        toks = tokenize(e.text)
        assert e.object is None or e.object in toks
        assert e.target is None or e.target in toks


def test_held_out_objects_only_appear_in_test():
    train_val = generate("train", 3000, 0) + generate("val", 1000, 0)
    assert not [e for e in train_val if e.object in OBJECTS_HELD_OUT]
    assert [e for e in generate("test", 3000, 0) if e.object in OBJECTS_HELD_OUT]


def test_parses_known_phrasing_and_unseen_object(model):
    p = model.parse("please bring me the plate")  # "plate" never seen in training
    assert (p.goal, p.object, p.target) == ("fetch", "plate", None)
    assert p.confidence > 0.5
    p = model.parse("put the mug on the shelf")
    assert (p.goal, p.object, p.target) == ("place", "mug", "shelf")


def test_gibberish_has_low_confidence(model):
    assert model.parse("colourless green ideas sleep furiously").confidence < 0.7


def test_model_round_trips_and_bad_file_returns_none(model, tmp_path):
    model.save(tmp_path / "p.pkl")
    again = SmallParser.load(tmp_path / "p.pkl")
    assert again is not None
    assert again.parse("find the apple").goal == model.parse("find the apple").goal
    (tmp_path / "bad.pkl").write_bytes(b"nope")
    assert SmallParser.load(tmp_path / "bad.pkl") is None
    assert SmallParser.load(tmp_path / "missing.pkl") is None


def test_serving_is_off_by_default_and_falls_back_when_model_missing(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("MILO_LEARNED_PARSER", raising=False)
    assert build_learned_parser() is None
    monkeypatch.setenv("MILO_LEARNED_PARSER", "1")
    monkeypatch.setenv("MILO_PARSER_DIR", str(tmp_path / "nope"))
    assert build_learned_parser() is None


def test_serving_returns_tasks_only_when_confident(model, monkeypatch, tmp_path):
    model.save(tmp_path / "parser.pkl")
    monkeypatch.setenv("MILO_LEARNED_PARSER", "1")
    monkeypatch.setenv("MILO_PARSER_DIR", str(tmp_path))
    monkeypatch.setenv("MILO_PARSER_THRESHOLD", "0.7")
    parse = build_learned_parser()
    assert parse is not None
    task = parse("take the mug to the desk")
    assert isinstance(task, SingleTask) and task.goal == "deliver"
    assert (task.object, task.target) == ("mug", "desk")
    assert parse("colourless green ideas sleep furiously") is None


def test_interpreter_uses_learned_parser_for_novel_phrasing_only_when_given():
    rules_only = InstructionInterpreter()
    assert rules_only.interpret("i want the mug at the desk").kind != "task"

    calls = []

    def learned(text):
        calls.append(text)
        return SingleTask(goal="deliver", object="mug", target="desk")

    out = InstructionInterpreter(learned=learned).interpret(
        "i want the mug at the desk"
    )
    assert out.kind == "task" and out.source == "learned"
    assert out.task.goal == "deliver" and calls == ["i want the mug at the desk"]


def test_questions_and_help_never_reach_the_learned_parser():
    def boom(text):
        raise AssertionError("must not be called")

    it = InstructionInterpreter(learned=boom)
    assert it.interpret("is the fridge open?").kind == "question"
    assert it.interpret("what can you do?").kind == "help"


def test_a_learned_parser_that_declines_leaves_the_phrasebook_in_charge():
    out = InstructionInterpreter(learned=lambda t: None).interpret("fetch the mug")
    assert out.kind == "task" and out.source == "rules" and out.task.goal == "fetch"
