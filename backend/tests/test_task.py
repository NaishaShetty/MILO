"""
test_task.py

Purpose
-------
Unit tests for the Language Interface schema (`schemas/task.py`,
`schemas/enums.py`, `schemas/metadata.py`, `schemas/validators.py`).
This is the executable proof that Phase 3.2's validation requirements
actually hold -- every invariant described in `schemas/task.py`'s and
`schemas/validators.py`'s docstrings has a corresponding test here that
would fail if that invariant were silently broken by a future edit.

Why this file exists
----------------------
The Language Interface is documented as "the single source of truth
for all task representations throughout the project"
(`backend/docs/language_interface_spec.md`). A schema can only be
trusted at that level if its behavior is pinned down by tests, not just
by docstrings a future editor could accidentally invalidate. Every
Planner, Execution, Memory, and Reflection module built in a later
phase will assume these invariants hold without re-checking them --
this file is what keeps that assumption safe across schema changes.

How to run
-----------
From `backend/` (so `schemas` resolves as a top-level import, matching
every other module in this project -- see `scene/test_scene.py` for the
same convention):

    cd backend
    python -m pytest tests/test_task.py -v

Organization
-------------
Tests are grouped by the model or invariant under test, mirroring
`schemas/task.py`'s own structure (`TaskConstraint` ->
`TaskAttributes` -> `Task` cross-field rules -> `SingleTask` ->
`MultiTask` -> the `ParsedInstruction` discriminated union ->
serialization). New fields or validators added to the schema should
have their tests added to the matching section here, not scattered
into a generic "misc" section, so this file stays easy to extend as
the schema evolves.
"""

import json
from datetime import datetime
from typing import Union

import pytest
from pydantic import TypeAdapter, ValidationError

from schemas.enums import ConstraintType, TaskPriority, TaskType
from schemas.metadata import SCHEMA_VERSION, TaskMetadata
from schemas.task import (
    MultiTask,
    ParsedInstruction,
    SingleTask,
    Task,
    TaskAttributes,
    TaskConstraint,
)

# Shared discriminated-union adapter, reused across every test that
# validates raw dict/JSON payloads the way a future Language Agent
# would -- constructing it once per module avoids the (small) per-call
# schema-analysis cost TypeAdapter does at construction time.
# `ParsedInstruction` is itself `Annotated[Union[SingleTask, MultiTask], ...]`,
# so the TypeAdapter's type parameter mirrors that union rather than a
# bare `TypeAdapter` (which mypy --strict flags as missing type args).
parsed_instruction_adapter: TypeAdapter[Union[SingleTask, MultiTask]] = TypeAdapter(
    ParsedInstruction
)


# ==========================================================================
# TaskConstraint
# ==========================================================================


class TestTaskConstraint:
    """
    Covers `TaskConstraint`'s own validation: a constraint must carry a
    real description, and is immutable once constructed.
    """

    def test_valid_constraint(self) -> None:
        constraint = TaskConstraint(
            constraint_type=ConstraintType.SAFETY,
            description="must not make noise because the baby is sleeping",
        )
        assert constraint.constraint_type is ConstraintType.SAFETY
        assert constraint.value is None

    def test_empty_description_rejected(self) -> None:
        # `require_non_empty_text` in validators.py must reject this --
        # a constraint that describes nothing is not a usable constraint.
        with pytest.raises(ValidationError):
            TaskConstraint(constraint_type=ConstraintType.SAFETY, description="   ")

    def test_invalid_constraint_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskConstraint.model_validate(
                {"constraint_type": "not_a_real_type", "description": "x"}
            )

    def test_is_frozen(self) -> None:
        constraint = TaskConstraint(
            constraint_type=ConstraintType.SAFETY, description="quiet please"
        )
        with pytest.raises(ValidationError):
            constraint.description = "changed"

    def test_unknown_field_rejected(self) -> None:
        # extra="forbid" is a deliberate schema-integrity guarantee --
        # see task.py's TaskConstraint docstring.
        with pytest.raises(ValidationError):
            TaskConstraint.model_validate(
                {"constraint_type": "safety", "description": "x", "bogus": 1}
            )


