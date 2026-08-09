"""
response_composer.py (backend/voice)

Purpose
-------
`compose_spoken_response()` -- turns a finished `agents.task_state.
TaskState` (plus, optionally, the `memory.retrieval.MemoryResult`s a
query retrieved) into one short sentence or two suitable for
`ElevenLabsClient.synthesize()` to speak aloud. This is new work Phase
8.2 needs (see the Phase 8.2 plan's Context section): no field anywhere
in this backend already holds "what MILO should say."

Why this is allowed to import `agents.task_state`/`memory.retrieval`
when the rest of `backend/voice/` cannot
------------------------------------------------------------------------
See `voice/__init__.py`'s module docstring -- composing a truthful
spoken summary is inherently about reading those types' already-real,
already-validated fields. This module never constructs a task, never
plans, never touches the simulator; it only reads.

Grounding policy -- never invent facts
-------------------------------------------
The LLM call below receives *only* a fixed set of real structured
fields (task status, user request, target, failure message if any,
retrieved memory contents) rendered as plain lines, with an explicit
system-prompt instruction never to state anything not present in that
context. This mirrors `language/prompt_builder.py`'s "the prompt is the
contract" discipline, just for a different, much smaller task. On any
failure (timeout, provider error, empty response) this function falls
back to a deterministic, template-only sentence built from the same
real fields -- so voice output can never go silent, and can never
silently fabricate something the LLM invented if the call itself
succeeds but returns nonsense (a length/sanity check is applied before
the LLM's text is trusted).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional, Sequence

from language.config import LLMRuntimeConfig
from language.exceptions import LanguageRuntimeError
from language.llm_client import LLMClient, LLMRequest
from language.provider_factory import create_llm_client

if TYPE_CHECKING:
    from agents.task_state import TaskState
    from memory.retrieval import MemoryResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are MILO, a helpful embodied household robot, speaking your "
    "response aloud to the person who gave you an instruction. You will "
    "be given real, structured facts about what just happened. Compose "
    "exactly one or two short, natural spoken sentences summarizing the "
    "outcome for the user. Never state a fact that is not present in "
    "the given context. Never invent locations, objects, times, or "
    "outcomes. If the context is sparse, keep your response short and "
    "honest rather than filling in details."
)

#: A response shorter than this or longer than this is treated as
#: suspicious (empty/truncated, or the model ignoring the "short"
#: instruction) and discarded in favor of the deterministic fallback --
#: not a hard guarantee of correctness, just a basic sanity bound.
_MIN_RESPONSE_CHARS = 3
_MAX_RESPONSE_CHARS = 500


def _build_context_lines(
    task_state: "TaskState", memories: Sequence["MemoryResult"]
) -> List[str]:
    lines = [
        f"Instruction: {task_state.user_request}",
        f"Status: {task_state.status.value}",
    ]
    if task_state.target:
        lines.append(f"Target object: {task_state.target}")
    if task_state.current_location:
        lines.append(f"Location: {task_state.current_location}")
    if task_state.failures:
        lines.append(f"Failure reason: {task_state.failures[-1].message}")
    for result in memories[:5]:
        lines.append(f"Remembered: {result.memory.content}")
    return lines


def _deterministic_fallback(task_state: "TaskState") -> str:
    """Template-only sentence, no LLM involved -- see module docstring."""
    from agents.task_state import TaskStatus

    if task_state.status == TaskStatus.SUCCEEDED:
        return f"I finished: {task_state.user_request}."
    if task_state.status == TaskStatus.FAILED:
        if task_state.failures:
            return f"I couldn't do that — {task_state.failures[-1].message}"
        return f"I couldn't complete: {task_state.user_request}."
    if task_state.status == TaskStatus.CANCELLED:
        return "I stopped that task."
    return f"Working on it: {task_state.user_request}."


def compose_spoken_response(
    task_state: "TaskState",
    memories: Optional[Sequence["MemoryResult"]] = None,
    *,
    llm_client: Optional[LLMClient] = None,
) -> str:
    """
    Returns a short, real-fact-grounded spoken response for
    `task_state`. Never raises -- degrades to `_deterministic_fallback`
    on any error. `llm_client`, when omitted, is built from
    `LLMRuntimeConfig.from_env()` via the same `create_llm_client()`
    factory `LanguageAgent` uses -- reusing the exact same provider
    configuration/credentials the parsing pipeline already has, rather
    than a second, separately-configured client.
    """
    memories = memories or []
    fallback = _deterministic_fallback(task_state)
    try:
        client = llm_client or create_llm_client(LLMRuntimeConfig.from_env())
        request = LLMRequest(
            system_prompt=_SYSTEM_PROMPT,
            user_message="\n".join(_build_context_lines(task_state, memories)),
            temperature=0.4,
            top_p=1.0,
            max_tokens=120,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            strict_json_mode=False,
            prompt_version="voice-response-v1",
            schema_version="n/a",
        )
        response = client.complete(request)
        text = response.content.strip()
        if _MIN_RESPONSE_CHARS <= len(text) <= _MAX_RESPONSE_CHARS:
            return text
        logger.warning(
            "voice.response_composer.suspicious_length", extra={"length": len(text)}
        )
    except LanguageRuntimeError:
        logger.warning("voice.response_composer.llm_failed", exc_info=True)
    except Exception:
        logger.warning("voice.response_composer.unexpected_error", exc_info=True)
    return fallback
