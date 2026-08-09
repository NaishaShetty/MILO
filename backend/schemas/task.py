"""
task.py

Purpose
-------
Defines the Language Interface: the single, stable data contract that
sits between the Language Understanding module and every module that
consumes its output (Planner, Execution, Memory, Reflection). This file
contains ONLY data models -- no parsing logic, no LLM calls, no runtime
behavior. It is the schema half of the interface described in
`backend/docs/language_interface_spec.md`; the prompt half lives in
`backend/prompts/parser_prompt.txt`.

Why this abstraction exists
----------------------------
Every future module in the pipeline (User -> Language Understanding ->
Planner -> Execution -> Memory -> Reflection) needs to agree on what a
"task" is without needing to know how the Language Understanding module
produced it. If the Planner imported LLM response dicts directly, any
change to the underlying model, prompt, or provider would silently
propagate into planning logic. `Task`, `SingleTask`, and `MultiTask`
exist so that boundary is explicit and typed: the Language Understanding
module's only contract with the rest of the system is "I produce a
`SingleTask` or `MultiTask`", not "I produce whatever JSON shape today's
LLM happens to emit."

This mirrors the pattern already established for perception in
`scene/scene.py` and `scene/detection.py` (see
`docs/architecture/api_contracts.md`): a strongly typed, shared data
model that downstream modules depend on instead of depending on the
producing module's internals. Just as `Scene` absorbed new perception
capabilities (masks, relationships) without breaking `VisionAgent`'s
signature, this schema is built so new task fields can be added later
without breaking the Planner, Execution, Memory, or Reflection modules
that already consume it.

Phase 3.2 changes (data-layer hardening)
------------------------------------------
Phase 3.1 defined the interface's *shape*. Phase 3.2 turns that shape
into a production-quality, validated data layer, split across four
files by concern:

- `schemas/enums.py` -- closed vocabularies (`TaskType`,
  `TaskPriority`, `ConstraintType`) that used to live inline here.
- `schemas/metadata.py` -- `TaskMetadata` (provenance + schema
  versioning), attached to every `Task` as `Task.metadata`.
- `schemas/validators.py` -- the reusable normalization/invariant
  functions every field validator below calls into, so the same logic
  is never duplicated across models.
- `schemas/task.py` (this file) -- the model definitions themselves,
  now wired up to the three files above.

Two behavioral changes from the Phase 3.1 draft, both additive and
non-breaking against the JSON contract in `parser_prompt.txt`:

1. `Task.task_id` is now auto-generated as a UUID4 string whenever a
   producer leaves it unset (`None`) or omits it entirely, instead of
   staying `None`. Every `Task` therefore has a stable identity from
   the moment it is validated -- important now that Memory (Phase 5)
   is expected to persist these records and Execution/Reflection are
   expected to reference them by id. `parser_prompt.txt` already emits
   `"task_id": null` for every task (per its "never omit a field" rule)
   precisely because id assignment was never the parser's job; this
   change only fills in who assigns it -- the schema layer itself, not
   the Planner or Memory -- so downstream modules never have to check
   for `None` before using a task's id. Validated to work correctly for
   both the omitted-key and explicit-`null` cases (see
   `_assign_task_id_if_missing` below).
2. Every model now attaches a `TaskMetadata` (`Task.metadata`) stamping
   schema version and creation time, and enforces `extra="forbid"` so a
   malformed or unexpected field fails validation immediately instead
   of being silently dropped.

Design notes
------------
- Every field that may legitimately be absent from a natural-language
  instruction is `Optional` and defaults to `None`. Downstream modules
  should treat `None` as "not specified" and must never treat it as an
  error -- see `parser_prompt.txt`'s "missing information -> null" rule,
  which this schema is the typed mirror of.
- `Task` holds every field common to both a single task and a subtask of
  a multi-task instruction. `SingleTask` and `MultiTask` both extend it,
  so a `Planner` written against `Task` fields works for either without
  a runtime `isinstance` check, and only needs to branch when it
  actually needs task-type-specific data (`SingleTask.object` /
  `MultiTask.subtasks`).
- `task_type` is typed as `Literal[TaskType.SINGLE]` /
  `Literal[TaskType.MULTI]` on the two subclasses so that
  `ParsedInstruction` (a discriminated union) can be validated directly
  from raw LLM JSON output with Pydantic choosing the correct model,
  rather than the caller needing to branch on shape before validation.
- `TaskAttributes`, `TaskConstraint`, and `TaskMetadata` are frozen
  (immutable) -- they are pure value objects describing facts fixed at
  parse time. `Task`/`SingleTask`/`MultiTask` are deliberately left
  mutable: they are the aggregate roots that future Planner, Execution,
  Memory, and Reflection modules are expected to enrich over a task's
  lifecycle (e.g. attaching a plan reference, an execution status, an
  outcome) as those modules are built in later phases. Freezing them
  now would force those future modules to reconstruct a new `Task` for
  every lifecycle update instead of annotating the existing one.
- Python compatibility: this project targets Python 3.9 (see
  `backend/requirements.txt` and the rest of `backend/scene/*.py`),
  which predates PEP 604 (`X | Y`) union syntax under Pydantic's
  runtime type resolution. `Optional[X]` / `List[X]` / `Union[X, Y]`
  from `typing` are used throughout for that reason -- this bit
  Phase 3.1 in practice (see the Phase 3.2 fix note in
  `language_interface_spec.md` section 14) and is called out here so it
  is not reintroduced.
"""

