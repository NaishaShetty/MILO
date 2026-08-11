"""
provider_factory.py

Purpose
-------
The one place that maps `LLMRuntimeConfig.provider` (a plain string,
per `config.py`'s deliberate choice not to make it a closed enum) onto
a concrete `LLMClient` implementation. Exists so `LanguageAgent.
from_config()` (`agent.py`) does not itself need an `if provider ==
"openai" ... elif provider == "gemini"` branch -- keeping that
selection logic in one small, dedicated, independently testable
function instead of inline in the orchestrator is what lets a future
provider (a self-hosted/local model, per this project's Phase 3.5
"Future local/self-hosted providers" requirement) be added by adding
one more `elif` here, with zero changes anywhere else.

Which component depends on this file
---------------------------------------
Only `LanguageAgent.from_config()` calls this. Tests should construct
a concrete `LLMClient` (or a fake) directly instead -- exactly like
every other Phase 3.4/3.5 test in this package -- so this factory's
only real caller is production wiring.
"""

from __future__ import annotations

from language.config import LLMRuntimeConfig
from language.exceptions import ConfigurationError
from language.gemini_client import GeminiLLMClient
from language.llm_client import LLMClient, OpenAICompatibleLLMClient

# Provider identifiers this factory knows how to construct a client
# for. Listed explicitly (rather than a bare `if/elif/else` with a
# silent fallback) so an unrecognized `LANGUAGE_LLM_PROVIDER` value
# fails loudly and immediately -- a misconfigured deployment should
# never silently fall back to OpenAI's contract for a provider name it
# doesn't recognize.
_SUPPORTED_PROVIDERS = ("openai", "gemini", "qwen")


def create_llm_client(config: LLMRuntimeConfig) -> LLMClient:
    """
    Constructs the `LLMClient` implementation matching
    `config.provider`. Raises `ConfigurationError` -- a
    `LLM_CONFIGURATION_ERROR` per `failures.py`'s taxonomy, and
    therefore never retried by `recovery.py` -- for an unrecognized
    provider name, since retrying a request against a client that was
    never constructible in the first place can never succeed.
    """
    if config.provider == "openai":
        return OpenAICompatibleLLMClient(config)
    if config.provider == "gemini":
        return GeminiLLMClient(config)
    if config.provider == "qwen":
        # A local/self-hosted Qwen server (vLLM, Ollama, ...) speaks
        # the same OpenAI-compatible chat-completions contract as
        # OpenAI itself -- see `llm_client.py`'s module docstring for
        # why `OpenAICompatibleLLMClient` already covers this case with
        # no new client class needed.
        return OpenAICompatibleLLMClient(config)
    raise ConfigurationError(
        f"Unsupported LLM provider {config.provider!r} (configured via "
        f"LANGUAGE_LLM_PROVIDER). Supported providers: "
        f"{', '.join(_SUPPORTED_PROVIDERS)}."
    )
