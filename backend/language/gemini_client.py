"""
gemini_client.py

Purpose
-------
The second concrete `LLMClient` (`llm_client.py`) implementation,
targeting Google's Gemini API directly via its REST
`generateContent` endpoint. Added in Phase 3.5 to satisfy this
project's requirement that the runtime support a free-tier-friendly
provider for development, without touching `LanguageAgent`,
`PromptBuilder`, `ResponseParser`, or `SchemaValidator` -- exactly the
provider-independence `llm_client.py`'s `LLMClient` protocol exists to
guarantee (see that module's docstring).

Why a dedicated Gemini-native client rather than an OpenAI-compatible
shim
----------------------------------------------------------------------
Google does publish an OpenAI-compatible endpoint for Gemini, which
would have let `OpenAICompatibleLLMClient` handle Gemini with zero new
code. This project deliberately does not take that shortcut: the
Phase 3.5 requirements explicitly ask for "a dedicated Gemini provider
abstraction so future Gemini-native capabilities can be used without
changing LanguageAgent" -- e.g. Gemini's own `responseMimeType`/
`responseSchema` structured-output controls, which are richer than the
OpenAI-compatible shim's `response_format` passthrough and are only
reachable through Gemini's native request shape. Isolating that
native shape inside this one file means a future improvement to how
this project uses Gemini's structured output never has to touch
`llm_client.py`'s provider-independent contract.

Why no `google-generativeai`/`google-genai` SDK dependency
-----------------------------------------------------------------
`OpenAICompatibleLLMClient` already established the precedent (see its
own docstring) of using `requests` directly rather than a
provider-specific SDK, for a research project not yet committed to any
one provider. Gemini's `generateContent` REST contract is simple
enough (a single JSON POST) that reusing `requests` -- and this
package's already-shared `post_json_with_retries`/`redact`/
`safe_error_detail` helpers (`llm_client.py`) -- avoids adding a new,
fairly heavy dependency to `backend/requirements.txt` purely to save
writing one request/response mapping. If a future phase needs a
Gemini-native capability this REST contract cannot express (e.g.
multi-turn function calling with complex state), that is the trigger
to add the official SDK -- not a default choice made preemptively here.

Gemini free-tier note
-------------------------
`gemini-flash-latest` (the default `LLMRuntimeConfig.model` when
`LANGUAGE_LLM_PROVIDER=gemini`, see `config.py`) is a Google-maintained
alias that points at a current Flash-tier model rather than a fixed
dated snapshot -- chosen so this project does not silently keep
pointing at a model Google has since deprecated. The model actually
used, and whether a free tier is currently available for it, are
controlled entirely by Google's API policies and the caller's own
Google AI Studio / Cloud project eligibility at request time -- this
client makes no assumption about pricing or quota, and
`LANGUAGE_LLM_MODEL` can be pointed at any other Gemini model without a
code change (see `LLMRuntimeConfig`).

Credential handling policy
------------------------------
Identical to `OpenAICompatibleLLMClient`: the API key is read from
`os.environ[config.api_key_env_var]` (default `GEMINI_API_KEY`) inside
`complete()`, immediately before use, never stored on `self`, and sent
as the `x-goog-api-key` request header -- never embedded in the
request URL, so it can never appear in a URL logged by an intermediate
proxy or in this client's own exception messages (which never include
request URLs verbatim for this reason).
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from language.config import LLMRuntimeConfig
from language.exceptions import ConfigurationError, LLMProviderError
from language.llm_client import (
    LLMRequest,
    LLMResponse,
    post_json_with_retries,
    safe_error_detail,
)


class GeminiLLMClient:
    """
    `LLMClient` implementation for Google's Gemini API. See this
    module's docstring for why this is a native REST client rather
    than an OpenAI-compatible-shim reuse or an SDK dependency.
    """

    def __init__(self, config: LLMRuntimeConfig) -> None:
        # Mirrors `OpenAICompatibleLLMClient.__init__` -- see that
        # class's docstring for why the whole config object is stored
        # rather than unpacked fields.
        self._config = config

    def complete(self, request: LLMRequest) -> LLMResponse:
        """
        Executes one Gemini `generateContent` call. Structured the
        same three ways as `OpenAICompatibleLLMClient.complete()`
        (resolve credentials, send the request, unwrap the response)
        so the two providers are easy to compare side by side and so
        both raise the same normalized exception vocabulary
        (`ConfigurationError`, `LLMTimeoutError`/`LLMProviderError`) --
        see `llm_client.py`'s module docstring, "Provider Error
        Normalization".
        """
        api_key = self._resolve_api_key()
        payload = self._build_payload(request)

        started_at = time.monotonic()
        http_response = post_json_with_retries(
            url=f"{self._config.base_url.rstrip('/')}/models/{self._config.model}:generateContent",
            json_payload=payload,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
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
                f"{safe_error_detail(http_response.text, api_key)}"
            )

        return self._parse_envelope(http_response, latency_ms, api_key)

    def _build_payload(self, request: LLMRequest) -> Dict[str, Any]:
        """
        Maps the provider-independent `LLMRequest` onto Gemini's native
        `generateContent` request shape. `system_prompt` becomes a
        `system_instruction` (Gemini's dedicated system-role field,
        analogous to OpenAI's `{"role": "system", ...}` message) and
        `user_message` becomes the sole entry in `contents` -- Gemini
        models a conversation as a list of turns even for this
        project's single-turn use, so a one-element list is the
        correct (not simplified) representation of "one user turn".
        """
        generation_config: Dict[str, Any] = {
            "temperature": request.temperature,
            "topP": request.top_p,
            "maxOutputTokens": request.max_tokens,
            "frequencyPenalty": request.frequency_penalty,
            "presencePenalty": request.presence_penalty,
        }
        # Gemini's native structured-output control -- the
        # Gemini-specific capability this dedicated client exists to
        # reach (see this module's docstring). Only requested when
        # `prompt_config.yaml`'s `strict_json_mode` asks for it, same
        # opt-in behavior as `OpenAICompatibleLLMClient`'s
        # `response_format`.
        if request.strict_json_mode:
            generation_config["responseMimeType"] = "application/json"

        return {
            "system_instruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_message}]}],
            "generationConfig": generation_config,
        }

    def _resolve_api_key(self) -> str:
        """Mirrors `OpenAICompatibleLLMClient._resolve_api_key` -- see its docstring."""
        api_key = os.environ.get(self._config.api_key_env_var)
        if not api_key:
            raise ConfigurationError(
                f"Environment variable {self._config.api_key_env_var!r} "
                f"(configured via LANGUAGE_LLM_API_KEY_ENV_VAR) is not set. "
                f"An API key is required to call provider "
                f"{self._config.provider!r}. Get a free-tier Gemini API "
                f"key from Google AI Studio and export it as this "
                f"variable -- see README.md's Gemini setup instructions."
            )
        return api_key

    def _parse_envelope(
        self,
        http_response: Any,
        latency_ms: float,
        api_key: Optional[str],
    ) -> LLMResponse:
        """
        Extracts the model's text output from Gemini's response
        envelope (`candidates[0].content.parts[*].text`, concatenated
        -- Gemini may split one turn's output across multiple `parts`)
        and normalizes two Gemini-specific failure shapes that are
        still HTTP 200 responses: no candidates at all, and a
        candidate whose `finishReason` indicates the model refused to
        answer (e.g. `"SAFETY"`) rather than actually producing
        content. Both are reported as `LLMProviderError`, matching
        `OpenAICompatibleLLMClient._parse_envelope`'s handling of a
        malformed-but-200 response.
        """
        try:
            envelope = http_response.json()
        except ValueError as exc:
            raise LLMProviderError(
                f"Provider {self._config.provider!r} returned a response "
                f"that is not valid JSON: "
                f"{safe_error_detail(http_response.text, api_key)}"
            ) from exc

        candidates = envelope.get("candidates") or []
        if not candidates:
            raise LLMProviderError(
                f"Provider {self._config.provider!r} returned no "
                f"candidates (prompt feedback: "
                f"{envelope.get('promptFeedback', 'none')})."
            )

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        if finish_reason not in (None, "STOP", "MAX_TOKENS"):
            raise LLMProviderError(
                f"Provider {self._config.provider!r} did not return "
                f"generated content (finishReason={finish_reason!r})."
            )

        try:
            parts: List[Dict[str, Any]] = candidate["content"]["parts"]
            content = "".join(part.get("text", "") for part in parts)
        except (KeyError, TypeError) as exc:
            raise LLMProviderError(
                f"Provider {self._config.provider!r} returned a response "
                f"that does not match the expected Gemini envelope shape: "
                f"{safe_error_detail(http_response.text, api_key)}"
            ) from exc

        return LLMResponse(
            content=content,
            provider=self._config.provider,
            model=envelope.get("modelVersion", self._config.model),
            latency_ms=latency_ms,
        )