# ==========================================================================
# TaskAttributes
# ==========================================================================


class TestTaskAttributes:
    """
    Covers `TaskAttributes`: optional descriptive fields, the
    quantity >= 1 constraint, and empty-string normalization.
    """

    def test_all_fields_optional(self) -> None:
        attributes = TaskAttributes()
        assert attributes.color is None
        assert attributes.descriptors is None

    def test_valid_attributes(self) -> None:
        attributes = TaskAttributes(
            color="red", size="small", quantity=2, descriptors=["fragile"]
        )
        assert attributes.color == "red"
        assert attributes.quantity == 2
        assert attributes.descriptors == ["fragile"]

    def test_quantity_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskAttributes(quantity=0)

    def test_negative_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskAttributes(quantity=-3)

    def test_whitespace_only_text_normalizes_to_none(self) -> None:
        attributes = TaskAttributes(color="   ")
        assert attributes.color is None

    def test_descriptors_list_drops_empty_entries(self) -> None:
        attributes = TaskAttributes(descriptors=["fragile", "  ", "my favorite"])
        assert attributes.descriptors == ["fragile", "my favorite"]

    def test_descriptors_all_empty_becomes_none(self) -> None:
        # "no information" must always be represented as None, never []
        # -- see normalize_text_list's docstring in validators.py.
        attributes = TaskAttributes(descriptors=["  ", ""])
        assert attributes.descriptors is None

    def test_is_frozen(self) -> None:
        attributes = TaskAttributes(color="red")
        with pytest.raises(ValidationError):
            attributes.color = "blue"


# ==========================================================================
# Task cross-field invariants (shared by SingleTask and MultiTask)
# ==========================================================================


class TestClarificationConsistency:
    """
    Covers the `needs_clarification` <-> `clarification_reason`
    invariant enforced by `Task._check_clarification_consistency`
    (`task.py`), for both concrete task types.
    """

    def test_needs_clarification_true_without_reason_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SingleTask(needs_clarification=True)

    def test_needs_clarification_true_with_reason_accepted(self) -> None:
        task = SingleTask(
            needs_clarification=True, clarification_reason="ambiguous referent"
        )
        assert task.needs_clarification is True
        assert task.clarification_reason == "ambiguous referent"

    def test_needs_clarification_false_with_reason_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SingleTask(
                needs_clarification=False, clarification_reason="unexpected reason"
            )

    def test_needs_clarification_false_default_is_valid(self) -> None:
        task = SingleTask()
        assert task.needs_clarification is False
        assert task.clarification_reason is None

    def test_whitespace_only_reason_treated_as_missing(self) -> None:
        # A reason that normalizes to None must be treated exactly like
        # an omitted reason -- the consistency check runs after
        # normalization, so this must still fail validation.
        with pytest.raises(ValidationError):
            SingleTask(needs_clarification=True, clarification_reason="   ")


class TestGoalValidation:
    """Covers `validate_snake_case_goal` as wired into `Task.goal`."""

    @pytest.mark.parametrize(
        "goal",
        ["pick_and_place", "navigate_to", "open", "fetch123", "a_b_c"],
    )
    def test_valid_snake_case_goals_accepted(self, goal: str) -> None:
        task = SingleTask(goal=goal)
        assert task.goal == goal

    @pytest.mark.parametrize(
        "goal",
        [
            "Pick And Place",
            "pick-and-place",
            "pick and place",
            "_leading",
            "trailing_",
            "double__underscore",
        ],
    )
    def test_malformed_goals_rejected(self, goal: str) -> None:
        with pytest.raises(ValidationError):
            SingleTask(goal=goal)

    def test_goal_is_lowercased(self) -> None:
        task = SingleTask(goal="FETCH")
        assert task.goal == "fetch"

    def test_goal_none_is_valid(self) -> None:
        task = SingleTask(goal=None)
        assert task.goal is None


