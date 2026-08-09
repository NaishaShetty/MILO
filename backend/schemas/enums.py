"""
enums.py

Purpose
-------
Centralizes every closed vocabulary used by the Language Interface
(`schemas/task.py`) into typed `Enum` classes. Before this file existed,
`TaskPriority` and `ConstraintType` lived inline inside `task.py`
alongside the models that used them; they were split out once a second
concern (`schemas/metadata.py`, `schemas/validators.py`) needed to
reference `TaskType` too, and duplicating the same enum definition
across files invites exactly the kind of silent-typo drift this file
exists to prevent.

Why enums instead of raw strings
---------------------------------
A raw string field (`priority: Optional[str]`) accepts `"hgih"` just as
happily as `"high"` -- the typo fails silently, and by the time a
Planner or Reflection module notices, the task has already been
mis-prioritized. Every enum below is validated by Pydantic at model
construction time, so a malformed value raises a `ValidationError`
immediately, at the boundary where the data entered the system, rather
than surfacing as a confusing bug three modules downstream. This is the
same rationale `scene/metadata_keys.py` uses for centralizing
`Scene.metadata` keys -- see `docs/architecture/api_contracts.md`.

Why `str, Enum` rather than a plain `Enum`
--------------------------------------------
Every enum here subclasses both `str` and `Enum`. That means a member
compares equal to, and serializes as, its plain string value
(`TaskPriority.HIGH == "high"` is `True`, and
`json.dumps(TaskPriority.HIGH)` emits `"high"` when used inside a
Pydantic model's `model_dump(mode="json")`). Downstream modules that
have not been written yet (Planner, Execution, Memory, Reflection) can
therefore treat these fields as ordinary strings if that is more
convenient for a given call site, without needing to import this module
just to do an equality check -- the enum only pays for itself at the
validation boundary.

Downstream consumers
---------------------
Every enum in this file is part of the Language Interface's public
contract (see `backend/docs/language_interface_spec.md`). The Planner
is expected to branch on `TaskType`/`ConstraintType` to decide how to
handle a task or constraint; Reflection and Memory are expected to read
`TaskPriority` when deciding retry/ordering behavior. None of those
modules exist yet as of Phase 3.2 -- this file is written so they have
a stable vocabulary to import against once they do.
"""

from enum import Enum


class TaskType(str, Enum):
    """
    Discriminator values identifying which concrete task representation
    a JSON payload encodes: a single atomic goal, or a decomposition
    into multiple atomic goals.

    This is the enum backing `Task.task_type`, `SingleTask.task_type`,
    and `MultiTask.task_type` in `schemas/task.py`, and the field
    `ParsedInstruction` (the discriminated union in that same file) uses
    to pick which concrete model to validate incoming JSON against.
    Kept as a two-member closed set deliberately: a task either is one
    goal or is a sequence of them, and any richer task topology (e.g. a
    dependency graph) is intentionally out of scope for this interface
    -- see `language_interface_spec.md` section 21 ("Limitations").
    """

    SINGLE = "single"
    MULTI = "multi"


class TaskPriority(str, Enum):
    """
    Urgency/importance levels a task may be assigned.

    Only populated when the user's wording actually signals urgency
    (see `parser_prompt.txt`'s field definitions); the Planner is
    expected to use this to order or preempt work, and the Reflection
    module may use it to decide how aggressively to retry a failed
    task. A task with no priority language in its source instruction
    should carry `None`, not a default of `TaskPriority.MEDIUM` --
    collapsing "unstated" into a specific priority would let the schema
    invent information the user never gave, which the whole Language
    Interface is built to avoid (see `language_interface_spec.md`
    section 6, "no invented information").
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConstraintType(str, Enum):
    """
    Categories of constraint a `TaskConstraint` (`schemas/task.py`) may
    express.

    Kept as a closed vocabulary (rather than a free-form string) so the
    Planner can dispatch on constraint category -- e.g. routing
    `SAFETY` constraints to a different validation path than `ORDERING`
    constraints -- without parsing natural language at planning time.
    `CUSTOM` is the deliberate escape hatch for constraint kinds this
    enum has not anticipated yet, so the Language Understanding module
    is never blocked on a schema change to express an unusual
    constraint; a future phase noticing repeated `CUSTOM` usage for the
    same kind of constraint is the signal to promote it to a first-class
    member here.
    """

    SPATIAL = "spatial"
    TEMPORAL = "temporal"
    SAFETY = "safety"
    RESOURCE = "resource"
    ORDERING = "ordering"
    CUSTOM = "custom"
