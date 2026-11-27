"""The language-model planner is given a whole sentence, not just the goal word."""

from __future__ import annotations

from novel.planner import command_text
from schemas.task import SingleTask


def test_a_structured_task_reaches_the_model_with_its_object_and_place():
    assert command_text(SingleTask(goal="fetch", object="mug")) == "bring me the mug"
    assert (
        command_text(SingleTask(goal="store", object="apple", target="fridge"))
        == "put the apple in the fridge"
    )
    assert command_text(SingleTask(goal="turn_on", object="television")) == (
        "turn on the television"
    )


def test_a_novel_command_is_passed_on_as_said():
    task = SingleTask(goal="novel", estimated_goal="chill the apple")
    assert command_text(task) == "chill the apple"


def test_a_goal_without_a_template_still_keeps_its_object():
    assert command_text(SingleTask(goal="clear_table", object="table")) == (
        "clear table table"
    )
