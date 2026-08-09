"""
react.py (backend/planner)

Purpose
-------
Implements `ReActPlanner`: an LLM-driven iterative planning strategy
that follows the same `planner.Planner` interface as
`RuleBasedPlanner`/`BehaviorTreePlanner`. Each iteration asks the LLM to
reason about the current symbolic `state.WorldState` and the task's
goal, then propose exactly ONE next action as structured JSON. That
proposal is validated against `actions.ACTION_REGISTRY` and its
preconditions BEFORE it is ever accepted as a `models.PlanStep` -- the
LLM never executes anything, never emits Python, and never bypasses
this package's action model. This is section 10's "the LLM must
produce structured planning output that is validated by the planner
framework" requirement, applied literally.

Reusing the existing LLM abstraction
--------------------------------------
This module deliberately reuses `language.llm_client.LLMClient` /
`LLMRequest` / `LLMResponse` (Phase 3.4) rather than inventing a new LLM
abstraction -- see section 10: "If the existing project has a local
Qwen integration, reuse it rather than creating an unrelated LLM
abstraction." `language.llm_client.OpenAICompatibleLLMClient` already
targets any OpenAI-API-compatible endpoint, which is exactly how a
self-hosted Qwen/Llama server is meant to be reached in this project
(see that module's own docstring); `ReActPlanner` only adds a
planning-specific system prompt and a small structured-output parser on
top of the same `LLMClient` protocol, never a second HTTP client.

Iteration loop
--------------
1. Build a system prompt describing the action vocabulary
   (`ACTION_REGISTRY`), the task's goal/object/target, and the current
   `WorldState`.
2. Call `LLMClient.complete()` and parse the response as one JSON
   object: `{"action": str, "target": str|null, "parameters": dict,
   "done": bool}`.
3. Reject malformed JSON, an unrecognized action name, or a step whose
   preconditions do not hold against the current state -- `_propose()`
   raises `MalformedLLMOutputError`/`PlanValidationError` and the
   iteration is retried (with the failure fed back to the model) up to
   `repair_attempts` times before the whole planning attempt fails.
4. Accept the step, apply its effect to a working `WorldState`, and
   stop when the model reports `"done": true`, the task's goal is
   already satisfied (checked via `validator.GOAL_CHECKS`), or
   `max_iterations` is reached (-> `PlanningTimeoutError`).

Graceful degradation
-----------------------
`ReActPlanner.__init__` takes `llm_client: Optional[LLMClient] = None`
and `fallback_planner: Optional[Planner] = None`. If no client is
configured, or the client raises a
`language.exceptions.LanguageRuntimeError` (network failure, missing
credentials, timeout), or output remains malformed after every repair
attempt, `plan()` delegates to `fallback_planner` (typically a
`RuleBasedPlanner`) when one is supplied, tagging the result's
`Plan.metadata["react_fallback"] = True` so a caller can tell the
result did not actually come from the LLM. With no fallback configured,
the same conditions surface as `PlanningResult(success=False, ...)`
with a descriptive error -- never a crash. This is what section 10's
"if an LLM is unavailable, the project should still be fully testable
through the deterministic planner" requires, and it is enforced by this
module, not left to callers to remember.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from language.exceptions import LanguageRuntimeError
from language.llm_client import LLMClient, LLMRequest
from planner.actions import get_action_spec
from planner.exceptions import (
    LLMUnavailableError,
    MalformedLLMOutputError,
    PlanningTimeoutError,
)
from planner.models import PlanningResult, PlanStep
from planner.planner import Planner
from planner.state import WorldState
from planner.validator import GOAL_CHECKS
from schemas.task import SingleTask

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_SYSTEM_PROMPT_TEMPLATE = """You are the Task Planner of an embodied household robot. You reason \
step by step about which single next action to take to accomplish a goal, given the robot's \
current symbolic world state. You NEVER execute anything yourself -- you only propose one \
action at a time as JSON, which a separate validator checks before it is accepted.

Available actions: {actions}

Respond with ONLY one JSON object, no prose, no markdown fences:
{{"action": "<one of the available actions>", "target": "<object name or null>", \
"parameters": {{}}, "done": <true if the goal is already fully achieved and no further \
action is needed, else false>, "reasoning": "<one short sentence>"}}

