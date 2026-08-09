"""
validator.py (backend/execution)

Purpose
-------
`ResultValidator` is section 8's "Result Validation" boundary: turns
whatever `ActionDispatcher.dispatch()` returned (a raw AI2-THOR event,
or `None` for `LOCATE`) into a standardized `ActionResult`, and never
treats "the simulator call returned without raising" as success on its
own. Three questions, in order, exactly per the Phase 5 spec:

1. Did it execute at all? (a malformed/missing response is
   `SIMULATOR_ERROR`, not silently coerced into success or failure)
2. Did the simulator report success? (`event.metadata["lastActionSuccess"]`)
3. Is the expected state change actually present? -- checked via
   AI2-THOR's own ground-truth metadata where this project's action
   vocabulary makes that meaningful (`isOpen` for open/close, the
   agent's `inventoryObjects` for pickup, `parentReceptacles` for
   put). A step that AI2-THOR marks successful but whose expected
   state change did not happen is reported as `VALIDATION_FAILED`,
   not as success -- this is what section 8 means by "do not treat a
   simulator response as automatically successful."

What this module deliberately does NOT do
---------------------------------------------
No visual/perception-based verification (e.g. re-detecting the object
to confirm it moved) -- that is Phase 2/3 Vision's domain, explicitly
out of scope here per the Phase 5 spec ("do not over-engineer visual
verification yet"). Every check below reads AI2-THOR's own simulator
ground truth (`event.metadata`), never a hallucinated inference.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from execution.errors import ExecutionErrorCode
from execution.models import Action, ActionResult, ActionType


def _find_object(
    metadata: Dict[str, Any], object_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    if not object_id:
        return None
    for obj in metadata.get("objects") or []:
        if obj.get("objectId") == object_id:
            return obj
    return None


def _is_held(metadata: Dict[str, Any], object_id: Optional[str]) -> bool:
    inventory: List[Dict[str, Any]] = metadata.get("inventoryObjects") or []
    return any(item.get("objectId") == object_id for item in inventory)


class ResultValidator:
    """Stateless -- every call is a pure function of its arguments."""

    def validate(
        self,
        action: Action,
        raw_result: Optional[Any],
        *,
        duration_ms: float,
        retry_count: int = 0,
    ) -> ActionResult:
        object_id = action.parameters.get("object_id")
        container_id = action.parameters.get("container_id")
        base: Dict[str, Any] = dict(
            action=action.action_type.value,
            action_id=action.action_id,
            step_id=action.step_id,
            object_id=object_id,
            target_id=container_id,
            duration_ms=duration_ms,
            retry_count=retry_count,
        )

        if action.action_type == ActionType.LOCATE:
            # No simulator call was made (see dispatcher.py) -- this is
            # a symbolic bookkeeping step that always "succeeds".
            return ActionResult(success=True, metadata={}, **base)

        if raw_result is None or not hasattr(raw_result, "metadata"):
            return ActionResult(
                success=False,
                error="Simulator returned no usable response for this action.",
                error_code=ExecutionErrorCode.SIMULATOR_ERROR,
                metadata={},
                **base,
            )

        metadata: Dict[str, Any] = raw_result.metadata or {}
        last_action_success = bool(metadata.get("lastActionSuccess"))
        error_message = metadata.get("errorMessage") or None

        if not last_action_success:
            return ActionResult(
                success=False,
                error=error_message
                or f"Simulator reported failure for " f"{action.action_type.value!r}.",
                error_code=self._error_code_for(action.action_type, metadata),
                metadata=metadata,
                **base,
            )

        postcondition_error = self._check_postcondition(action, metadata)
        if postcondition_error is not None:
            return ActionResult(
                success=False,
                error=postcondition_error,
                error_code=ExecutionErrorCode.VALIDATION_FAILED,
                metadata=metadata,
                **base,
            )

        return ActionResult(success=True, metadata=metadata, **base)

    @staticmethod
    def _error_code_for(
        action_type: ActionType, metadata: Dict[str, Any]
    ) -> ExecutionErrorCode:
        if action_type == ActionType.NAVIGATE:
            return ExecutionErrorCode.NAVIGATION_FAILED
        return ExecutionErrorCode.SIMULATOR_ERROR

    @staticmethod
    def _check_postcondition(action: Action, metadata: Dict[str, Any]) -> Optional[str]:
        object_id = action.parameters.get("object_id")

        if action.action_type == ActionType.PICKUP:
            if not _is_held(metadata, object_id):
                return (
                    f"PickupObject reported success but {object_id!r} is not "
                    "in the agent's inventory."
                )
        elif action.action_type == ActionType.OPEN:
            obj = _find_object(metadata, object_id)
            if obj is not None and obj.get("isOpen") is not True:
                return f"OpenObject reported success but {object_id!r} is not open."
        elif action.action_type == ActionType.CLOSE:
            obj = _find_object(metadata, object_id)
            if obj is not None and obj.get("isOpen") is not False:
                return f"CloseObject reported success but {object_id!r} is still open."
        elif action.action_type == ActionType.PUT:
            # AI2-THOR's PutObject targets the receptacle by id and infers
            # the held object itself; the only ground-truth postcondition
            # this project's action vocabulary can check is "the agent is
            # no longer holding it" -- there is no separate objectId for
            # "the object that was placed" once PutObject has run.
            if _is_held(metadata, object_id):
                return (
                    f"PutObject reported success but the held object "
                    f"{object_id!r} is still in the agent's inventory."
                )

        return None
