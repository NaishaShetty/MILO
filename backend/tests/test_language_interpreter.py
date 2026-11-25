"""
test_language_interpreter.py

The phrasebook that turns everyday sentences into tasks, questions,
preferences, clarifying questions or a plain "I can't do that yet".
Offline: no LLM, except where a fake fallback parser is injected to check
the hand-off.
"""

from __future__ import annotations

import pytest

from language.interpreter import InstructionInterpreter
from schemas.task import MultiTask, SingleTask


def _task(text: str, **kwargs):
    result = InstructionInterpreter(**kwargs).interpret(text)
    assert result.kind == "task", (text, result.kind, result.message)
    return result.task


def _shape(task: SingleTask):
    return (
        task.goal,
        task.object,
        task.target,
        task.source_location,
        task.target_location,
    )


@pytest.mark.parametrize(
    "text, goal, obj, target",
    [
        ("Put the apple in the fridge", "store", "apple", "fridge"),
        ("put the mug on the shelf", "place", "mug", "shelf"),
        ("Could you grab me the mug?", "fetch", "mug", None),
        ("could you please bring me the apple", "fetch", "apple", None),
        ("get me a mug", "fetch", "mug", None),
        ("Fetch the book", "fetch", "book", None),
        ("give me the keys", "fetch", "keys", None),
        ("bring the apple to me", "fetch", "apple", None),
        ("Take the book to the desk", "deliver", "book", "desk"),
        ("bring the package to the office", "deliver", "package", "office"),
        ("move the mug to the shelf", "place", "mug", "shelf"),
        ("pick up the book", "pick_up", "book", None),
        ("grab the mug", "pick_up", "mug", None),
        ("open the drawer", "open", "drawer", None),
        ("Close the fridge please", "close", "fridge", None),
        ("turn on the lights", "turn_on", "lights", None),
        ("switch the tap off", "turn_off", "tap", None),
        ("find the mug", "find", "mug", None),
        ("can you look for my keys?", "find", "keys", None),
    ],
)
def test_everyday_requests_become_the_right_task(text, goal, obj, target):
    task = _task(text)
    assert isinstance(task, SingleTask)
    assert (task.goal, task.object) == (goal, obj)
    assert (task.target or task.target_location) == target


def test_colour_words_become_attributes_not_part_of_the_object_name():
    task = _task("put the red apple in the fridge")
    assert task.object == "apple"
    assert task.attributes is not None and task.attributes.color == "red"


def test_go_to_is_a_navigation_task_not_politeness():
    task = _task("go to the fridge")
    assert (task.goal, task.target) == ("navigate_to", "fridge")


def test_clear_the_table_needs_a_destination_and_asks_for_it():
    ask = InstructionInterpreter().interpret("clear the table")
    assert ask.kind == "clarify"
    assert "Where should I put" in ask.message

    task = _task("clear the table onto the counter")
    assert _shape(task) == ("clear_table", None, None, "table", "counter")


@pytest.mark.parametrize(
    "text", ["tidy up", "Tidy up the room", "put everything away", "clean up"]
)
def test_tidy_up_phrasings(text):
    assert _task(text).goal == "tidy_up"


def test_chains_become_a_multitask_in_order():
    task = _task("put the apple in the fridge and the mug on the shelf")
    assert isinstance(task, MultiTask)
    assert [_shape(s)[:3] for s in task.subtasks] == [
        ("store", "apple", "fridge"),
        ("place", "mug", "shelf"),
    ]

    task = _task("open the fridge then grab the apple")
    assert [s.goal for s in task.subtasks] == ["open", "pick_up"]

    task = _task("find the mug and the cup")
    assert [(s.goal, s.object) for s in task.subtasks] == [
        ("find", "mug"),
        ("find", "cup"),
    ]


@pytest.mark.parametrize(
    "text, kind, subject, expected",
    [
        ("is the fridge open?", "is_open", "fridge", True),
        ("Is the drawer closed?", "is_open", "drawer", False),
        ("are the lights on?", "is_on", "lights", True),
        ("where is the mug?", "where", "mug", None),
        ("where's my book", "where", "book", None),
    ],
)
def test_plain_questions_are_answered_without_acting(text, kind, subject, expected):
    result = InstructionInterpreter().interpret(text)
    assert result.kind == "question"
    assert (
        result.question.kind,
        result.question.subject,
        result.question.expected,
    ) == (
        kind,
        subject,
        expected,
    )


def test_holding_and_seeing_questions():
    ask = InstructionInterpreter().interpret
    assert ask("what are you holding?").question.kind == "holding"
    assert ask("what can you see?").question.kind == "see"


def test_a_preference_is_remembered_not_acted_on():
    result = InstructionInterpreter().interpret("the mug goes on the shelf")
    assert result.kind == "preference"
    assert (
        result.preference.object,
        result.preference.place,
        result.preference.relation,
    ) == (
        "mug",
        "shelf",
        "located_on",
    )
    inside = InstructionInterpreter().interpret(
        "Remember that the apple goes in the fridge"
    )
    assert inside.preference.relation == "stored_in"
    assert "I'll remember" in inside.message


def test_help_lists_what_milo_can_do():
    result = InstructionInterpreter().interpret("what can you do?")
    assert result.kind == "help"
    assert "fetch" in result.message.lower() and "tidy up" in result.message.lower()


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("put it away", "What should I put away"),
        ("grab it", "What should I pick up"),
        ("bring me something", "What should I bring you"),
        ("open it", "What should I open"),
        ("take the book to", "Where should I take"),
        ("turn on", "What should I turn on"),
        ("the mug", "What should I do with the mug"),
    ],
)
def test_missing_details_get_a_clarifying_question(text, fragment):
    result = InstructionInterpreter().interpret(text)
    assert result.kind == "clarify", (text, result.kind)
    assert fragment in result.message


def test_put_away_uses_a_remembered_usual_place():
    def usual(name):
        return ("shelf", "located_on") if name == "mug" else None

    task = _task("put the mug away", usual_place=usual)
    assert _shape(task)[:3] == ("place", "mug", "shelf")

    ask = InstructionInterpreter(usual_place=usual).interpret("put the book away")
    assert ask.kind == "clarify" and "usually go" in ask.message


@pytest.mark.parametrize("text", ["fly to the moon", "dance", "cook dinner"])
def test_impossible_requests_get_a_plain_reason_and_what_milo_can_do(text):
    result = InstructionInterpreter().interpret(text)
    assert result.kind == "unsupported"
    assert "I don't know how to" in result.message
    assert "I can" in result.message


def test_empty_input_asks_what_to_do():
    assert InstructionInterpreter().interpret("please").kind == "clarify"


def test_unknown_phrasing_is_handed_to_the_model_when_there_is_one():
    seen = []

    def model(text):
        seen.append(text)
        return SingleTask(goal="clean", object="window")

    result = InstructionInterpreter(fallback=model).interpret("Wipe down the window")
    assert result.kind == "task" and result.source == "model"
    assert seen == ["Wipe down the window"]


def test_everyday_phrasing_never_needs_the_model():
    def model(text):  # pragma: no cover - must not be called
        raise AssertionError("the phrasebook should have handled this")

    assert (
        InstructionInterpreter(fallback=model).interpret("find the mug").kind == "task"
    )


def test_model_that_cannot_parse_falls_back_to_a_plain_reason():
    result = InstructionInterpreter(fallback=lambda text: None).interpret(
        "flibbertigibbet the mug"
    )
    assert result.kind == "unsupported"
