"""
test_planner_react.py

Purpose
-------
Unit tests for `planner/react.py`'s `ReActPlanner`, using a hand-written
fake `LLMClient` -- matching this project's existing convention
(`backend/language/`'s test suite) of testing LLM-dependent code with
zero network access and zero mocking frameworks. Covers section 14's
"ReAct" bullets: structured output accepted end to end, invalid/
malformed LLM output triggering the repair loop and then fallback, no
LLM configured falling back immediately, and a precondition-violating
proposal being rejected rather than silently accepted.

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_react.py -v
"""

import json

from language.llm_client import LLMResponse
from memory.agent import PlannerMemoryContext
from memory.models import MemoryProvenance
from memory.retrieval import MemoryResult
from memory.semantics import build_semantic_memory
from planner.react import ReActPlanner
from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from schemas.task import SingleTask

TASK = SingleTask(goal="pick_up", object="mug")

_VALID_SEQUENCE = [
    {"action": "locate", "target": "mug", "parameters": {}, "done": False},
    {"action": "navigate", "target": "mug", "parameters": {}, "done": False},
    {"action": "pickup", "target": "mug", "parameters": {}, "done": True},
]


class ScriptedClient:
    """Fake LLMClient returning one scripted JSON response per call."""

    def __init__(self, responses):
        self._responses = [
            json.dumps(r) if isinstance(r, dict) else r for r in responses
        ]
        self.calls = 0
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        content = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return LLMResponse(
            content=content, provider="fake", model="fake", latency_ms=0.1
        )


def test_structured_output_accepted_end_to_end():
    client = ScriptedClient(_VALID_SEQUENCE)
    planner = ReActPlanner(llm_client=client)
    result = planner.plan(TASK, WorldState.initial())
    assert result.success
    assert [s.action for s in result.plan.steps] == ["locate", "navigate", "pickup"]
    assert result.plan.metadata.get("react_fallback") is None


def test_malformed_json_triggers_repair_then_recovers():
    client = ScriptedClient(["not json"] + [json.dumps(r) for r in _VALID_SEQUENCE])
    planner = ReActPlanner(llm_client=client, repair_attempts=2)
    result = planner.plan(TASK, WorldState.initial())
    assert result.success
    assert client.calls >= len(_VALID_SEQUENCE) + 1


def test_persistently_malformed_output_falls_back_to_rule_based():
    client = ScriptedClient(["still not json"])
    planner = ReActPlanner(
        llm_client=client, fallback_planner=RuleBasedPlanner(), repair_attempts=1
    )
    result = planner.plan(TASK, WorldState.initial())
    assert result.success
    assert result.plan.metadata["react_fallback"] is True
    assert result.plan.planner_type == "react"


def test_persistently_malformed_output_with_no_fallback_fails_cleanly():
    client = ScriptedClient(["still not json"])
    planner = ReActPlanner(llm_client=client, fallback_planner=None, repair_attempts=0)
    result = planner.plan(TASK, WorldState.initial())
    assert not result.success
    assert result.plan is None
    assert result.errors


def test_no_llm_client_falls_back_immediately():
    planner = ReActPlanner(llm_client=None, fallback_planner=RuleBasedPlanner())
    result = planner.plan(TASK, WorldState.initial())
    assert result.success
    assert result.plan.metadata["react_fallback"] is True


def test_precondition_violating_proposal_is_rejected_not_accepted():
    # Proposes "pickup" before ever locating/navigating -- must be
    # rejected by _validate_proposal_shape, not silently accepted.
    bad_then_good = [
        {"action": "pickup", "target": "mug", "parameters": {}, "done": False},
    ] + _VALID_SEQUENCE
    client = ScriptedClient(bad_then_good)
    planner = ReActPlanner(llm_client=client, repair_attempts=3)
    result = planner.plan(TASK, WorldState.initial())
    assert result.success
    assert [s.action for s in result.plan.steps] == ["locate", "navigate", "pickup"]


