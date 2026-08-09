"""
validators.py

Purpose
-------
Holds the reusable validation *logic* the Language Interface models
(`schemas/task.py`) apply to their fields, as plain functions rather
than duplicated inline in every `@field_validator`/`@model_validator`.
`task.py` wires these functions into its models; this file owns no
Pydantic model definitions of its own.

Why this is a separate file from `task.py`
--------------------------------------------
Several fields across `TaskAttributes`, `TaskConstraint`, `SingleTask`,
and `MultiTask` share the same normalization or invariant-checking
need -- e.g. `SingleTask.object`, `SingleTask.target`,
`SingleTask.source_location`, and `TaskConstraint.value` all need the
same "empty string means unset, not a value" normalization. Writing
that logic once here and calling it from each field validator means a
future bug fix or refinement (e.g. also stripping surrounding quote
characters an LLM sometimes emits) happens in one place and applies
everywhere automatically, instead of needing to be copy-pasted into
every validator that needs it and inevitably drifting out of sync.

Design principle: normalize permissively, validate strictly
--------------------------------------------------------------
Two different failure modes show up in LLM-produced JSON, and this
file treats them differently on purpose:

1. **Formatting noise in optional data** (an empty string instead of
   `null`, stray leading/trailing whitespace). This is not a
   correctness problem -- the parser prompt already instructs the LLM
   to use `null` for unset fields, but LLMs do not always follow
   instructions exactly. The functions handling this
   (`normalize_optional_text`, `normalize_text_list`) *repair* the
   value rather than rejecting it, collapsing every "nothing was said
   here" representation down to the one canonical form (`None`) the
   rest of the codebase can rely on.
2. **Violations of a structural invariant** (a `TaskConstraint` with no
   description, a `MultiTask` with only one subtask, `needs_clarification`
   set without a reason). These are not formatting noise -- they
   indicate the payload cannot be trusted to mean what its shape
   claims. The functions handling this
   (`require_non_empty_text`, `validate_clarification_consistency`,
   `validate_subtask_count`) raise `ValueError`, which Pydantic
   converts into a `ValidationError` with a clear, attributable message
   pointing at the offending field.

Downstream consumers
---------------------
None directly -- this module exists purely to be imported by
`schemas/task.py`. No future module (Planner, Execution, Memory,
Reflection) should need to import `validators.py` itself; if a future
module needs the same normalization behavior for its own input, that is
a signal the logic belongs in a more general-purpose shared utility,
not that this file should grow unrelated responsibilities.
"""

import re
from typing import List, Optional, Sequence

from pydantic import BaseModel

# A `goal` is a snake_case verb phrase per the parser prompt's contract
# (`backend/prompts/parser_prompt.txt`, FIELD DEFINITIONS section):
# lowercase letters/digits, words separated by single underscores, no
# leading/trailing/doubled underscores. Compiled once at module import
# time since every `Task`/`SingleTask`/`MultiTask` validation reuses it.
_SNAKE_CASE_PATTERN = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")

# A `MultiTask` exists specifically to represent *more than one* atomic
# goal; an instruction with exactly one goal must be represented as a
# `SingleTask` instead (see `language_interface_spec.md` section 9,
# "Single Task Representation" vs "Multi Task Representation"). This
# constant is the single place that threshold is recorded, rather than
# a magic `2` appearing inline in a validator.
MIN_MULTITASK_SUBTASKS = 2


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """
    Collapse "no information here" to exactly one representation:
    `None`.

    Why it exists
        An optional free-text field (`SingleTask.object`,
        `TaskConstraint.value`, `TaskAttributes.color`, ...) can arrive
        as `null`, an empty string, or a whitespace-only string -- all
        three mean the same thing ("this was not stated"), but only
        `None` is the canonical representation the rest of this schema
        (and every future downstream consumer) is documented to expect.
        Without this normalization, a consumer would need to check
        `value is None or not value.strip()` at every read site instead
        of a single `value is None` check.

    What invariant it enforces
        After this function runs, a field's value is either non-empty
        stripped text, or `None`. It never returns an empty or
        whitespace-only string.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_text_list(values: Optional[List[str]]) -> Optional[List[str]]:
    """
    Apply `normalize_optional_text` to every element of an optional
    string list, dropping any element that normalizes to `None`.

    Why it exists
        `TaskAttributes.descriptors`, `Task.preconditions`, and
        `Task.postconditions` are all optional lists of free text
        produced from natural language, where the same "empty string
        noise" problem `normalize_optional_text` solves for a single
        field can also occur per-element (e.g. a trailing empty string
        in a list the LLM emitted). Centralizing this here means a list
        field's validator is a one-line call instead of re-implementing
        the same filter/strip loop three times.

    What invariant it enforces
        Returns `None` for `None` input or for a list that contains no
        genuine content after normalization (never an empty list `[]`)
        -- consistent with this schema's rule that "no information"
        is always represented as `None`, never an empty container.
    """
    if values is None:
        return None
    normalized = [normalize_optional_text(item) for item in values]
    cleaned = [item for item in normalized if item is not None]
    return cleaned or None


def require_non_empty_text(value: str, *, field_name: str) -> str:
    """
    Guarantee a *required* text field actually carries content.

    Why it exists
        Pydantic's plain `str` type happily accepts `""` as a valid
        value -- it is syntactically a string. But a `TaskConstraint`
        with `description=""` is not a usable constraint; it claims to
        describe something and describes nothing. This function is the
        boundary that turns that silent acceptance into an explicit,
        attributable validation failure.

    What invariant it enforces
        The returned value is always non-empty after stripping
        whitespace. Raises `ValueError` (which Pydantic wraps into a
        `ValidationError` naming the offending field) otherwise.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty or whitespace-only.")
    return stripped


