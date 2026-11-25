"""
reflector.py (backend/learning)

`LearnedReflector` wraps the rule-based `ReflectionAgent` and uses the step
outcome predictor to choose continue / retry / replan / abort.

Modes (`MILO_LEARNED_REFLECTOR`):
- `off`     -- the rule-based verdict, unchanged;
- `shadow`  -- the rule-based verdict is used; the learned verdict is computed
               alongside, and both are logged for comparison (`decisions`);
- `on`      -- the learned verdict is used, subject to the safety rules below.

Safety rules (a learned model never takes an irreversible action on its own):
- a mission the rule-based reflector says succeeded ("continue") is never
  second-guessed;
- the learned verdict applies only to a step that really failed, and only
  while the predictor is usable (not drifted / not too slow) and confident;
  otherwise the rule-based verdict stands;
- an early abort needs strong evidence (thresholds tuned on validation data)
  and carries a plain-language explanation shown to the user.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from agents.failures import AgentFailure
from agents.reflection_agent import ReflectionAgent, ReflectionResult
from execution.models import ExecutionRecord, StepStatus
from learning.serving import OutcomePredictor, Prediction

_REPLAN_TYPES = {"blocked", "not_reachable", "not_visible", "wrong_object"}


def _the(name: Optional[str]) -> str:
    return f"the {name}" if name else "it"


class LearnedReflector(ReflectionAgent):
    name = "reflection"
    uses_contexts = True

    def __init__(
        self,
        base: ReflectionAgent,
        predictor: OutcomePredictor,
        mode: str = "shadow",
        thresholds: Optional[Mapping[str, float]] = None,
    ) -> None:
        super().__init__()
        self._base = base
        self._predictor = predictor
        self.mode = mode
        self.thresholds = {**predictor.thresholds, **(thresholds or {})}
        self.decisions: List[Dict[str, Any]] = []
        #: Running totals for the Lab's shadow comparison.
        self.stats = {"compared": 0, "agree": 0, "used": 0, "fallbacks": 0}

    def pop_decisions(self) -> List[Dict[str, Any]]:
        out, self.decisions = self.decisions, []
        return out

    def reflect(  # type: ignore[override]
        self,
        record: ExecutionRecord,
        failures: List[AgentFailure],
        *,
        attempt: int,
        max_attempts: int,
        contexts: Optional[Mapping[int, Mapping[str, Any]]] = None,
    ) -> ReflectionResult:
        base = self._base.reflect(
            record, failures, attempt=attempt, max_attempts=max_attempts
        )
        if self.mode == "off" or base.action == "continue" or not contexts:
            return base
        failed = next(
            (
                s
                for s in record.step_results
                if s.status in (StepStatus.FAILED, StepStatus.BLOCKED)
            ),
            None,
        )
        ctx = contexts.get(failed.step_id) if failed is not None else None
        if failed is None or ctx is None:
            return base
        if not self._predictor.usable:
            self._log(
                base,
                None,
                None,
                reason=self._predictor.disabled_reason or "drifted",
                used=False,
            )
            return base
        pred = self._predictor.predict(ctx, explain=True)
        learned = self._decide(base, pred, failed.target, attempt, max_attempts, ctx)
        used = self.mode == "on" and learned is not None and pred.confident
        self._log(base, learned, pred, used=used)
        return learned if used and learned is not None else base

    # -- the decision -------------------------------------------------------------
    def _decide(
        self,
        base: ReflectionResult,
        pred: Prediction,
        target: Optional[str],
        attempt: int,
        max_attempts: int,
        ctx: Mapping[str, Any],
    ) -> Optional[ReflectionResult]:
        if attempt >= max_attempts:
            return None  # budget exhausted: the rule-based abort stands
        kind = pred.failure_type
        replans = int(ctx.get("replans_so_far", 0))
        if pred.p_retry_success < 0.10 and (
            kind == "wrong_object" or (kind in _REPLAN_TYPES and replans >= 1)
        ):
            why = (
                f"I can't find {_the(target)} anywhere I can see, so I'm going to stop here."
                if kind == "wrong_object"
                else f"I don't think I can get to {_the(target)} from here, so I'm going to stop instead of trying again."
            )
            return ReflectionResult(
                success=False,
                reason=base.reason,
                action="abort",
                store_memory=True,
                explanation=why,
            )
        if pred.p_retry_success >= self.thresholds.get("retry", 0.5):
            return ReflectionResult(
                success=False,
                reason=base.reason,
                action="retry",
                store_memory=False,
                explanation="That looks like a hiccup that usually works the second time, so I'm trying it again.",
            )
        if kind in _REPLAN_TYPES:
            return ReflectionResult(
                success=False,
                reason=base.reason,
                action="replan",
                store_memory=False,
                explanation=f"Trying again probably won't help with {_the(target)}, so I'm making a new plan.",
            )
        return None

    def _log(
        self,
        base: ReflectionResult,
        learned: Optional[ReflectionResult],
        pred: Optional[Prediction],
        *,
        used: bool,
        reason: str = "",
    ) -> None:
        self.stats["compared"] += 1 if learned is not None else 0
        self.stats["agree"] += (
            1 if (learned is not None and learned.action == base.action) else 0
        )
        self.stats["used"] += 1 if used else 0
        self.stats["fallbacks"] += 1 if reason else 0
        self.decisions.append(
            {
                "model": "outcome_predictor",
                "mode": self.mode,
                "rule_based": base.action,
                "learned": learned.action if learned else None,
                "agree": bool(learned is None or learned.action == base.action),
                "used": used,
                "fallback_reason": reason or None,
                "prediction": pred.to_dict() if pred else None,
            }
        )
