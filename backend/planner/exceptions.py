"""
exceptions.py (backend/planner)

Purpose
-------
Defines the closed hierarchy of exceptions this package raises. Mirrors
the pattern already established by `language/exceptions.py`: every
planner-facing failure is a `PlanningError` subclass, so a caller (the
API layer, a test, a future Phase 5 integration) can catch one base
type and still branch on the specific failure via `isinstance` when it
needs to. No bare `Exception`/`ValueError` should ever cross this
package's boundary.

Why a closed hierarchy instead of return codes
------------------------------------------------
`Planner.plan()` returns a `PlanningResult` (see `models.py`) for
*planning* outcomes -- a plan that cannot be validated, or a goal that
cannot be achieved, is reported as `PlanningResult(success=False, ...)`,
never as a raised exception. Exceptions here are reserved for
programmer/configuration errors this package cannot recover from on its
own: a task missing fields the requested goal needs, a goal with no
known planning strategy, a planner timing out, or an LLM-backed planner
receiving output it cannot make sense of even after retrying. This
split matches `language/agent.py`'s "a task with needs_clarification=True
is a successful parse" precedent -- a planner producing *no* usable
plan is business-as-usual output, not a Python exception.
"""

from __future__ import annotations

from typing import Optional


class PlanningError(Exception):
    """Base class for every exception raised by `backend/planner/`."""


class InvalidTaskError(PlanningError):
    """
    Raised when the `SingleTask` handed to a planner is missing a field
    its goal requires (e.g. `goal="store"` with `object=None`), or
    carries a `task_type`/shape a planner cannot operate on (e.g. a
    bare `MultiTask` handed directly to a planner that only accepts one
    `SingleTask` at a time -- callers are expected to iterate a
    `MultiTask.subtasks` themselves, see `planner.py`).
    """


class UnsupportedGoalError(PlanningError):
    """
    Raised when a task's `goal` does not match any template a planner
    knows how to expand, and no generic fallback applies either. Kept
    distinct from `InvalidTaskError` (a *shape* problem) because this
    is a *coverage* problem: the planner's goal vocabulary needs a new
    entry, not the task data itself needing to change.
    """


class PlanValidationError(PlanningError):
    """
    Raised only when a planning strategy cannot proceed *because* an
    intermediate plan is invalid (e.g. a ReAct iteration that cannot
    recover from a precondition failure after its repair budget is
    exhausted). Routine "here is a plan and here is why it's invalid"
    reporting goes through `ValidationResult` (`models.py`), not this
    exception -- see this module's docstring.
    """

    def __init__(self, message: str, *, step_id: Optional[int] = None) -> None:
        super().__init__(message)
        self.step_id = step_id


class PlanningTimeoutError(PlanningError):
    """Raised when a planner exceeds its configured time/iteration budget."""


class LLMUnavailableError(PlanningError):
    """
    Raised by `ReActPlanner` when no `LLMClient` is configured, or the
    configured client raises a `language.exceptions.LanguageRuntimeError`
    (network failure, missing credentials, provider error). Callers
    that want the "still fully testable without a live LLM" guarantee
    this project requires should catch this and fall back to
    `RuleBasedPlanner` -- `ReActPlanner` itself supports this directly
    via its optional `fallback_planner` constructor argument (see
    `react.py`).
    """


class MalformedLLMOutputError(PlanningError):
    """
    Raised by `ReActPlanner` when the LLM's structured output cannot be
    parsed as JSON, does not match the expected action-proposal shape,
    or names an action/parameter this package does not recognize --
    even after the planner's bounded repair-retry budget is exhausted.
    Never allows arbitrary LLM text to be treated as an executable
    step; see `react.py`'s module docstring for the full contract.
    """
