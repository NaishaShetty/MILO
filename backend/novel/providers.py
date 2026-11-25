"""
providers.py (backend/novel)

Pluggable language-model planners for novel tasks. A provider takes a `PlanRequest`
(command, scene, memories/skills/lessons, the action registry, any feedback from a failed
attempt) and returns the raw JSON proposal (see `novel.plan`), or raises `ProviderError`.

    MILO_NOVEL_PROVIDER = claude | ollama | offline   (default: claude when credentials resolve)
    MILO_NOVEL_MODEL    = claude-opus-5-5
    MILO_NOVEL_TIMEOUT  = 30                    seconds per call (Claude; Ollama default 120)
    MILO_OLLAMA_MODEL / MILO_OLLAMA_URL / MILO_OLLAMA_KEEP_ALIVE   (see OllamaProvider)

`OllamaProvider` runs a free local model through Ollama with grammar-constrained JSON
output; it is the one that has been measured (docs/local_model.md). `ClaudeProvider` uses
the official Anthropic SDK with structured outputs constrained to `PLAN_SCHEMA`, and
refusal fallbacks enabled (`fallbacks: "default"`); it has never been run against the API
(no credits) and is untested beyond mocked unit tests. Identical requests are answered
from an in-process cache. `OfflineProvider` always says it can't plan offline. Either
model provider falls back to offline when it can't be reached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
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
        # getattr: newer SDKs type content as a union of many block kinds, and
        # checking b.type doesn't narrow it for mypy.
        text = next(
            (getattr(b, "text", "") for b in response.content if b.type == "text"), ""
        )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("my language model's answer wasn't valid JSON") from exc
        self._cache[key] = data
        return data


DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"


def _post_json(url: str, body: Dict[str, Any], timeout_s: float) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode() or "{}")


def ollama_reachable(url: str, timeout_s: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=timeout_s):
            return True
    except Exception:
        return False


def _few_shot() -> List[Dict[str, str]]:
    """Worked examples from the DEV set only (never the held-out TEST set)."""
    from novel.dev_set import dev_commands, few_shot_commands

    by_command = {c["command"]: c for c in dev_commands()}
    tiny_scene: List[Dict[str, Any]] = [
        {"objectType": "Cooler", "openable": True, "isOpen": False},
        {"objectType": "Bread", "pickupable": True},
        {"objectType": "Desk"},
    ]
    messages: List[Dict[str, str]] = []
    for wanted in few_shot_commands():
        item = next(c for cmd, c in by_command.items() if cmd.startswith(wanted))
        example = PlanRequest(
            command=item["command"], scene=tiny_scene, holding=None, actions=[]
        )
        messages.append({"role": "user", "content": render(example)})
        messages.append({"role": "assistant", "content": json.dumps(item["answer"])})
    return messages


class OllamaProvider:
    """A local model served by Ollama (native /api/chat). The plan schema is passed as
    `format`, so the model can only produce JSON of that shape; temperature 0 and a fixed
    seed make answers repeatable. Identical (model, prompt) pairs come from a cache.

        MILO_NOVEL_PROVIDER=ollama
        MILO_OLLAMA_MODEL=qwen2.5:7b        MILO_OLLAMA_URL=http://localhost:11434
        MILO_OLLAMA_KEEP_ALIVE=5m           how long Ollama keeps the model in VRAM
    """

    name = "ollama"

    def __init__(
        self,
        model: Optional[str] = None,
        url: Optional[str] = None,
        timeout_s: float = 120.0,
        retries: int = 2,
        seed: int = 0,
        keep_alive: Optional[str] = None,
        think: Optional[bool] = False,
        few_shot: bool = True,
        post: Any = None,
    ) -> None:
        self.model = model or os.environ.get("MILO_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        self.url = (
            url or os.environ.get("MILO_OLLAMA_URL", DEFAULT_OLLAMA_URL)
        ).rstrip("/")
        self.timeout_s = timeout_s
        self.retries = retries
        self.seed = seed
        self.keep_alive = keep_alive or os.environ.get("MILO_OLLAMA_KEEP_ALIVE", "5m")
        self.think = think
        self._examples = _few_shot() if few_shot else []
        self._post = post or _post_json
        self._cache: Dict[str, Dict[str, Any]] = {}
        #: Totals for evaluation: calls made, bad JSON answers, tokens and seconds.
        self.stats: Dict[str, float] = {"calls": 0, "invalid_json": 0, "timeouts": 0,
                                        "eval_tokens": 0, "eval_seconds": 0.0, "seconds": 0.0}  # fmt: skip

    def _body(self, prompt: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "format": PLAN_SCHEMA,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0, "seed": self.seed},
            "messages": [{"role": "system", "content": SYSTEM}]
            + self._examples
            + [{"role": "user", "content": prompt}],
        }
        if self.think is not None:
            body["think"] = self.think
        return body

    def propose(self, request: PlanRequest) -> Dict[str, Any]:
        prompt = render(request)
        key = hashlib.sha256(f"{self.model}\n{prompt}".encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]
        body = self._body(prompt)
        problem = ProviderError("my local language model gave no answer")
        for _ in range(self.retries + 1):
            started = time.perf_counter()
            self.stats["calls"] += 1
            try:
                reply = self._post(f"{self.url}/api/chat", body, self.timeout_s)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:200]
                if exc.code == 400 and "think" in detail and "think" in body:
                    body.pop("think")  # this model can't switch thinking; ask without
                    continue
                if exc.code == 404:
                    raise ProviderError(
                        f"my local model {self.model} isn't installed "
                        f"(run: ollama pull {self.model})"
                    ) from exc
                raise ProviderError(
                    f"my local language model failed ({exc.code})"
                ) from exc
            except (socket.timeout, TimeoutError) as exc:
                self.stats["timeouts"] += 1
                problem = ProviderError(
                    "my local language model took too long to answer"
                )
                problem.__cause__ = exc
                continue
            except (urllib.error.URLError, ConnectionError, OSError) as exc:
                raise ProviderError(
                    f"I couldn't reach my local language model at {self.url}"
                ) from exc
            finally:
                self.stats["seconds"] += time.perf_counter() - started
            self.stats["eval_tokens"] += reply.get("eval_count") or 0
            self.stats["eval_seconds"] += (reply.get("eval_duration") or 0) / 1e9
            text = (reply.get("message") or {}).get("content", "")
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                self.stats["invalid_json"] += 1
                problem = ProviderError("my local model's answer wasn't valid JSON")
                continue
            if not isinstance(data, dict):
                self.stats["invalid_json"] += 1
                problem = ProviderError("my local model's answer wasn't a plan")
                continue
            self._cache[key] = data
            return data
        raise problem


def build_provider() -> Provider:
    choice = os.environ.get("MILO_NOVEL_PROVIDER", "claude").strip().lower()
    if choice == "offline":
        return OfflineProvider()
    if choice == "ollama":
        url = os.environ.get("MILO_OLLAMA_URL", DEFAULT_OLLAMA_URL)
        if not ollama_reachable(url):
            logger.warning("novel.ollama_unreachable url=%s", url)
            return OfflineProvider()
        timeout = float(os.environ.get("MILO_NOVEL_TIMEOUT", "120"))
        return OllamaProvider(url=url, timeout_s=timeout)
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