def test_unrecognized_action_name_is_rejected():
    client = ScriptedClient(
        [{"action": "teleport", "target": "mug", "parameters": {}, "done": False}]
        + _VALID_SEQUENCE
    )
    planner = ReActPlanner(llm_client=client, repair_attempts=3)
    result = planner.plan(TASK, WorldState.initial())
    assert result.success


def test_memory_context_is_threaded_into_the_prompt():
    # Regression test: ReActPlanner.plan() used to accept memory_context
    # only for interface consistency and never actually use it -- the
    # LLM prompt looked identical whether or not memory was supplied.
    memory = build_semantic_memory(
        "mug",
        "located_on",
        "counter",
        provenance=MemoryProvenance.OBSERVATION,
        confidence=0.9,
    )
    result = MemoryResult(
        memory=memory,
        similarity=0.8,
        final_score=0.85,
        ranking_components={},
        retrieval_metadata={},
    )
    memory_context = PlannerMemoryContext(query="mug", results=[result])

    client = ScriptedClient(_VALID_SEQUENCE)
    planner = ReActPlanner(llm_client=client)
    result_ = planner.plan(TASK, WorldState.initial(), memory_context=memory_context)

    assert result_.success
    assert client.requests, "LLM should have been called"
    assert memory.content in client.requests[0].system_prompt

    # No memory supplied -> prompt still valid, but no hint content.
    client_no_memory = ScriptedClient(_VALID_SEQUENCE)
    planner_no_memory = ReActPlanner(llm_client=client_no_memory)
    planner_no_memory.plan(TASK, WorldState.initial())
    assert "[]" in client_no_memory.requests[0].system_prompt


# ---------------------------------------------------------------------
# Raw completion logging (module docstring's "Raw completion logging"
# section) -- closes the gap a real failure investigation hit
# (phase_e_milo_benchmark_report.md's Addendum 8, which had to re-run
# episodes with a one-off diagnostic client just to see what a model
# had actually proposed, because nothing persisted that text). These
# tests confirm the raw text is actually readable from real log output
# at the right level, not just that the logging call itself doesn't
# raise.
# ---------------------------------------------------------------------


def test_raw_completion_is_captured_and_readable_at_debug_level(caplog):
    distinctive_content = json.dumps(
        {"action": "not_a_real_action", "target": "mug", "parameters": {}}
    )
    client = ScriptedClient([distinctive_content] + _VALID_SEQUENCE)
    planner = ReActPlanner(llm_client=client, repair_attempts=3)

    with caplog.at_level("DEBUG", logger="planner.react"):
        result = planner.plan(TASK, WorldState.initial())

    assert result.success
    # The exact raw completion text must appear verbatim in the
    # rendered log output -- not just recorded as an opaque `extra=`
    # field a default formatter would drop.
    assert distinctive_content in caplog.text
    assert "planner.react.raw_completion" in caplog.text
    assert f"task_id={TASK.task_id}" in caplog.text


def test_raw_completion_is_silent_at_default_warning_level(caplog):
    # Gating check: at this project's normal/default logging level
    # (WARNING), the raw-completion DEBUG line must produce no output
    # at all -- it should never bloat normal logs unless a caller
    # explicitly opts into DEBUG for this logger.
    distinctive_content = json.dumps(
        {"action": "not_a_real_action", "target": "mug", "parameters": {}}
    )
    client = ScriptedClient([distinctive_content] + _VALID_SEQUENCE)
    planner = ReActPlanner(llm_client=client, repair_attempts=3)

    with caplog.at_level("WARNING", logger="planner.react"):
        result = planner.plan(TASK, WorldState.initial())

    assert result.success
    assert "planner.react.raw_completion" not in caplog.text
    assert distinctive_content not in caplog.text
    # The short summary WARNING (no raw content) still fires as before.
    assert "planner.react.malformed_output" in caplog.text
