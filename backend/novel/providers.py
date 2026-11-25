"""
providers.py (backend/novel)

Pluggable language-model planners for novel tasks. A provider takes a `PlanRequest`
(command, scene, memories/skills/lessons, the action registry, any feedback from a failed
attempt) and returns the raw JSON proposal (see `novel.plan`), or raises `ProviderError`.

    MILO_NOVEL_PROVIDER = claude | offline      (default: claude when credentials resolve)
    MILO_NOVEL_MODEL    = claude-opus-5-5
    MILO_NOVEL_TIMEOUT  = 30                    seconds per call (the SDK retries twice)

`ClaudeProvider` uses the official Anthropic SDK with structured outputs constrained to
`PLAN_SCHEMA`, and refusal fallbacks enabled (`fallbacks: "default"`). Identical requests
are answered from an in-process cache. `OfflineProvider` always says it can't plan offline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from novel.plan import PLAN_SCHEMA

logger = logging.getLogger(__name__)
DEFAULT_MODEL = "claude-opus-5-5"


class ProviderError(RuntimeError):
    """The planner could not give an answer (offline, timeout, API error, refusal)."""


@dataclass
class PlanRequest:
    command: str
    scene: List[Dict[str, Any]]
    holding: Optional[str]
    actions: List[Dict[str, Any]]
    memories: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    lessons: List[str] = field(default_factory=list)
    feedback: List[str] = field(default_factory=list)

    def key(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()


class Provider(Protocol):
    name: str

    def propose(self, request: PlanRequest) -> Dict[str, Any]: ...


SYSTEM = """You plan actions for MILO, a household robot in a simulated home.
You receive a command MILO has no built-in recipe for, the objects MILO can currently
see (with their state), what MILO is holding, relevant memories, saved skills and
lessons from past failures, and the ONLY actions MILO can perform.

Answer with exactly one of:
- a plan: "goal" in plain words, "success" conditions that can be checked in the world,
  and ordered "steps" that use only the listed actions and only objects in the scene;
- "question": one short clarifying question, when the command is ambiguous;
- "impossible": a short plain reason, when no sequence of the listed actions can do it.
Unused fields are empty strings or empty lists. Use lower-case object names as they appear
in the scene. Prefer the shortest plan that makes the success conditions true. If feedback
says an earlier attempt failed, change the plan to avoid that failure."""


def render(request: PlanRequest) -> str:
    return json.dumps(
        {
            "command": request.command,
            "scene": request.scene,
            "holding": request.holding,
            "actions": request.actions,
            "memories": request.memories,
            "skills": request.skills,
            "lessons": request.lessons,
            "feedback_from_last_attempt": request.feedback,
        },
        indent=1,
    )


class OfflineProvider:
    name = "offline"

    def propose(self, request: PlanRequest) -> Dict[str, Any]:
        raise ProviderError(
            "I can't work out new tasks offline -- no language model is set up"
        )


class ScriptedProvider:
    """Answers from a fixed table (tests, evaluation, demos). `table[command]` is a
    proposal dict or a list of them (one per call, for replans)."""

    name = "scripted"

    def __init__(self, table: Dict[str, Any]) -> None:
        self._table = table
        self._calls: Dict[str, int] = {}

    def propose(self, request: PlanRequest) -> Dict[str, Any]:
        answer = self._table.get(request.command)
        if answer is None:
            raise ProviderError("no scripted answer for this command")
        if isinstance(answer, list):
            n = self._calls.get(request.command, 0)
            self._calls[request.command] = n + 1
            return answer[min(n, len(answer) - 1)]
        return answer


class ClaudeProvider:
    name = "claude"

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_s: float = 30.0,
        client: Any = None,
    ) -> None:
        import anthropic

        self._anthropic = anthropic
        self.model = model or os.environ.get("MILO_NOVEL_MODEL", DEFAULT_MODEL)
        self._client = client or anthropic.Anthropic(timeout=timeout_s, max_retries=2)
        self._cache: Dict[str, Dict[str, Any]] = {}

    def propose(self, request: PlanRequest) -> Dict[str, Any]:
        key = request.key()
        if key in self._cache:
            return self._cache[key]
        a = self._anthropic
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=SYSTEM,
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": PLAN_SCHEMA},
                },
                messages=[{"role": "user", "content": render(request)}],
            )
        except a.AuthenticationError as exc:
            raise ProviderError("my language model key isn't valid") from exc
        except a.RateLimitError as exc:
            raise ProviderError("my language model is busy; try again soon") from exc
        except a.APITimeoutError as exc:
            raise ProviderError("my language model took too long to answer") from exc
        except a.APIStatusError as exc:
            raise ProviderError(
                f"my language model failed ({exc.status_code})"
            ) from exc
        except a.APIConnectionError as exc:
            raise ProviderError("I couldn't reach my language model") from exc
        if response.stop_reason == "refusal":
            raise ProviderError("my language model declined to plan this")
        if response.stop_reason == "max_tokens":
            raise ProviderError("my language model's answer was cut off")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("my language model's answer wasn't valid JSON") from exc
        self._cache[key] = data
        return data


def build_provider() -> Provider:
    choice = os.environ.get("MILO_NOVEL_PROVIDER", "claude").strip().lower()
    if choice == "offline":
        return OfflineProvider()
    try:
        timeout = float(os.environ.get("MILO_NOVEL_TIMEOUT", "30"))
        provider = ClaudeProvider(timeout_s=timeout)
        # The SDK resolves an API key, auth token or `ant auth login` profile; with
        # none of them every call would fail, so say "offline" up front instead.
        if not (
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_PROFILE")
            or os.path.isdir(os.path.expanduser("~/.config/anthropic"))
        ):
            return OfflineProvider()
        return provider
    except Exception:
        logger.warning("novel.provider_unavailable", exc_info=True)
        return OfflineProvider()