class TestTaskIdentity:
    """
    Covers automatic `task_id` (UUID4) and `metadata` (schema version +
    provenance) generation -- the Phase 3.2 hardening described in
    `task.py`'s module docstring.
    """

    def test_task_id_autogenerated_when_omitted(self) -> None:
        task = SingleTask(goal="fetch")
        assert task.task_id is not None
        assert len(task.task_id) == 36  # canonical UUID4 string length
        assert task.task_id.count("-") == 4

    def test_task_id_autogenerated_when_explicitly_null(self) -> None:
        # This is the exact shape parser_prompt.txt emits for every
        # task ("task_id": null, per its "never omit a field" rule) --
        # must resolve identically to the omitted-key case above.
        task = SingleTask.model_validate({"goal": "fetch", "task_id": None})
        assert task.task_id is not None
        assert len(task.task_id) == 36

    def test_task_id_generated_values_are_unique(self) -> None:
        first = SingleTask(goal="fetch")
        second = SingleTask(goal="fetch")
        assert first.task_id != second.task_id

    def test_explicit_task_id_preserved(self) -> None:
        task = SingleTask(goal="fetch", task_id="task-042")
        assert task.task_id == "task-042"

    def test_whitespace_only_task_id_regenerated(self) -> None:
        task = SingleTask.model_validate({"goal": "fetch", "task_id": "   "})
        assert task.task_id is not None
        assert task.task_id.strip() == task.task_id
        assert task.task_id != ""

    def test_metadata_defaults_to_current_schema_version(self) -> None:
        task = SingleTask(goal="fetch")
        assert isinstance(task.metadata, TaskMetadata)
        assert task.metadata.schema_version == SCHEMA_VERSION
        assert isinstance(task.metadata.created_at, datetime)

    def test_metadata_is_frozen(self) -> None:
        task = SingleTask(goal="fetch")
        with pytest.raises(ValidationError):
            task.metadata.source = "changed"


class TestConditionLists:
    """Covers `preconditions`/`postconditions` normalization."""

    def test_conditions_preserved(self) -> None:
        task = SingleTask(
            goal="fetch",
            preconditions=["room is empty"],
            postconditions=["lid is closed"],
        )
        assert task.preconditions == ["room is empty"]
        assert task.postconditions == ["lid is closed"]

    def test_empty_condition_entries_dropped(self) -> None:
        task = SingleTask(goal="fetch", preconditions=["room is empty", "  ", ""])
        assert task.preconditions == ["room is empty"]

    def test_all_empty_conditions_becomes_none(self) -> None:
        task = SingleTask(goal="fetch", preconditions=["  ", ""])
        assert task.preconditions is None


# ==========================================================================
# SingleTask
# ==========================================================================


class TestSingleTask:
    """
    Covers `SingleTask`-specific fields and the "no invented
    information" contract (missing data stays None, is never fabricated
    by the schema layer itself).
    """

    def test_fully_specified_task(self) -> None:
        task = SingleTask(
            goal="pick_and_place",
            object="red mug",
            source_location="kitchen counter",
            target_location="dining table",
            attributes=TaskAttributes(color="red"),
            priority=TaskPriority.HIGH,
        )
        assert task.task_type is TaskType.SINGLE
        assert task.object == "red mug"
        assert task.target is None
        assert task.priority is TaskPriority.HIGH

    def test_minimal_task_has_all_optional_fields_none(self) -> None:
        # Mirrors parser_prompt.txt Example 2 ("Bring me the milk.") --
        # missing information must stay None, never a fabricated value.
        task = SingleTask(goal="fetch", object="milk")
        assert task.target is None
        assert task.source_location is None
        assert task.target_location is None
        assert task.attributes is None
        assert task.constraints is None
        assert task.priority is None

    def test_task_type_defaults_correctly(self) -> None:
        task = SingleTask(goal="fetch")
        assert task.task_type is TaskType.SINGLE

    def test_task_type_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SingleTask.model_validate({"task_type": "multi", "goal": "fetch"})

    def test_whitespace_only_object_normalizes_to_none(self) -> None:
        task = SingleTask(goal="fetch", object="   ")
        assert task.object is None

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SingleTask.model_validate({"goal": "fetch", "unexpected_field": True})

    def test_is_mutable(self) -> None:
        # Deliberately NOT frozen -- see task.py's module-level design
        # notes on why aggregate roots stay mutable for future
        # Planner/Execution/Memory/Reflection enrichment.
        task = SingleTask(goal="fetch")
        task.priority = TaskPriority.HIGH
        assert task.priority is TaskPriority.HIGH

    def test_invalid_assignment_still_validated(self) -> None:
        # validate_assignment=True: mutation must go through the same
        # validation as construction, not silently store bad data.
        task = SingleTask(goal="fetch")
        with pytest.raises(ValidationError):
            task.priority = "not_a_valid_priority"  # type: ignore[assignment]


