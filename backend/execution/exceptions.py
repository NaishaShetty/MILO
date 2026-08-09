"""
exceptions.py (backend/execution)

Purpose
-------
The closed hierarchy of exceptions this package raises for
programmer/configuration errors it cannot recover from on its own --
mirrors `planner/exceptions.py`'s split exactly: an ordinary "this step
failed" outcome is *returned* data (`execution.models.ActionResult`
with `success=False`, see `errors.py`'s docstring), never a raised
exception. Exceptions here are reserved for cases where there is no
sensible `ExecutionRecord` to return at all.
"""

from __future__ import annotations


class ExecutionRuntimeError(Exception):
    """Base class for every exception raised by `backend/execution/`."""


class PlanNotExecutableError(ExecutionRuntimeError):
    """
    Raised by `ExecutionController.load_plan()` when handed a `Plan`
    that is not in a startable state -- e.g. `PlanStatus.INVALID` (a
    plan `PlanValidator` already rejected) or a `Plan` with zero steps.
    Distinct from a step failing *during* execution, which is normal,
    reported outcome data, not an exception.
    """


class SimulatorUnavailableError(ExecutionRuntimeError):
    """
    Raised when an `ExecutionController` is asked to execute a plan
    with no `Simulator` configured/started. This is a deployment
    configuration problem (mirrors `api/app.py`'s
    `VISION_ENABLE_SIMULATOR` gate), not a plan or step defect.
    """