def validate_snake_case_goal(value: Optional[str]) -> Optional[str]:
    """
    Normalize and validate `Task.goal` against the snake_case
    verb-phrase convention `parser_prompt.txt` mandates.

    Why it exists
        The Planner (a future module) is expected to use `goal` as a
        dispatch key -- e.g. mapping `"pick_and_place"` to a specific
        action template -- not as free text to re-parse. If arbitrary
        casing or punctuation were allowed through
        (`"Pick And Place"`, `"pick-and-place"`), every future consumer
        of `goal` would need its own normalization step, and two
        semantically identical goals could fail to compare equal. This
        validator makes "goal is a well-formed dispatch key" a
        guarantee of the schema itself, not a convention every future
        caller must remember to enforce.

    What invariant it enforces
        `None` passes through unchanged (goal is optional -- see
        "missing information -> null" in `language_interface_spec.md`
        section 13). A non-`None` value is lowercased, stripped, and
        must match `^[a-z0-9]+(_[a-z0-9]+)*$` -- lowercase
        alphanumeric words joined by single underscores, no leading,
        trailing, or doubled underscores. Raises `ValueError` with the
        offending value included in the message otherwise.
    """
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not _SNAKE_CASE_PATTERN.match(normalized):
        raise ValueError(
            "goal must be a lowercase snake_case verb phrase "
            f"(e.g. 'pick_and_place', 'navigate_to'); got {value!r}."
        )
    return normalized


def validate_clarification_consistency(
    needs_clarification: bool, clarification_reason: Optional[str]
) -> None:
    """
    Enforce that `clarification_reason` is present exactly when
    `needs_clarification` is `True`.

    Why it exists
        These two fields are read together by every downstream
        consumer (a Planner deciding whether to pause, a UI deciding
        whether to surface a follow-up question) -- see
        `language_interface_spec.md` section 12, "Ambiguity Handling".
        If they could disagree (`needs_clarification=True` with no
        reason, or a reason present but the flag `False`), a consumer
        would have to reconcile two independent booleans-worth of
        information instead of trusting one field as authoritative.
        This validator makes that disagreement impossible to construct
        in the first place, rather than relying on every future
        consumer to defensively re-check consistency itself.

    What invariant it enforces
        `needs_clarification=True` requires a non-empty
        `clarification_reason`. `needs_clarification=False` requires
        `clarification_reason` to be `None`. Raises `ValueError`
        (surfaced by the caller as part of a `ValidationError`) for
        either violation, with a message naming which side of the
        invariant failed.
    """
    if needs_clarification and not (
        clarification_reason and clarification_reason.strip()
    ):
        raise ValueError(
            "clarification_reason is required and must be non-empty "
            "when needs_clarification is True."
        )
    if not needs_clarification and clarification_reason:
        raise ValueError(
            "clarification_reason must be None when needs_clarification "
            "is False -- ambiguity that isn't flagged shouldn't carry "
            "an explanation."
        )


def validate_subtask_count(subtasks: Sequence[BaseModel]) -> None:
    """
    Enforce that a `MultiTask` actually represents more than one goal.

    Why it exists
        `MultiTask` and `SingleTask` both exist so the Planner never
        needs to guess whether an instruction was "really" one goal or
        several -- but that guarantee only holds if `MultiTask` is
        never used to wrap a single goal. Without this check, a
        producer could construct a `MultiTask` with one subtask, and
        every downstream consumer would need to defensively handle that
        degenerate case even though `SingleTask` already exists
        specifically to represent it.

    What invariant it enforces
        `len(subtasks) >= MIN_MULTITASK_SUBTASKS` (currently 2). Raises
        `ValueError` naming the actual count and the required minimum
        otherwise.
    """
    if len(subtasks) < MIN_MULTITASK_SUBTASKS:
        raise ValueError(
            f"MultiTask requires at least {MIN_MULTITASK_SUBTASKS} subtasks "
            f"(got {len(subtasks)}); an instruction with a single goal "
            "should be represented as a SingleTask instead."
        )
