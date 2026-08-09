"""
tasks.py (backend/api/models)

Purpose
-------
Request envelope for the Phase 7 Task API (`api/routes/tasks.py`).
Matches `api/models/execution.py`'s established pattern: the response
side reuses the real backend model (`agents.task_state.TaskState.
to_dict()`, `agents.events.Event`) directly rather than a
hand-maintained copy; this file adds only the one request-side shape
that has no existing model -- a raw natural-language instruction,
text input only this session (see `orchestration/orchestrator.py`'s
module docstring and this session's plan for why speech is deferred).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateTaskRequest(BaseModel):
    """Request body for `POST /api/v1/tasks`."""

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(
        min_length=1,
        max_length=2000,
        description="A natural language instruction, e.g. "
        "'Put the red apple in the refrigerator.' Parsed via the "
        "existing LanguageAgent, then run through the Orchestrator. "
        "Must not be empty or whitespace-only.",
        examples=["Put the red apple in the refrigerator."],
    )
    input_source: Literal["text", "speech"] = Field(
        default="text",
        description="Where `instruction` came from -- 'text' (typed) "
        "or 'speech' (already transcribed via a prior "
        "POST /api/v1/speech/transcribe call; this endpoint itself "
        "never touches audio). Recorded on the resulting TaskState, "
        "purely for observability -- does not change how the "
        "instruction is parsed or planned.",
    )

    @field_validator("instruction", mode="after")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        # Mirrors `api/models/language.py::ParseRequest`'s identical
        # validator -- same rule, same boundary rationale, kept as its
        # own copy (not a shared import) since these are two different
        # request bodies that happen to agree on this one rule; see
        # this package's docstring on not inventing cross-module
        # coupling for a two-line check.
        stripped = value.strip()
        if not stripped:
            raise ValueError("instruction must not be empty or whitespace-only")
        return stripped
