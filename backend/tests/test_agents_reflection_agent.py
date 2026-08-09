"""
test_agents_reflection_agent.py

Purpose
-------
Unit tests for `agents.reflection_agent.ReflectionAgent.reflect()`:
each of the seven documented rules (success -> continue; no cause ->
abort; INVALID_ACTION/INVALID_PLAN -> abort; attempts exhausted ->
abort; PATH_BLOCKED/NAVIGATION_FAILURE/OBJECT_NOT_FOUND/
ENVIRONMENT_CHANGED -> replan; recoverable -> retry; else -> abort).
"""

from __future__ import annotations

from agents.failures import AgentFailure, FailureCategory
from agents.reflection_agent import ReflectionAgent
from execution.models import ExecutionRecord, ExecutionStatus


def _failed_record():
    return ExecutionRecord(plan_id="p1", task_id="t1", status=ExecutionStatus.FAILED)


def _failure(category: FailureCategory, *, recoverable: bool = False) -> AgentFailure:
    return AgentFailure(
        category=category, message="boom", agent="execution", recoverable=recoverable
    )


def test_success_recommends_continue_and_store_memory():
    agent = ReflectionAgent()
    record = ExecutionRecord(plan_id="p1", task_id="t1", status=ExecutionStatus.SUCCESS)
    result = agent.reflect(record, [], attempt=0, max_attempts=2)
    assert result.success is True
    assert result.action == "continue"
    assert result.store_memory is True


def test_no_failures_recorded_aborts():
    agent = ReflectionAgent()
    result = agent.reflect(_failed_record(), [], attempt=0, max_attempts=2)
    assert result.action == "abort"
    assert result.store_memory is True


def test_invalid_plan_aborts_even_with_attempts_remaining():
    agent = ReflectionAgent()
    result = agent.reflect(
        _failed_record(),
        [_failure(FailureCategory.INVALID_PLAN, recoverable=True)],
        attempt=0,
        max_attempts=5,
    )
    assert result.action == "abort"


def test_attempts_exhausted_aborts_even_for_a_replannable_category():
    agent = ReflectionAgent()
    result = agent.reflect(
        _failed_record(),
        [_failure(FailureCategory.PATH_BLOCKED, recoverable=True)],
        attempt=2,
        max_attempts=2,
    )
    assert result.action == "abort"
    assert "exhausted" in result.reason


def test_path_blocked_recommends_replan_without_storing_memory_yet():
    agent = ReflectionAgent()
    result = agent.reflect(
        _failed_record(),
        [_failure(FailureCategory.PATH_BLOCKED, recoverable=True)],
        attempt=0,
        max_attempts=2,
    )
    assert result.action == "replan"
    assert result.store_memory is False


def test_recoverable_non_replan_category_recommends_retry():
    agent = ReflectionAgent()
    result = agent.reflect(
        _failed_record(),
        [_failure(FailureCategory.ACTION_FAILURE, recoverable=True)],
        attempt=0,
        max_attempts=2,
    )
    assert result.action == "retry"
    assert result.store_memory is False


def test_non_recoverable_non_replan_category_aborts():
    agent = ReflectionAgent()
    result = agent.reflect(
        _failed_record(),
        [_failure(FailureCategory.ACTION_FAILURE, recoverable=False)],
        attempt=0,
        max_attempts=2,
    )
    assert result.action == "abort"
    assert result.store_memory is True
