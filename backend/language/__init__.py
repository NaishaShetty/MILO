"""
backend/language/ -- Language Parsing Runtime (Phase 3.4)

Purpose
-------
This package is the runtime layer that connects Phase 3.1's language
interface design, Phase 3.2's `ParsedInstruction` schema
(`backend/schemas/task.py`), and Phase 3.3's prompt assets
(`backend/prompts/`) to an actual LLM, producing validated
`SingleTask`/`MultiTask` objects a future Planner (Phase 4) can
consume. It contains no planning, execution, memory, or vision logic --
its entire responsibility ends at returning a validated
`ParsedInstruction`.

Package layout and responsibility boundaries
--------------------------------------------------
- `agent.py` -- `LanguageAgent`, the orchestrator. The only class most
  callers need.
- `prompt_builder.py` -- loads `backend/prompts/` assets and builds an
  `LLMRequest`.
- `llm_client.py` -- provider-independent `LLMClient` protocol, the
  `LLMRequest`/`LLMResponse` value objects, and one concrete
  OpenAI-compatible implementation.
- `response_parser.py` -- raw LLM text -> Python `dict`.
- `schema_validator.py` -- Python `dict` -> validated
  `ParsedInstruction`, via Phase 3.2's schema.
- `config.py` -- environment-driven runtime/deployment configuration
  (provider, model, credentials, timeouts) -- distinct from
  `backend/prompts/prompt_config.yaml`'s decoding parameters.
- `exceptions.py` -- the exception vocabulary every component above
  raises instead of leaking a third-party library exception.

See each file's own module docstring for the full rationale behind its
boundaries, and `backend/docs/language_interface_spec.md` section 26.3
for the design record this package implements.

Public surface
------------------
Deliberately re-exports only what an external caller (a future
Planner, Phase 3.7's API layer, or a test) should ever need to import
directly: `LanguageAgent` to run the pipeline, `LanguageRuntimeConfig`
to configure it, and the exception hierarchy to handle its failures.
Every other name in this package (`PromptBuilder`, `LLMClient`,
`ResponseParser`, `SchemaValidator`, and their supporting types) is an
internal collaborator `LanguageAgent` wires together -- importable
directly for tests, but not part of this package's intended public
contract.
"""

from language.agent import LanguageAgent
from language.config import LanguageRuntimeConfig, LLMRuntimeConfig, PromptAssetPaths
from language.exceptions import (
    ConfigurationError,
    LanguageRuntimeError,
    LLMProviderError,
    LLMTimeoutError,
    PromptLoadError,
    ResponseParsingError,
    TaskValidationError,
)

__all__ = [
    "LanguageAgent",
    "LanguageRuntimeConfig",
    "LLMRuntimeConfig",
    "PromptAssetPaths",
    "LanguageRuntimeError",
    "ConfigurationError",
    "PromptLoadError",
    "LLMProviderError",
    "LLMTimeoutError",
    "ResponseParsingError",
    "TaskValidationError",
]