# ==========================================================================
# MultiTask
# ==========================================================================


class TestMultiTask:
    """
    Covers `MultiTask`-specific behavior: the minimum-two-subtasks
    invariant and ordered decomposition.
    """

    def test_valid_multitask(self) -> None:
        task = MultiTask(
            subtasks=[
                SingleTask(goal="pick_up", object="blue cup", source_location="sink"),
                SingleTask(goal="deliver", object="blue cup", target_location="office"),
            ]
        )
        assert task.task_type is TaskType.MULTI
        assert len(task.subtasks) == 2
        assert task.subtasks[0].goal == "pick_up"
        assert task.subtasks[1].goal == "deliver"

    def test_single_subtask_rejected(self) -> None:
        # A MultiTask exists specifically to represent >1 goal --
        # see validate_subtask_count in validators.py.
        with pytest.raises(ValidationError):
            MultiTask(subtasks=[SingleTask(goal="fetch")])

    def test_zero_subtasks_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MultiTask(subtasks=[])

    def test_subtask_order_preserved(self) -> None:
        goals = ["pick_up", "deliver", "turn_off"]
        task = MultiTask(subtasks=[SingleTask(goal=g) for g in goals])
        assert [subtask.goal for subtask in task.subtasks] == goals

    def test_each_subtask_gets_a_distinct_task_id(self) -> None:
        task = MultiTask(subtasks=[SingleTask(goal="a"), SingleTask(goal="b")])
        ids = [subtask.task_id for subtask in task.subtasks]
        assert len(set(ids)) == 2

    def test_invalid_subtask_propagates_validation_error(self) -> None:
        # A malformed subtask (bad goal casing) must fail the whole
        # MultiTask, not be silently accepted or dropped.
        with pytest.raises(ValidationError):
            MultiTask.model_validate(
                {
                    "subtasks": [
                        {"goal": "pick_up"},
                        {"goal": "Not Snake Case"},
                    ]
                }
            )

    def test_task_type_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MultiTask.model_validate(
                {"task_type": "single", "subtasks": [{"goal": "a"}, {"goal": "b"}]}
            )


# ==========================================================================
# ParsedInstruction discriminated union
# ==========================================================================


class TestParsedInstructionUnion:
    """
    Covers `ParsedInstruction`, the discriminated union a future
    Language Agent will validate raw LLM JSON output against directly
    (see `task.py`'s trailing comment).
    """

    def test_single_task_payload_resolves_to_singletask(self) -> None:
        result = parsed_instruction_adapter.validate_python(
            {"task_type": "single", "goal": "fetch", "object": "milk"}
        )
        assert isinstance(result, SingleTask)

    def test_multi_task_payload_resolves_to_multitask(self) -> None:
        result = parsed_instruction_adapter.validate_python(
            {
                "task_type": "multi",
                "subtasks": [{"goal": "a"}, {"goal": "b"}],
            }
        )
        assert isinstance(result, MultiTask)

    def test_invalid_discriminator_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parsed_instruction_adapter.validate_python({"task_type": "not_a_real_type"})

    def test_missing_discriminator_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parsed_instruction_adapter.validate_python({"goal": "fetch"})

    def test_parser_prompt_example_ambiguous_case(self) -> None:
        # Mirrors parser_prompt.txt Example 3 ("Put it on the table.")
        # -- ambiguity must be representable without discarding the
        # rest of the parser's best-effort reading.
        result = parsed_instruction_adapter.validate_python(
            {
                "task_type": "single",
                "goal": "place",
                "target_location": "table",
                "needs_clarification": True,
                "clarification_reason": "The pronoun 'it' has no clear referent.",
            }
        )
        assert isinstance(result, SingleTask)
        assert result.object is None
        assert result.needs_clarification is True


