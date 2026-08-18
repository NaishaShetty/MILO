"""
llm_client.py

Purpose
-------
Defines the provider-independent boundary between the Language Parsing
Runtime (Phase 3.4) and whichever LLM actually turns a prepared prompt
into a raw response. This is the one file allowed to know that an LLM
call happens over HTTP, that a specific provider's API expects a
specific JSON request shape, or that credentials come from an
environment variable -- every other component in `backend/language/`
depends only on the `LLMClient` protocol defined here, never on a
concrete provider.

Why this abstraction exists
------------------------------
`LanguageAgent` (`agent.py`) must not hardcode "call OpenAI" -- Phase
3.3's `prompt_config.yaml` already documents five candidate provider
families (OpenAI, Anthropic, Qwen, Llama, Phi), and this project's own
research goal (comparing how different models parse the same
instruction) requires swapping providers without touching orchestration
code. `LLMClient` is a `typing.Protocol` rather than an abstract base
class deliberately: structural typing lets a test supply a bare object
with a matching `complete()` method (see `backend/language/`'s test
suite) with no inheritance ceremony, and lets a future concrete client
be added without this file changing at all.

Scope of this file (what it does NOT do)
--------------------------------------------
`LLMClient` implementations receive a fully-prepared `LLMRequest` (built
by `PromptBuilder`) and return a `LLMResponse` carrying the provider's
raw text output. They do not parse that text as JSON (`ResponseParser`'s
job), do not validate it against the task schema (`SchemaValidator`'s
job), and do not decide what the prompt should say (`PromptBuilder`'s
job). The one exception is transport-envelope unwrapping: a provider's
raw HTTP response is a JSON envelope (e.g. OpenAI's
`{"choices": [{"message": {"content": "..."}}]}`), and extracting the
assistant's text *out of that transport envelope* is inherent to being
"a client for provider X" -- it is not business logic about the
content's own shape. `ResponseParser`'s "provider response wrapper"
responsibility is a different, content-level concern (e.g. the
extracted text itself being wrapped in a markdown code fence) -- see
`response_parser.py`'s module docstring for exactly where that line is
drawn.

Only one concrete implementation exists in this phase
----------------------------------------------------------
`OpenAICompatibleLLMClient` targets any provider that implements the
OpenAI chat-completions HTTP contract -- which covers OpenAI itself and
self-hosted OpenAI-API-compatible servers (e.g. vLLM/Ollama serving
Qwen, Llama, or Phi), matching `prompt_config.yaml`'s recommended
default for `strict_json_mode: true` without requiring a
provider-specific SDK per entry in its `model_compatibility` list.
Adding a genuinely incompatible provider (e.g. one with a fundamentally
different transport contract) later means adding one more class here
that implements the same `LLMClient` protocol -- it does not require
changing `LanguageAgent`, `PromptBuilder`, or any other component.

Credential handling policy
------------------------------
The API key is read from `os.environ[config.api_key_env_var]` inside
`complete()`, immediately before use, and is never stored on `self`,
never included in a raised exception's message, and never logged. See
`_redact` and every `raise` in this file for where that policy is
enforced.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable

import requests

from language.config import LLMRuntimeConfig
from language.exceptions import ConfigurationError, LLMProviderError, LLMTimeoutError

# Maximum number of characters of a provider's error response body to
# surface in an exception message. Long enough to be diagnostically
# useful (most provider error bodies are short JSON objects), short
# enough that a pathological response can't flood logs/exception
# trackers -- see `_safe_error_detail`.
_MAX_ERROR_DETAIL_CHARS = 500


def redact(text: str, secret: Optional[str]) -> str:
    """
    Public re-export of this module's credential-redaction helper (see
    `_redact` below) -- `gemini_client.py` (Phase 3.5) needs the exact
    same behavior for its own error messages, and duplicating the
    one-line implementation would risk the two copies drifting on a
    future fix. Kept as a thin wrapper (rather than renaming `_redact`
    itself) so this module's own internal call sites are unaffected.
    """
    return _redact(text, secret)


def safe_error_detail(body: str, secret: Optional[str]) -> str:
    """
    Public re-export of `OpenAICompatibleLLMClient._safe_error_detail`
    for reuse by `gemini_client.py` -- see `redact` above for why this
    is a thin wrapper rather than a second implementation.
    """
    return _truncate_and_redact(body, secret)


def _truncate_and_redact(body: str, secret: Optional[str]) -> str:
    redacted = _redact(body, secret)
    if len(redacted) > _MAX_ERROR_DETAIL_CHARS:
        return redacted[:_MAX_ERROR_DETAIL_CHARS] + "... [truncated]"
    return redacted


def post_json_with_retries(
    *,
    url: str,
    json_payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout_seconds: float,
    max_retries: int,
    provider_name: str,
    redact_secret: Optional[str] = None,
) -> "requests.Response":
    """
    Provider-independent "POST a JSON payload, retrying up to
    `max_retries` additional times on a transient network failure"
    helper, factored out of what was originally
    `OpenAICompatibleLLMClient._post_with_retries` so `GeminiLLMClient`
    (`gemini_client.py`, Phase 3.5) does not need its own copy of the
    same retry loop -- see this project's "no duplicated provider
    logic" engineering requirement. Every provider's HTTP transport
    ultimately reduces to "POST JSON, get JSON back", so this is
    genuinely provider-independent; only the URL, payload shape, and
    headers differ per provider, and those are supplied by the caller.

    Deliberately simple (no exponential backoff, no jitter) -- see the
    original docstring this was extracted from, immediately below on
    `OpenAICompatibleLLMClient`, for why that is a considered choice
    for this project's load profile, not an oversight.

    Raises `LLMTimeoutError` after the final attempt times out, or
    `LLMProviderError` after the final attempt hits any other
    `requests` exception (connection error, DNS failure, TLS error,
    ...). A non-2xx HTTP status is returned to the caller as an
    ordinary `requests.Response` (not raised here) since interpreting
    the response body to build a useful error message is provider-
    specific -- each concrete client does that itself.

    `redact_secret`, when supplied, is stripped from a `requests`
    exception's own message before it is placed into
    `LLMProviderError` -- defense in depth on top of the fact that
    `requests`' own exception text does not include the `headers` this
    function was called with (see `_redact`'s docstring for why this
    belt-and-suspenders check exists at all).
    """
    last_exc: Optional[Exception] = None
    attempts = max_retries + 1
    for attempt in range(attempts):
        try:
            return requests.post(
                url, json=json_payload, headers=headers, timeout=timeout_seconds
            )
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            if attempt == attempts - 1:
                raise LLMTimeoutError(
                    f"LLM request to provider {provider_name!r} timed out "
                    f"after {timeout_seconds}s ({attempts} attempt(s))."
                ) from exc
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt == attempts - 1:
                raise LLMProviderError(
                    f"LLM request to provider {provider_name!r} failed "
                    f"after {attempts} attempt(s): "
                    f"{_redact(str(exc), redact_secret)}"
                ) from exc
    raise AssertionError("unreachable") from last_exc


@dataclass(frozen=True)
class LLMRequest:
    """
    Everything an `LLMClient` needs to make one LLM call, fully
    resolved by `PromptBuilder` before this object is constructed.

    A dedicated value object (rather than passing `PromptBuilder` and
    `LLMClient` around and letting the client pull values out of it)
    is what makes `LLMClient` provider-independent in practice: this
    class has no knowledge of *where* these values came from (a prompt
    file, a YAML config, an environment variable), only what an LLM
    call needs to be fully specified.
    """

    #: The Phase 3.3 parser prompt, loaded verbatim -- sent as the
    #: system message.
    system_prompt: str

    #: The user's raw natural language instruction -- sent as the user
    #: message, unmodified (see `PromptBuilder`'s docstring for why it
    #: is never rewritten or summarized before this point).
    user_message: str

    #: Decoding parameters, sourced from `prompt_config.yaml` by
    #: `PromptBuilder` -- never chosen by `LLMClient` itself, which
    #: keeps "how creative/deterministic should the model be" a prompt
    #: concern, not a transport concern.
    temperature: float
    top_p: float
    max_tokens: int
    frequency_penalty: float
    presence_penalty: float

    #: Whether the caller prefers the provider's native structured
    #: JSON output mode, per `prompt_config.yaml`'s
    #: `output.strict_json_mode`. A preference, not a guarantee -- see
    #: that file's own comment on this field for why.
    strict_json_mode: bool

    #: Carried through for observability only (see this package's
    #: `agent.py` for how they surface) -- never sent to the provider.
    prompt_version: str
    schema_version: str


@dataclass(frozen=True)
class LLMResponse:
    """
    The raw result of one LLM call, already unwrapped from the
    provider's transport envelope into a plain text string -- but
    deliberately *not* parsed as JSON or validated in any way. That is
    `ResponseParser`'s and `SchemaValidator`'s job respectively; giving
    `LLMClient` a reason to touch the content's structure would break
    the separation of concerns this whole package is built around.
    """

    #: The assistant's raw text output, exactly as the provider
    #: returned it (may or may not be valid JSON, may or may not be
    #: wrapped in a markdown code fence -- `ResponseParser` decides).
    content: str

    #: Which provider/model actually produced this response --
    #: observability metadata, not re-derived from `LLMRequest` since
    #: a provider may report back a resolved model version different
    #: from the one requested (e.g. an alias resolving to a dated
    #: snapshot).
    provider: str
    model: str

    #: Wall-clock time the request took, in milliseconds. Exposed for
    #: future observability (see this package's `agent.py`) without
    #: requiring a logging framework -- see this repository's
    #: Observability requirements for Phase 3.4.
    latency_ms: float

    #: `{"prompt_tokens": int, "completion_tokens": int}` when the
    #: provider's response envelope included a real OpenAI-style
    #: `usage` object (Ollama's OpenAI-compatible endpoint does, as of
    #: the `qwen2.5:7b` runs this field was added for); `None` when the
    #: provider didn't return one. This is the provider's own reported
    #: count, never estimated here -- a caller wanting a token estimate
    #: for a provider that omits `usage` must compute its own
    #: heuristic (see `planning_evaluation/run_benchmark.py`'s
    #: cost/latency instrumentation for exactly that, clearly labeled
    #: as an approximation, not this field).
    usage: Optional[Dict[str, int]] = None


@runtime_checkable
class LLMClient(Protocol):
    """
    The provider-independent contract every LLM client implementation
    must satisfy. A `typing.Protocol` rather than an ABC: any object
    with a matching `complete()` method satisfies this type, whether or
    not it inherits from anything in this file -- which is exactly what
    lets `backend/language/`'s tests supply a minimal fake client with
    no dependency on this module beyond the type hint itself.
    """

    def complete(self, request: LLMRequest) -> LLMResponse:
        """
        Sends `request` to the configured LLM and returns its raw
        response. Implementations must raise `LLMTimeoutError` on a
        timeout and `LLMProviderError` for every other failure mode
        (network error, non-2xx status, malformed transport envelope)
        -- never let a provider-SDK-specific or `requests`-specific
        exception escape this method, since that would leak an
        implementation detail into `LanguageAgent`, defeating the
        purpose of this abstraction.
        """
        ...


def _redact(text: str, secret: Optional[str]) -> str:
    """
    Removes any literal occurrence of `secret` (the resolved API key)
    from `text` before it is ever placed in an exception message.
    Defense in depth on top of the fact that no code path in this file
    deliberately interpolates the key into a message: provider error
    bodies are outside this project's control, and a provider could in
    principle echo a header back in a diagnostic payload.
    """
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")


class OpenAICompatibleLLMClient:
    """
    `LLMClient` implementation for any provider exposing an
    OpenAI-compatible chat-completions HTTP endpoint -- OpenAI itself,
    or a self-hosted server (vLLM, Ollama, ...) fronting Qwen, Llama,
    or Phi with the same request/response contract. See this module's
    docstring for why one implementation covers this much of
    `prompt_config.yaml`'s `model_compatibility` list without a
    provider-specific SDK per entry.

    Deliberately built on `requests` rather than an LLM-specific SDK:
    every provider this project currently targets speaks HTTP/JSON, so
    a single lightweight HTTP client avoids a proliferation of
    heavyweight, largely-overlapping provider SDK dependencies for a
    research project that does not yet know which provider it will
    standardize on (Phase 3.6 benchmarks that decision).
    """

    def __init__(self, config: LLMRuntimeConfig) -> None:
        # Stored as the config object, not as unpacked fields -- keeps
        # this class's constructor stable if `LLMRuntimeConfig` grows
        # new fields later (e.g. custom headers for a new provider).
        self._config = config

    def complete(self, request: LLMRequest) -> LLMResponse:
        """
        Executes one chat-completion call. Structured as three
        phases -- resolve credentials, send the request, unwrap the
        response -- each of which maps to exactly one documented
        failure mode (`ConfigurationError`, `LLMTimeoutError`/
        `LLMProviderError`, `LLMProviderError` respectively), so a
        caller catching `LanguageRuntimeError` subclasses can tell
        which phase failed without inspecting message text.

        A *transient* network failure (timeout, connection reset) is
        retried up to `LLMRuntimeConfig.max_retries` additional times
        before giving up -- this is a network-reliability concern, not
        the schema-validation repair loop Phase 3.5 owns (see this
        class's docstring and `prompt_config.yaml`'s
        `output.max_retries`, a different setting for a different
        failure mode). A non-2xx response or a malformed envelope is
        never retried: those indicate the provider actively rejected
        or misunderstood the request, and resending the identical
        request would fail identically.
        """
        api_key = self._resolve_api_key()

        payload: Dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_message},
            ],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "frequency_penalty": request.frequency_penalty,
            "presence_penalty": request.presence_penalty,
        }
        # Only attached when requested -- an OpenAI-compatible server
        # that doesn't support this field would otherwise reject the
        # whole request, and `prompt_config.yaml` already documents
        # `strict_json_mode` as a preference, not a guarantee (see its
        # own comment on that field).
        if request.strict_json_mode:
            payload["response_format"] = {"type": "json_object"}

        started_at = time.monotonic()
        http_response = post_json_with_retries(
            url=f"{self._config.base_url.rstrip('/')}/chat/completions",
            json_payload=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout_seconds=self._config.timeout_seconds,
            max_retries=self._config.max_retries,
            provider_name=self._config.provider,
            redact_secret=api_key,
        )
        latency_ms = (time.monotonic() - started_at) * 1000.0

        if not http_response.ok:
            raise LLMProviderError(
                f"Provider {self._config.provider!r} returned HTTP "
                f"{http_response.status_code}: "
                f"{self._safe_error_detail(http_response.text, api_key)}"
            )

        return self._parse_envelope(http_response, latency_ms, api_key)

    def _resolve_api_key(self) -> str:
        """
        Reads the API key from the environment variable named by
        `LLMRuntimeConfig.api_key_env_var` -- resolved here, at call
        time, rather than at construction time, so constructing an
        `OpenAICompatibleLLMClient` (e.g. while wiring up a
        `LanguageAgent` in a process that will never actually call the
        LLM, such as most of this repository's test suite) never
        requires a key to be present.
        """
        api_key = os.environ.get(self._config.api_key_env_var)
        if not api_key:
            raise ConfigurationError(
                f"Environment variable {self._config.api_key_env_var!r} "
                f"(configured via LANGUAGE_LLM_API_KEY_ENV_VAR) is not set. "
                f"An API key is required to call provider "
                f"{self._config.provider!r}."
            )
        return api_key

    @staticmethod
    def _safe_error_detail(body: str, api_key: Optional[str]) -> str:
        """
        Truncates and redacts a provider's raw error response body
        before it is placed into an exception message -- delegates to
        this module's shared `_truncate_and_redact` (see `redact`'s
        docstring for why this logic is now shared with
        `gemini_client.py`).
        """
        return _truncate_and_redact(body, api_key)

    def _parse_envelope(
        self,
        http_response: "requests.Response",
        latency_ms: float,
        api_key: Optional[str],
    ) -> LLMResponse:
        """
        Extracts the assistant's text content from the OpenAI-shaped
        response envelope (`choices[0].message.content`). A malformed
        envelope (valid HTTP 200, but not the expected JSON shape) is
        still this client's problem to report, not `ResponseParser`'s
        -- see this module's docstring for why envelope-shape failures
        belong here rather than there.
        """
        try:
            envelope = http_response.json()
            content = envelope["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                f"Provider {self._config.provider!r} returned a response "
                f"that does not match the expected OpenAI-compatible "
                f"envelope shape: {self._safe_error_detail(http_response.text, api_key)}"
            ) from exc

        raw_usage = envelope.get("usage")
        usage: Optional[Dict[str, int]] = None
        if (
            isinstance(raw_usage, dict)
            and "prompt_tokens" in raw_usage
            and "completion_tokens" in raw_usage
        ):
            try:
                usage = {
                    "prompt_tokens": int(raw_usage["prompt_tokens"]),
                    "completion_tokens": int(raw_usage["completion_tokens"]),
                }
            except (TypeError, ValueError):
                usage = None

        return LLMResponse(
            content=content,
            provider=self._config.provider,
            model=envelope.get("model", self._config.model),
            latency_ms=latency_ms,
            usage=usage,
        )
