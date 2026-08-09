"""
test_agents_failures.py

Purpose
-------
Unit tests for `agents.failures`: exhaustive `ExecutionErrorCode` ->
`FailureCategory` mapping coverage, and `AgentFailure` construction.
"""

from __future__ import annotations

from agents.failures import AgentFailure, FailureCategory, from_execution_error
from execution.errors import ExecutionErrorCode


def test_every_execution_error_code_maps_to_a_failure_category():
    for code in ExecutionErrorCode:
        failure = from_execution_error(code, message="x")
        assert isinstance(failure.category, FailureCategory)


def test_navigation_failed_maps_to_navigation_failure():
    failure = from_execution_error(
        ExecutionErrorCode.NAVIGATION_FAILED, message="blocked", agent="execution"
    )
    assert failure.category == FailureCategory.NAVIGATION_FAILURE
    assert failure.agent == "execution"


def test_unknown_error_maps_to_unknown_failure():
    failure = from_execution_error(ExecutionErrorCode.UNKNOWN_ERROR, message="?")
    assert failure.category == FailureCategory.UNKNOWN_FAILURE


def test_agent_failure_recoverable_and_details_pass_through():
    failure = AgentFailure(
        category=FailureCategory.PATH_BLOCKED,
        message="chair blocked route",
        agent="navigation",
        recoverable=True,
        details={"blocking_object": "Chair|1"},
    )
    assert failure.recoverable is True
    assert failure.details["blocking_object"] == "Chair|1"
