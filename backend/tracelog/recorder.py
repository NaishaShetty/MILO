"""
recorder.py (backend/tracelog)

Turns the orchestrator's lifecycle (its published events and its per-step listener)
into trace records. Every hook swallows its own errors: tracing can never fail or stall
a mission.

    MILO_TRACE=1                 on by default; 0 turns it off
    MILO_TRACE_DB=data/traces.db where the store lives
    MILO_TRACE_FRAMES=1          keep a small JPEG thumbnail per finished step
"""

from __future__ import annotations

import base64
import io
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from tracelog.store import TraceStore

logger = logging.getLogger(__name__)
FrameSource = Callable[[], Any]
THUMB_WIDTH = 160


def thumbnail(frame: Any, width: int = THUMB_WIDTH) -> Optional[str]:
    """RGB array -> small base64 JPEG (None if there is no frame or no Pillow)."""
    if frame is None:
        return None
    try:
        from PIL import Image

        image = Image.fromarray(frame).convert("RGB")
        height = max(1, int(image.height * width / max(image.width, 1)))
        image = image.resize((width, height))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=70)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        return None


class TraceRecorder:
    def __init__(
        self,
        store: TraceStore,
        frame_source: Optional[FrameSource] = None,
        keep_frames: bool = True,
    ) -> None:
        self.store = store
        self._frames = frame_source if keep_frames else None
        self._thoughts_seen: Dict[str, int] = {}
        self._step_started: Dict[tuple, float] = {}

    # -- hooks the orchestrator calls ---------------------------------------------

    def on_event(self, task_state: Any, event: str, payload: Dict[str, Any]) -> None:
        try:
            self._on_event(task_state, event, payload)
        except Exception:
            logger.warning("trace.event_failed", exc_info=True)

    def on_step(self, task_state: Any, step: Any, status: str) -> None:
        try:
            self._on_step(task_state, step, status)
        except Exception:
            logger.warning("trace.step_failed", exc_info=True)

    # -- internals ----------------------------------------------------------------------

    def _on_event(self, ts: Any, event: str, payload: Dict[str, Any]) -> None:
        mid = ts.task_id
        if event == "TASK_CREATED":
            self.store.begin(
                mid,
                task_text=ts.user_request,
                parsed_task={
                    "goal": ts.goal,
                    "objects": ts.objects,
                    "target": ts.target,
                    "sub_goals": ts.sub_goals,
                },
                planner=ts.planner,
                started_at=ts.created_at,
            )
            self.store.add(mid, "mission_started", {"text": ts.user_request})
            return
        self._flush_thoughts(ts)
        if event == "MEMORY_RETRIEVED":
            self.store.add(mid, "memory", {"hits": ts.retrieved_memories})
        elif event == "PLAN_CREATED" and ts.current_plan is not None:
            self.store.add(
                mid,
                "plan",
                {
                    "planner": ts.planner,
                    "plan": ts.current_plan.model_dump(mode="json"),
                    "stage_ms": dict(ts.latencies_ms),
                },
            )
        elif event == "REFLECTION_COMPLETED":
            decisions = payload.get("model_decisions") or []
            self.store.add(
                mid,
                "reflection",
                {
                    "verdict": payload.get("action"),
                    "reason": payload.get("reason"),
                    "explanation": payload.get("explanation"),
                    "stage_ms": dict(ts.latencies_ms),
                },
            )
            for decision in decisions:
                self.store.add(mid, "model_decision", dict(decision))
        elif event == "REPLAN_TRIGGERED":
            self.store.add(mid, "replan", {"stage_ms": dict(ts.latencies_ms)})
        elif event in ("TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED"):
            if ts.verification:
                self.store.add(mid, "verification", {"results": ts.verification})
            outcome = {
                "TASK_COMPLETED": "succeeded",
                "TASK_FAILED": "failed",
                "TASK_CANCELLED": "cancelled",
            }[event]
            self.store.add(
                mid,
                "mission_finished",
                {"outcome": outcome, "reason": payload.get("reason")},
            )
            self.store.finish(
                mid,
                outcome,
                reason=payload.get("reason"),
                latencies=dict(ts.latencies_ms),
                verification=ts.verification,
            )
            self._thoughts_seen.pop(mid, None)

    def _on_step(self, ts: Any, step: Any, status: str) -> None:
        key = (ts.task_id, step.step_id)
        now = time.time()
        if status == "started":
            self._step_started[key] = now
            return
        started = self._step_started.pop(key, None)
        data: Dict[str, Any] = {
            "action": step.action,
            "target": step.target,
            "parameters": step.parameters,
            "status": status,
            "started_at": started,
            "ended_at": now,
            "duration_ms": (now - started) * 1000.0 if started else None,
            "confidence": getattr(step, "confidence", None),
            "why": getattr(step, "why", None),
            "explanation": getattr(step, "explanation", None),
            "stage_ms": dict(ts.latencies_ms),
        }
        if self._frames is not None:
            data["frame"] = thumbnail(self._frames())
        self.store.add(ts.task_id, "step", data, step_id=step.step_id, ts=now)
        self._flush_thoughts(ts)

    def _flush_thoughts(self, ts: Any) -> None:
        seen = self._thoughts_seen.get(ts.task_id, 0)
        for thought in ts.thoughts[seen:]:
            self.store.add(
                ts.task_id,
                "thought",
                dict(thought),
                step_id=thought.get("step_id"),
                ts=thought.get("at"),
            )
        self._thoughts_seen[ts.task_id] = len(ts.thoughts)


def build_recorder(
    frame_source: Optional[FrameSource] = None,
) -> Optional[TraceRecorder]:
    """The recorder the API uses (None when `MILO_TRACE=0` or the store can't open)."""
    if os.environ.get("MILO_TRACE", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    try:
        store = TraceStore(Path(os.environ.get("MILO_TRACE_DB", "data/traces.db")))
    except Exception:
        logger.warning("trace.store_unavailable", exc_info=True)
        return None
    keep = os.environ.get("MILO_TRACE_FRAMES", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    return TraceRecorder(store, frame_source=frame_source, keep_frames=keep)
