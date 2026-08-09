"""
test_language_semantic_validator.py

Purpose
-------
Verifies `SemanticValidator` accepts every structurally-valid task this
project's real usage is expected to produce, and rejects exactly the
narrow, curated set of semantically-implausible combinations documented
in `semantic_validator.py`'s module docstring -- never anything wider.
The "never anything wider" half is as important as the rejection cases:
a false positive here would incorrectly reject or retry a perfectly
valid instruction.
"""

from __future__ import annotations

import pytest

from language.exceptions import SemanticValidationError
from language.semantic_validator import SemanticValidator
from schemas.task import MultiTask, SingleTask


@pytest.fixture()
def validator() -> SemanticValidator:
    return SemanticValidator()


class TestAcceptsPlausibleTasks:
    def test_goal_with_no_object_needed_is_accepted(
        self, validator: SemanticValidator
    ) -> None:
        # "navigate_to" (and any goal outside the curated
        # object-required set, e.g. this test suite's own "fetch"
        # fixture used elsewhere) legitimately has no object.
        task = SingleTask(goal="navigate_to", target_location="kitchen")
        validator.validate(task)  # must not raise

    def test_object_required_goal_with_object_present_is_accepted(
        self, validator: SemanticValidator
    ) -> None:
        task = SingleTask(goal="bring", object="red mug")
        validator.validate(task)

    def test_object_required_goal_with_target_present_is_accepted(
        self, validator: SemanticValidator
    ) -> None:
        task = SingleTask(goal="bring", target="the guest")
        validator.validate(task)

    def test_object_required_goal_with_clarification_flagged_is_accepted(
        self, validator: SemanticValidator
    ) -> None:
        task = SingleTask(
            goal="bring",
            needs_clarification=True,
            clarification_reason="which mug is unclear",
        )
        validator.validate(task)

    def test_task_with_no_goal_at_all_is_accepted(
        self, validator: SemanticValidator
    ) -> None:
        task = SingleTask(needs_clarification=True, clarification_reason="unclear")
        validator.validate(task)

    def test_multitask_with_resolved_subtasks_is_accepted(
        self, validator: SemanticValidator
    ) -> None:
        multi = MultiTask(
            subtasks=[
                SingleTask(goal="navigate_to", target_location="kitchen"),
                SingleTask(goal="pick_up", object="mug"),
            ]
        )
        validator.validate(multi)


class TestRejectsImplausibleTasks:
    def test_object_required_goal_missing_object_and_target(
        self, validator: SemanticValidator
    ) -> None:
        task = SingleTask(goal="bring")
        with pytest.raises(SemanticValidationError):
            validator.validate(task)

    def test_object_equals_target(self, validator: SemanticValidator) -> None:
        task = SingleTask(object="mug", target="mug")
        with pytest.raises(SemanticValidationError):
            validator.validate(task)

    def test_object_equals_target_case_insensitive(
        self, validator: SemanticValidator
    ) -> None:
        task = SingleTask(object="Mug", target="mug")
        with pytest.raises(SemanticValidationError):
            validator.validate(task)

    def test_multitask_subtask_failure_propagates(
        self, validator: SemanticValidator
    ) -> None:
        multi = MultiTask(
            subtasks=[
                SingleTask(goal="navigate_to", target_location="kitchen"),
                SingleTask(goal="bring"),  # missing object/target
            ]
        )
        with pytest.raises(SemanticValidationError):
            validator.validate(multi)

    def test_multitask_contradictory_clarification_state(
        self, validator: SemanticValidator
    ) -> None:
        multi = MultiTask(
            needs_clarification=False,
            subtasks=[
                SingleTask(needs_clarification=True, clarification_reason="unclear a"),
                SingleTask(needs_clarification=True, clarification_reason="unclear b"),
            ],
        )
        with pytest.raises(SemanticValidationError):
            validator.validate(multi)