Goal: {goal}
Object: {object}
Target: {target}
Current world state: {state}
Steps taken so far: {history}
"""


def _describe_state(state: WorldState) -> Dict[str, Any]:
    return {
        "robot_holding": state.robot_holding,
        "robot_location": state.robot_location,
        "objects": {
            name: {
                "is_located": obj.is_located,
                "is_near_robot": obj.is_near_robot,
                "is_held": obj.is_held,
                "is_open": obj.is_open,
                "location": obj.location,
            }
            for name, obj in state.objects.items()
        },
    }


def _extract_json(text: str) -> Dict[str, Any]:
    stripped = _CODE_FENCE_RE.sub("", text.strip()).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise MalformedLLMOutputError(f"LLM output is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MalformedLLMOutputError("LLM output must be a single JSON object.")
    return parsed


class ReActPlanner(Planner):
    """
    LLM-driven iterative planning strategy. See this module's docstring
    for the full iteration/fallback contract.
    """

    planner_type = "react"

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        fallback_planner: Optional[Planner] = None,
        *,
        max_iterations: int = 12,
        repair_attempts: int = 2,
        validator=None,
    ) -> None:
        super().__init__(validator=validator)
        self._llm_client = llm_client
        self._fallback_planner = fallback_planner
        self._max_iterations = max_iterations
        self._repair_attempts = repair_attempts

    def plan(
        self, task: SingleTask, state: WorldState, memory_context=None
    ) -> PlanningResult:
        started_at = time.monotonic()
        logger.info(
            "planner.plan.start",
            extra={
                "planner_type": self.planner_type,
                "task_id": task.task_id,
                "goal": task.goal,
            },
        )
        if self._llm_client is None:
            return self._fallback(
                task,
                state,
                started_at,
                "No LLM client configured for ReActPlanner.",
                memory_context,
            )

        try:
            # `memory_context` is accepted for interface consistency
            # (Phase 6.3) but not yet threaded into the ReAct
            # prompt/loop itself -- doing so safely (without risking
            # the LLM treating a retrieved memory as ground truth
            # rather than a fallible hint) is future work; the
            # fallback path below still benefits from it via
            # `RuleBasedPlanner`.
            steps = self._run_react_loop(task, state)
        except (
            LLMUnavailableError,
            MalformedLLMOutputError,
            PlanningTimeoutError,
        ) as exc:
            logger.warning(
                "planner.react.failed",
                extra={"task_id": task.task_id, "error": str(exc)},
            )
            return self._fallback(task, state, started_at, str(exc), memory_context)

        result = self._finalize(task, state, steps, started_at, memory_context)
        return result

    def _generate_steps(
        self, task: SingleTask, state: WorldState, memory_context=None
    ) -> List[PlanStep]:
        # Never called: `plan()` is fully overridden above because the
        # ReAct control flow interleaves generation and validation
        # per-iteration rather than generating a complete step list up
        # front (see this module's docstring). Implemented only to
        # satisfy `Planner`'s abstract interface.
        raise NotImplementedError("ReActPlanner overrides plan() directly; see plan().")

    def _fallback(
        self,
        task: SingleTask,
        state: WorldState,
        started_at: float,
        reason: str,
        memory_context=None,
    ) -> PlanningResult:
        if self._fallback_planner is None:
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            return PlanningResult(
                success=False,
                plan=None,
                validation=None,
                errors=[reason],
                planner_type=self.planner_type,
                latency_ms=elapsed_ms,
            )
        logger.info(
            "planner.react.fallback",
            extra={"task_id": task.task_id, "reason": reason},
        )
        result = self._fallback_planner.plan(task, state, memory_context)
        if result.plan is not None:
            result.plan.planner_type = self.planner_type
            result.plan.metadata["react_fallback"] = True
            result.plan.metadata["react_fallback_reason"] = reason
        return PlanningResult(
            success=result.success,
            plan=result.plan,
            validation=result.validation,
            errors=result.errors,
            planner_type=self.planner_type,
            latency_ms=(time.monotonic() - started_at) * 1000.0,
        )

    def _run_react_loop(self, task: SingleTask, state: WorldState) -> List[PlanStep]:
        working_state = state.clone()
        steps: List[PlanStep] = []
        goal_check = GOAL_CHECKS.get((task.goal or "").strip().lower())

        for iteration in range(1, self._max_iterations + 1):
            logger.info(
                "planner.react.iteration",
                extra={"task_id": task.task_id, "iteration": iteration},
            )
            if goal_check is not None and goal_check(task, working_state):
                break

            proposal = self._propose_with_repair(task, working_state, steps)
            if not proposal.get("action"):
                # "done" with no action: the model reports the goal is
                # already achieved and there is nothing left to do.
                logger.info(
                    "planner.react.done",
                    extra={"task_id": task.task_id, "iteration": iteration},
                )
                break

            step = self._accept_proposal(proposal, working_state, len(steps) + 1)
            spec = get_action_spec(step.action)
            assert spec is not None  # guaranteed by _accept_proposal
            spec.apply_effect(working_state, step.target, step.parameters)
            steps.append(step)
            if proposal.get("done"):
                # "done" alongside an action: this action is the final
                # one needed -- apply it (above), then stop iterating.
                logger.info(
                    "planner.react.done",
                    extra={"task_id": task.task_id, "iteration": iteration},
                )
                break
        else:
            if goal_check is None or not goal_check(task, working_state):
                raise PlanningTimeoutError(
                    f"ReActPlanner exceeded {self._max_iterations} iterations without completing the task."
                )
        return steps

    def _propose_with_repair(
        self, task: SingleTask, state: WorldState, steps: List[PlanStep]
    ) -> Dict[str, Any]:
        last_error: Optional[str] = None
        for attempt in range(self._repair_attempts + 1):
            request = self._build_request(task, state, steps, last_error)
            try:
                response = self._llm_client.complete(request)  # type: ignore[union-attr]
            except LanguageRuntimeError as exc:
                raise LLMUnavailableError(f"LLM call failed: {exc}") from exc

            try:
                proposal = _extract_json(response.content)
                self._validate_proposal_shape(proposal, state)
                return proposal
            except MalformedLLMOutputError as exc:
                last_error = str(exc)
                logger.warning(
                    "planner.react.malformed_output",
                    extra={
                        "task_id": task.task_id,
                        "attempt": attempt,
                        "error": last_error,
                    },
                )
        raise MalformedLLMOutputError(
            f"LLM produced malformed output after {self._repair_attempts + 1} attempt(s): {last_error}"
        )

    def _validate_proposal_shape(
        self, proposal: Dict[str, Any], state: WorldState
    ) -> None:
        if not proposal.get("action"):
            # No action proposed: valid only when reporting the goal is
            # already achieved (see `_run_react_loop`'s "done" handling).
            return
        action = proposal.get("action")
        if not isinstance(action, str) or get_action_spec(action) is None:
            raise MalformedLLMOutputError(f"Unrecognized action proposed: {action!r}")
        target = proposal.get("target")
        if target is not None and not isinstance(target, str):
            raise MalformedLLMOutputError("'target' must be a string or null.")
        parameters = proposal.get("parameters", {})
        if not isinstance(parameters, dict):
            raise MalformedLLMOutputError("'parameters' must be an object.")

        spec = get_action_spec(action)
        assert spec is not None
        if spec.requires_target and not target:
            raise MalformedLLMOutputError(f"Action '{action}' requires a target.")
        failed = spec.check_preconditions(state, target, parameters)
        if failed:
            names = ", ".join(p.code for p in failed)
            raise MalformedLLMOutputError(
                f"Proposed action '{action}' violates precondition(s): {names}."
            )

    def _accept_proposal(
        self, proposal: Dict[str, Any], state: WorldState, step_id: int
    ) -> PlanStep:
        action = proposal["action"]
        target = proposal.get("target")
        parameters = proposal.get("parameters") or {}
        spec = get_action_spec(action)
        assert spec is not None
        return PlanStep(
            step_id=step_id,
            action=action,
            target=target,
            parameters=parameters,
            description=spec.describe(target),
            preconditions=[p.description for p in spec.preconditions],
            postconditions=[
                d.format(target=target or "") for d in spec.postcondition_descriptions
            ],
        )

    def _build_request(
        self,
        task: SingleTask,
        state: WorldState,
        steps: List[PlanStep],
        last_error: Optional[str],
    ) -> LLMRequest:
        actions = ", ".join(sorted(_all_action_names()))
        history = [f"{s.action}({s.target or ''})" for s in steps]
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            actions=actions,
            goal=task.goal,
            object=task.object,
            target=task.target,
            state=json.dumps(_describe_state(state)),
            history=json.dumps(history),
        )
        user_message = "Propose the next action."
        if last_error:
            user_message += (
                f" Your previous proposal was rejected: {last_error} Try again."
            )
        return LLMRequest(
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=0.0,
            top_p=1.0,
            max_tokens=300,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            strict_json_mode=True,
            prompt_version="planner-react-v1",
            schema_version="planner-react-v1",
        )


def _all_action_names() -> List[str]:
    from planner.actions import ACTION_REGISTRY

    return list(ACTION_REGISTRY.keys())
