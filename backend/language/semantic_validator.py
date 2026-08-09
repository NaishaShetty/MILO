"""
semantic_validator.py

Purpose
-------
Adds a lightweight semantic-plausibility check on top of Phase 3.2's
structural `ParsedInstruction` validation (`schema_validator.py`).
Structural validity only guarantees a response has the *shape* of a
task; it says nothing about whether that shape makes sense. A
`SingleTask(goal="bring", object=None, target=None,
needs_clarification=False)` is a perfectly valid `SingleTask` by
Pydantic's rules -- every field is the right type -- yet it claims to
be an unambiguous instruction to bring an unspecified thing to an
unspecified someone, which no Planner could act on. This module is
where that gap gets caught, independently of `SchemaValidator`.

Why this is a separate component from `SchemaValidator`
------------------------------------------------------------
Phase 3.2's schema (`schemas/task.py`) is a closed, heavily-tested
contract (70+ cases) that this project has committed to not
duplicating or re-implementing (see `schema_validator.py`'s own
docstring). Semantic plausibility is a genuinely different concern --
it is about the *combination* of field values an LLM produced for one
specific parse, not about the shape every `Task` must have -- so it
belongs in its own file with its own narrow, documented rule set,
called strictly *after* `SchemaValidator` has already produced a real
`SingleTask`/`MultiTask` to inspect.

Design principle: conservative and narrow, not "world reasoning"
----------------------------------------------------------------------
This module explicitly does not attempt general commonsense reasoning
about tasks (per this phase's scope: "Do not attempt full world
reasoning"). Every rule below is a small, named, testable check against
a curated set of situations the Phase 3.5 requirements call out by
name: a manipulation goal with no object or target, a task whose
`object` and `target` name the same thing, and a `MultiTask` whose own
`needs_clarification` disagrees with what its subtasks actually say.
Rules are deliberately conservative -- narrow enough that a legitimate
task with no object (e.g. `goal="navigate_to"`) is never flagged --
because a false positive here means a valid instruction gets rejected
or retried for no reason, which is worse than missing an edge case.

Which component depends on this file
---------------------------------------
`recovery.py` calls `SemanticValidator.validate()` immediately after a
successful `SchemaValidator.validate()` call, inside the same
retry-eligible attempt loop -- a `SemanticValidationError` is treated
as a recoverable failure (see `failures.py`'s `is_retryable`), not a
different kind of hard stop. `LanguageAgent` never calls this class
directly; wiring it in is opt-in (see `agent.py`'s constructor) so
Phase 3.4's existing behavior is unchanged for any caller that does not
explicitly enable it.
"""

from __future__ import annotations

from typing import FrozenSet

from language.exceptions import SemanticValidationError
from schemas.task import MultiTask, ParsedInstruction, SingleTask

# Goals that, by their own meaning, always act on a specific object
# (you cannot "bring" nothing). Deliberately a small, explicit,
# hand-curated set rather than a heuristic over the verb string --
# see this module's docstring on staying conservative. Extending this
# set is a deliberate content decision, not something this module
# infers on its own.
_OBJECT_REQUIRED_GOALS: FrozenSet[str] = frozenset(
    {"bring", "fetch_and_deliver", "hand_over", "deliver", "give"}
)


def _validate_single(task: SingleTask) -> None:
    """
    Applies every single-task semantic rule to one `SingleTask` --
    shared between validating a standalone `SingleTask` and validating
    each subtask of a `MultiTask`, so the two never drift apart.
    """
    # Rule 1: a manipulation goal with neither an object nor a target
    # and no clarification flagged is an instruction the model claims
    # to have fully understood, yet gave itself nothing to act on --
    # see this module's docstring for why this set is small and
    # explicit.
    if (
        task.goal in _OBJECT_REQUIRED_GOALS
        and task.object is None
        and task.target is None
        and not task.needs_clarification
    ):
        raise SemanticValidationError(
            f"Task goal {task.goal!r} requires an 'object' or 'target' "
            "to act on, but both are null and needs_clarification is "
            "False -- this task cannot be executed as stated."
        )

    # Rule 2: an object cannot be its own target (e.g. "put the mug on
    # the mug"). This is a contradiction in the extracted fields, not a
    # plausible instruction -- see this module's docstring's "impossible
    # task representation" example.
    if (
        task.object is not None
        and task.target is not None
        and task.object.strip().lower() == task.target.strip().lower()
    ):
        raise SemanticValidationError(
            f"Task object and target are both {task.object!r} -- an "
            "object cannot be its own target."
        )


class SemanticValidator:
    """
    Stateless semantic-plausibility checker for an already
    structurally-valid `ParsedInstruction`. No constructor arguments,
    mirroring `SchemaValidator`/`ResponseParser` -- this class holds no
    state between calls, only a name and a place to attach tests.
    """

    def validate(self, instruction: ParsedInstruction) -> None:
        """
        Raises `SemanticValidationError` if `instruction` fails any
        semantic rule; returns `None` (no return value) on success,
        matching `SchemaValidator`'s error-signaling convention of
        "raise on failure" rather than a boolean/result type the
        caller would have to remember to check.
        """
        if isinstance(instruction, SingleTask):
            _validate_single(instruction)
            return

        # MultiTask: validate every subtask individually (each is a
        # SingleTask in its own right -- see schemas/task.py), plus one
        # multi-task-specific invariant below.
        multi: MultiTask = instruction
        for subtask in multi.subtasks:
            _validate_single(subtask)

        # Rule 3: a MultiTask that itself claims no clarification is
        # needed, while every one of its subtasks independently says
        # it does, is internally contradictory -- the parent's
        # confidence is not supported by its own decomposition.
        if not multi.needs_clarification and multi.subtasks:
            if all(subtask.needs_clarification for subtask in multi.subtasks):
                raise SemanticValidationError(
                    "MultiTask reports needs_clarification=False, but "
                    "every one of its subtasks reports "
                    "needs_clarification=True -- an inconsistent "
                    "clarification state."
                )