from typing import Annotated, List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.enums import ConstraintType, TaskPriority, TaskType
from schemas.metadata import TaskMetadata
from schemas.validators import (
    normalize_optional_text,
    normalize_text_list,
    require_non_empty_text,
    validate_clarification_consistency,
    validate_snake_case_goal,
    validate_subtask_count,
)


class TaskConstraint(BaseModel):
    """
    A single explicit constraint attached to a task.

    Purpose
        Represent one constraint the user's instruction actually stated
        or clearly implied (e.g. "but don't wake the dog"), as
        structured data a Planner can reason about individually instead
        of re-parsing a paragraph of constraint prose.

    Responsibilities
        Hold a `ConstraintType` category, a human-readable
        `description`, and an optional structured `value`. Nothing
        else -- this model does not decide how a constraint is
        enforced, only what it is.

    Downstream consumers
        The Planner (rejecting or adapting a plan that would violate a
        `SAFETY` constraint), Execution (checking a `TEMPORAL`
        constraint before acting), and Reflection (auditing whether a
        completed task actually respected its constraints).

    Design notes
        Frozen and `extra="forbid"`: a constraint is a fixed fact
        extracted from the instruction at parse time, not a mutable
        record with a lifecycle of its own. Constraints are never
        inferred by the Language Understanding module -- they exist as
        a list element on `Task.constraints` specifically so the
        producer only ever adds one when the instruction actually
        supports it, never as a generic robotics safety default.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    constraint_type: ConstraintType = Field(
        description="The category of constraint, used by the Planner to "
        "decide how this constraint should be enforced or validated."
    )
    description: str = Field(
        description="A faithful natural-language restatement of the "
        "constraint, preserved from the user's instruction rather than "
        "reworded, so a human or Reflection module can audit it against "
        "the original request."
    )
    value: Optional[str] = Field(
        default=None,
        description="A structured value extracted from the constraint "
        "when one exists (e.g. a duration, a distance, a count). "
        "`None` when the constraint is purely qualitative.",
    )

    @field_validator("description", mode="after")
    @classmethod
    def _require_description(cls, value: str) -> str:
        # A constraint that claims to describe something but describes
        # nothing (""), is not a usable constraint -- see
        # `validators.require_non_empty_text` for why this must raise
        # rather than silently normalize to an empty value.
        return require_non_empty_text(value, field_name="TaskConstraint.description")

    @field_validator("value", mode="after")
    @classmethod
    def _normalize_value(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class TaskAttributes(BaseModel):
    """
    Descriptive qualifiers about the object a task acts on.

    Purpose
        Hold the color/size/material/state/quantity/free-form
        descriptors an instruction attached to its primary object (e.g.
        "the *red*, *small* mug"), separately from the object reference
        itself.

    Responsibilities
        Store exactly the typed descriptive fields listed below plus an
        open-ended `descriptors` list for qualifiers that don't fit a
        typed field. Nothing else -- this model never infers an
        attribute the instruction did not state.

    Downstream consumers
        The Planner, for disambiguating between multiple candidate
        objects in a `Scene` that share a label (e.g. two mugs, one
        red) -- grounding `attributes` against `Detection` data is
        Planner work, not this schema's, but the Planner needs this
        data present and typed to do it.

    Design notes
        Frozen: attribute data describes the instruction as stated, a
        fact fixed at parse time. Split out from `Task` itself (rather
        than inlining color/size/etc. as top-level fields) so that
        attribute data has one obvious place to grow -- a future phase
        adding, say, a "weight" or "fragility" field only touches this
        model, not every field consumer of `Task`. This is the same
        rationale `scene/mask.py` uses for wrapping raw mask data in its
        own type instead of scattering fields across `Detection`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    color: Optional[str] = Field(
        default=None, description="Stated color of the object, e.g. 'red'."
    )
    size: Optional[str] = Field(
        default=None, description="Stated size of the object, e.g. 'small'."
    )
    material: Optional[str] = Field(
        default=None, description="Stated material, e.g. 'wooden'."
    )
    state: Optional[str] = Field(
        default=None,
        description="Stated physical/operational state, e.g. 'open', 'full', 'broken'.",
    )
    quantity: Optional[int] = Field(
        default=None,
        ge=1,
        description="Number of instances of the object referenced, if "
        "stated. Must be at least 1 when present -- a stated quantity "
        "of zero or fewer objects is not a meaningful manipulation "
        "target.",
    )
    descriptors: Optional[List[str]] = Field(
        default=None,
        description="Any other free-form qualifiers not covered by the "
        "typed fields above (e.g. 'fragile', 'my favorite'), preserved "
        "verbatim so no descriptive information from the instruction is "
        "silently dropped.",
    )

    @field_validator("color", "size", "material", "state", mode="after")
    @classmethod
    def _normalize_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("descriptors", mode="after")
    @classmethod
    def _normalize_descriptors(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return normalize_text_list(value)


class Task(BaseModel):
    """
    Base fields shared by every task representation in the Language
    Interface, whether it stands alone (`SingleTask`) or lives inside a
    `MultiTask.subtasks` list.

    Purpose
        Provide the one set of fields (`goal`, `priority`,
        `preconditions`, `needs_clarification`, ...) that is identical
        regardless of whether an instruction decomposed into one goal
        or several, so downstream modules have a single shape to
        program against.

    Responsibilities
        Own every field common to both `SingleTask` and `MultiTask`,
        plus the cross-cutting invariant that ties two of them together
        (`needs_clarification` <-> `clarification_reason`
        consistency, enforced below). Task-representation-specific
        fields (`SingleTask.object`, `MultiTask.subtasks`) belong on the
        subclasses, never here.

    Downstream consumers
        The Planner (Phase 4), Execution, Memory (Phase 5), and
        Reflection are all expected to read `Task` fields directly --
        this class, not `SingleTask`/`MultiTask` individually, is the
        contract those modules should type their inputs against
        wherever task-type-specific data isn't needed.

    Design notes
        Never instantiated directly by producers (`task_type` has no
        sensible default at this level) -- always construct a
        `SingleTask` or `MultiTask`. Intentionally not frozen: see the
        module-level "Design notes" above for why aggregate roots stay
        mutable while their nested value objects (`TaskAttributes`,
        `TaskConstraint`, `TaskMetadata`) are frozen.
    """

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, validate_assignment=True
    )

    task_type: TaskType = Field(
        description="Discriminator identifying the concrete task "
        "representation (`TaskType.SINGLE` or `TaskType.MULTI`). "
        "Downstream modules should branch on this field rather than "
        "using `isinstance` checks, since it is what travels through "
        "JSON serialization."
    )
    task_id: Optional[str] = Field(
        default=None,
        validate_default=True,
        description="Stable identifier for this task. Auto-generated as "
        "a UUID4 string whenever the producer leaves this unset or "
        "explicitly `null` (see `_assign_task_id_if_missing` below), so "
        "every `Task` carries a stable identity from the moment it is "
        "validated -- the Language Understanding module never needs to "
        "know anything about id assignment, and Memory/Execution never "
        "need to handle a missing id.",
    )
    metadata: TaskMetadata = Field(
        default_factory=TaskMetadata,
        description="Provenance and schema-version record for this "
        "task. See `schemas/metadata.py`. Populated automatically at "
        "construction time -- producers never need to set this "
        "explicitly.",
    )
    goal: Optional[str] = Field(
        default=None,
        description="The core intent of the task as a short snake_case "
        "verb phrase (e.g. 'pick_and_place', 'navigate_to'). This is "
        "what the Planner reads to select an action template; it is "
        "deliberately not free text so the Planner does not need NLP "
        "of its own.",
    )
    attributes: Optional[TaskAttributes] = Field(
        default=None,
        description="Descriptive qualifiers about the task's primary "
        "object. `None` when the instruction gave no descriptive "
        "qualifiers, rather than an attributes object with every field "
        "null.",
    )
    constraints: Optional[List[TaskConstraint]] = Field(
        default=None,
        description="Constraints explicitly stated or clearly implied "
        "by the instruction. `None` when the instruction stated no "
        "constraints; consumers must not infer generic constraints "
        "(e.g. obstacle avoidance) that are not represented here -- "
        "that reasoning belongs to the Planner and Execution layers, "
        "not to this interface.",
    )
    priority: Optional[TaskPriority] = Field(
        default=None,
        description="Urgency/importance signaled by the user's wording. "
        "`None` when the instruction carries no urgency language; the "
        "Planner should treat an unset priority as neutral, not as low.",
    )
    preconditions: Optional[List[str]] = Field(
        default=None,
        description="Conditions that must hold before the task can "
        "begin, only when explicitly stated or clearly implied (e.g. "
        "'once the room is empty'). Read by the Planner before "
        "scheduling and by Execution before dispatch.",
    )
    postconditions: Optional[List[str]] = Field(
        default=None,
        description="Conditions that define success beyond the "
        "immediate action, only when explicitly stated (e.g. 'make "
        "sure the lid is closed afterward'). Intended for the "
        "Reflection module to check against the world state after "
        "Execution reports completion.",
    )
    estimated_goal: Optional[str] = Field(
        default=None,
        description="A concise natural-language restatement of what "
        "the world should look like when this task succeeds, derived "
        "strictly from this task's other fields (never inventing new "
        "information). Intended as a human-readable and "
        "Reflection-module-readable success description -- not a "
        "replacement for a formal postcondition check.",
    )
    needs_clarification: bool = Field(
        default=False,
        description="True when the instruction underlying this task is "
        "ambiguous in a way that could lead to an incorrect action if "
        "the Planner proceeded without resolving it. Modules "
        "downstream of Language Understanding should treat this as a "
        "hard signal to pause and request clarification rather than "
        "guessing.",
    )
    clarification_reason: Optional[str] = Field(
        default=None,
        description="Explanation of the ambiguity, required whenever "
        "`needs_clarification` is True and `None` otherwise. Intended "
        "to be surfaced back to the user verbatim or used to prompt a "
        "targeted follow-up question.",
    )

    @field_validator("task_id", mode="before")
    @classmethod
    def _assign_task_id_if_missing(cls, value: Optional[str]) -> str:
        # `validate_default=True` on the field above is what makes this
        # validator run even when the caller omits `task_id` entirely
        # (Pydantic skips "before" validators for omitted fields by
        # default, applying the bare default instead) -- without it,
        # every Task built from a producer that doesn't set `task_id`
        # would stay `None` forever. This was verified empirically: see
        # the Phase 3.2 note in `language_interface_spec.md` section 14.
        #
        # A producer's explicit `"task_id": null` (which `parser_prompt.txt`
        # emits for every task per its "never omit a field" rule) and an
        # entirely omitted key must both resolve to a freshly generated
        # id -- this validator is the one place that happens, so no
        # downstream module ever has to handle a missing task_id.
        if value is None:
            return str(uuid4())
        stripped = value.strip()
        return stripped or str(uuid4())

    @field_validator("goal", mode="after")
    @classmethod
    def _validate_goal(cls, value: Optional[str]) -> Optional[str]:
        return validate_snake_case_goal(value)

    @field_validator("estimated_goal", mode="after")
    @classmethod
    def _normalize_estimated_goal(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("clarification_reason", mode="after")
    @classmethod
    def _normalize_clarification_reason(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("preconditions", "postconditions", mode="after")
    @classmethod
    def _normalize_condition_lists(
        cls, value: Optional[List[str]]
    ) -> Optional[List[str]]:
        return normalize_text_list(value)

    @model_validator(mode="after")
    def _check_clarification_consistency(self) -> "Task":
        # Cross-field invariant: `needs_clarification` and
        # `clarification_reason` must agree (see
        # `validators.validate_clarification_consistency` for the full
        # rationale). This has to be a model-level validator rather
        # than a field-level one because it depends on two fields at
        # once, and must run after both have already been normalized by
        # their own field validators above.
        validate_clarification_consistency(
            self.needs_clarification, self.clarification_reason
        )
        return self


class SingleTask(Task):
    """
    A task representing exactly one atomic goal extracted from a user
    instruction (e.g. "pick up the red mug from the counter").

    Purpose
        The leaf representation every subtask of a `MultiTask` also
        uses -- a `MultiTask` is a sequence of `SingleTask` objects
        rather than a separate nested shape, so the Planner has exactly
        one task representation to reason about regardless of whether
        it originated from a single- or multi-task instruction.

    Responsibilities
        Adds `object`, `target`, `source_location`, and
        `target_location` to everything `Task` already provides -- the
        fields specific to "one atomic goal acting on (at most) one
        primary object."

    Downstream consumers
        The Planner grounds `object`/`target`/`source_location`/
        `target_location` against a `Scene`'s `Detection`s to produce
        an executable action sequence (see `language_interface_spec.md`
        section 15, "Planner Integration"). Execution, Memory, and
        Reflection consume it the same way they consume any `Task`.
    """

    task_type: Literal[TaskType.SINGLE] = Field(
        default=TaskType.SINGLE,
        description="Discriminator value for this task representation.",
    )
    object: Optional[str] = Field(
        default=None,
        description="The primary object the action is performed on, "
        "preserved in the user's own wording. `None` when the "
        "instruction names no object (e.g. 'turn off the lights' has no "
        "manipulable object). Never populated with an object the user "
        "did not mention.",
    )
    target: Optional[str] = Field(
        default=None,
        description="A secondary object or entity the primary object is "
        "being related to, when different from `object` (e.g. for 'put "
        "the mug next to the toaster', object='mug', target='toaster'). "
        "`None` when the instruction has no secondary object.",
    )
    source_location: Optional[str] = Field(
        default=None,
        description="Where the object currently is or should be "
        "acquired from, only when stated or unambiguously implied. "
        "Read by the Planner to sequence navigation before "
        "manipulation.",
    )
    target_location: Optional[str] = Field(
        default=None,
        description="Where the object or robot should end up, only "
        "when stated or unambiguously implied. Read by the Planner to "
        "sequence manipulation before navigation, and by Reflection to "
        "verify final placement.",
    )

    @field_validator(
        "object", "target", "source_location", "target_location", mode="after"
    )
    @classmethod
    def _normalize_reference_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class MultiTask(Task):
    """
    A task representing two or more distinct goals extracted from a
    single user instruction (e.g. "pick up the cup, then take it to the
    office, and turn off the kitchen lights").

    Purpose
        Represent an instruction that decomposes into multiple atomic
        goals, while still giving the Planner exactly one leaf task
        shape (`SingleTask`) to reason about per goal.

    Responsibilities
        Add `subtasks` -- the ordered decomposition -- to everything
        `Task` already provides, and enforce that a `MultiTask` is
        never used to wrap a single goal (see
        `validate_subtask_count`).

    Downstream consumers
        The Planner iterates `subtasks` in order to build an action
        sequence, respecting each subtask's own `preconditions` for
        finer-grained sequencing. Memory and Reflection may track
        `subtasks` progress individually while still referencing the
        parent `MultiTask` by its own `task_id`.

    Design notes
        `subtasks` preserves the order implied by the instruction,
        since conjunctions like "then" or "after that" carry sequencing
        meaning the Planner is expected to respect by default. This
        model intentionally does not encode inter-subtask dependencies
        beyond ordering and each subtask's own `preconditions` -- richer
        dependency graphs are a Planner-level concern, not part of the
        Language Interface (see `language_interface_spec.md` section
        21, "Limitations").
    """

    task_type: Literal[TaskType.MULTI] = Field(
        default=TaskType.MULTI,
        description="Discriminator value for this task representation.",
    )
    subtasks: List[SingleTask] = Field(
        description="The ordered list of atomic tasks that make up this "
        "instruction. Order reflects the sequence implied by the user's "
        "wording and should be treated as the default execution order "
        "unless the Planner has an explicit reason to reorder. Must "
        "contain at least two entries -- a single-goal instruction "
        "should be represented as a SingleTask instead.",
    )

    @field_validator("subtasks", mode="after")
    @classmethod
    def _validate_subtask_count(cls, value: List[SingleTask]) -> List[SingleTask]:
        validate_subtask_count(value)
        return value


# A discriminated union of every concrete task representation the
# Language Understanding module may emit. Using `task_type` as the
# discriminator lets Pydantic pick `SingleTask` or `MultiTask` directly
# from raw parser output without the caller needing to branch on shape
# before validation -- e.g.
# `TypeAdapter(ParsedInstruction).validate_json(raw)` in a future
# Language Agent implementation (Phase 3.3+). Verified to resolve
# correctly for both concrete types, including the explicit-`null`
# `task_id` case every parser prompt response includes -- see
# `backend/tests/test_task.py`.
ParsedInstruction = Annotated[
    Union[SingleTask, MultiTask],
    Field(discriminator="task_type"),
]