# ==========================================================================
# Serialization / deserialization
# ==========================================================================


class TestSerialization:
    """
    Covers round-tripping a `Task` through JSON, the exact path a
    future Memory module (persisting tasks) and Planner (receiving
    parsed instructions over a process boundary) both depend on.
    """

    def test_single_task_json_round_trip(self) -> None:
        original = SingleTask(goal="fetch", object="milk", priority=TaskPriority.HIGH)
        dumped = original.model_dump_json()
        restored = SingleTask.model_validate_json(dumped)
        assert restored == original

    def test_multitask_json_round_trip_via_union_adapter(self) -> None:
        original = MultiTask(subtasks=[SingleTask(goal="a"), SingleTask(goal="b")])
        dumped = parsed_instruction_adapter.dump_json(original)
        restored = parsed_instruction_adapter.validate_python(json.loads(dumped))
        assert restored == original

    def test_enum_fields_serialize_as_plain_strings(self) -> None:
        # TaskPriority/ConstraintType subclass `str` specifically so
        # JSON output stays plain strings, not a nested enum
        # representation -- see enums.py's module docstring.
        task = SingleTask(
            goal="fetch",
            priority=TaskPriority.HIGH,
            constraints=[
                TaskConstraint(
                    constraint_type=ConstraintType.SAFETY, description="be quiet"
                )
            ],
        )
        dumped = json.loads(task.model_dump_json())
        assert dumped["priority"] == "high"
        assert dumped["constraints"][0]["constraint_type"] == "safety"

    def test_datetime_metadata_serializes_and_restores(self) -> None:
        task = SingleTask(goal="fetch")
        dumped = task.model_dump_json()
        restored = SingleTask.model_validate_json(dumped)
        assert restored.metadata.created_at == task.metadata.created_at

    def test_model_dump_python_shape(self) -> None:
        # A plain (non-JSON) dump should keep native Python types --
        # e.g. an enum member, not its string value -- for callers that
        # want to keep working with typed objects in-process.
        task = SingleTask(goal="fetch", priority=TaskPriority.HIGH)
        dumped = task.model_dump()
        assert dumped["priority"] is TaskPriority.HIGH


# ==========================================================================
# Edge cases
# ==========================================================================


class TestEdgeCases:
    """Miscellaneous edge cases not tied to a single model or field."""

    def test_task_base_class_requires_task_type(self) -> None:
        # `Task` itself is never meant to be instantiated directly (see
        # its docstring) -- it has no default for `task_type`. The
        # missing argument is the point of this test (it must raise a
        # ValidationError at runtime), hence the mypy override below.
        with pytest.raises(ValidationError):
            Task()  # type: ignore[call-arg]

    def test_deeply_nested_multitask_serializes_completely(self) -> None:
        task = MultiTask(
            subtasks=[
                SingleTask(
                    goal="pick_up",
                    object="blue cup",
                    attributes=TaskAttributes(color="blue"),
                    constraints=[
                        TaskConstraint(
                            constraint_type=ConstraintType.SAFETY,
                            description="be careful",
                        )
                    ],
                ),
                SingleTask(goal="deliver", target_location="office"),
            ]
        )
        dumped = json.loads(task.model_dump_json())
        assert dumped["subtasks"][0]["attributes"]["color"] == "blue"
        assert dumped["subtasks"][0]["constraints"][0]["description"] == "be careful"

    def test_constraints_list_accepts_multiple_types(self) -> None:
        task = SingleTask(
            goal="fetch",
            constraints=[
                TaskConstraint(
                    constraint_type=ConstraintType.SAFETY, description="be quiet"
                ),
                TaskConstraint(
                    constraint_type=ConstraintType.TEMPORAL,
                    description="within 5 minutes",
                ),
            ],
        )
        assert task.constraints is not None
        assert len(task.constraints) == 2

    def test_custom_constraint_type_is_valid(self) -> None:
        # CUSTOM is a deliberate escape hatch -- see ConstraintType's
        # docstring in enums.py.
        constraint = TaskConstraint(
            constraint_type=ConstraintType.CUSTOM, description="something unusual"
        )
        assert constraint.constraint_type is ConstraintType.CUSTOM
