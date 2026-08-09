"""
prompt_builder.py

Purpose
-------
Turns the Phase 3.3 runtime prompt assets (`backend/prompts/`) and one
natural language instruction into a fully-specified `LLMRequest`
(`llm_client.py`) -- the only component in the Language Parsing Runtime
that knows those asset files exist, where they live, or how they are
formatted. `LanguageAgent` (`agent.py`) calls `PromptBuilder.build()`
and receives back a self-contained request object; it never opens a
file or parses YAML itself.

Why prompt text is never embedded in Python
------------------------------------------------
`parser_prompt.txt` is production software with its own version history
(`backend/prompts/prompt_version.md`) reviewed independently of any
code change -- see that file's versioning policy. If this module copied
the prompt text into a Python string literal, the two would inevitably
drift (an edit to one and not the other), and every prompt change would
require a code review and deploy cycle instead of a data change. This
module only ever *reads* `parser_prompt.txt` and `prompt_config.yaml`
from disk; the files themselves remain the single source of truth,
exactly as their own docstrings specify.

Runtime assets vs. research/benchmark datasets
----------------------------------------------------
`backend/prompts/README.md` draws a deliberate line: `parser_prompt.txt`
and `prompt_config.yaml` under `backend/prompts/` are what a running
Language Agent loads; `datasets/language/prompts/examples.json` (few-shot
examples), `negative_examples.json`, and `edge_cases.json` are
research/review data that a prompt engineer reviews `parser_prompt.txt`
against -- not, by default, something this class loads. This module
honors that split: few-shot injection from `examples.json` only
activates when a caller explicitly configures
`PromptAssetPaths.few_shot_examples_path`
(`config.py`) -- it is never guessed at or enabled implicitly, per this
repository's instruction to "not treat benchmark datasets as runtime
prompt assets unless explicitly configured."

Caching policy
------------------
`parser_prompt.txt` and `prompt_config.yaml` are static for the
lifetime of a `PromptBuilder` instance -- re-reading them from disk on
every `build()` call would be pure overhead with no correctness
benefit (the files do not change while a process is running). Both are
loaded lazily on first use and cached on the instance; see
`_load_system_prompt` and `_load_prompt_config`. This mirrors
`SchemaValidator`'s `TypeAdapter` caching for the same reason -- see
that class's docstring.

What this file must never do
---------------------------------
- Never call an LLM (`LLMClient`'s job).
- Never parse an LLM's response (`ResponseParser`'s job).
- Never validate a task (`SchemaValidator`'s job).
- Never decide planning behavior (out of scope for this phase
  entirely -- see Phase 4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from language.config import PromptAssetPaths
from language.exceptions import PromptLoadError
from language.llm_client import LLMRequest

# Required top-level keys this module reads out of `prompt_config.yaml`.
# Listed explicitly (rather than trusting `.get(..., default)` for
# everything) so a malformed or incomplete config file fails loudly at
# load time with a specific key name, instead of silently falling back
# to a Python-side default that would make `prompt_config.yaml` a lie
# about what's actually being sent to the LLM.
_REQUIRED_CONFIG_KEYS = ("prompt_version", "schema_version", "decoding", "output")
_REQUIRED_DECODING_KEYS = (
    "temperature",
    "top_p",
    "max_tokens",
    "frequency_penalty",
    "presence_penalty",
)
_REQUIRED_OUTPUT_KEYS = ("strict_json_mode",)


@dataclass(frozen=True)
class PromptAssetConfig:
    """
    The subset of `prompt_config.yaml` this runtime actually consumes,
    parsed into a typed shape. Deliberately does not mirror every key
    in the YAML file (e.g. `model_compatibility` and `notes` are
    reference/documentation content for humans, not runtime inputs --
    see `prompt_config.yaml`'s own comments) -- only fields an
    `LLMRequest` needs are represented here, keeping this class's
    surface a direct reflection of what actually reaches an LLM call.
    """

    prompt_version: str
    schema_version: str
    temperature: float
    top_p: float
    max_tokens: int
    frequency_penalty: float
    presence_penalty: float
    strict_json_mode: bool

    @classmethod
    def from_mapping(cls, raw: Dict[str, Any], *, source: Path) -> "PromptAssetConfig":
        """
        Builds a `PromptAssetConfig` from the parsed YAML mapping,
        raising `PromptLoadError` with the offending key name for any
        missing required field -- see this module's
        `_REQUIRED_CONFIG_KEYS` for why an explicit check is used
        instead of permissive defaults.
        """
        missing_top = [key for key in _REQUIRED_CONFIG_KEYS if key not in raw]
        if missing_top:
            raise PromptLoadError(
                f"{source} is missing required key(s): {missing_top}."
            )

        decoding = raw["decoding"]
        missing_decoding = [
            key for key in _REQUIRED_DECODING_KEYS if key not in decoding
        ]
        if missing_decoding:
            raise PromptLoadError(
                f"{source}'s 'decoding' section is missing required "
                f"key(s): {missing_decoding}."
            )

        output = raw["output"]
        missing_output = [key for key in _REQUIRED_OUTPUT_KEYS if key not in output]
        if missing_output:
            raise PromptLoadError(
                f"{source}'s 'output' section is missing required "
                f"key(s): {missing_output}."
            )

        return cls(
            prompt_version=str(raw["prompt_version"]),
            schema_version=str(raw["schema_version"]),
            temperature=float(decoding["temperature"]),
            top_p=float(decoding["top_p"]),
            max_tokens=int(decoding["max_tokens"]),
            frequency_penalty=float(decoding["frequency_penalty"]),
            presence_penalty=float(decoding["presence_penalty"]),
            strict_json_mode=bool(output["strict_json_mode"]),
        )


class PromptBuilder:
    """
    Loads Phase 3.3's runtime prompt assets and assembles them, with
    one caller-supplied instruction, into an `LLMRequest`.

    Constructed from a `PromptAssetPaths` (`config.py`) rather than
    loose path arguments -- keeps this constructor stable as
    `PromptAssetPaths` gains fields, and keeps path resolution
    (environment variables, defaults) entirely in `config.py`, where
    it belongs.
    """

    def __init__(self, paths: PromptAssetPaths) -> None:
        self._paths = paths
        self._system_prompt_cache: Optional[str] = None
        self._prompt_config_cache: Optional[PromptAssetConfig] = None
        self._few_shot_cache: Optional[str] = None

    def build(self, instruction: str) -> LLMRequest:
        """
        Assembles one `LLMRequest` for `instruction`. The instruction
        text itself is passed through unmodified as the user message --
        this method never rewrites, summarizes, or otherwise alters
        user intent (that would silently violate `parser_prompt.txt`'s
        own "preserve intent" principle before the LLM ever sees the
        instruction).

        When few-shot injection is configured
        (`PromptAssetPaths.few_shot_examples_path` is not `None`), the
        formatted examples are appended to the system prompt, after
        `parser_prompt.txt`'s own content -- additive, never replacing
        any of `parser_prompt.txt`'s instructions.
        """
        system_prompt = self._load_system_prompt()
        config = self._load_prompt_config()

        few_shot_block = self._load_few_shot_block()
        if few_shot_block:
            system_prompt = f"{system_prompt}\n\n{few_shot_block}"

        return LLMRequest(
            system_prompt=system_prompt,
            user_message=instruction,
            temperature=config.temperature,
            top_p=config.top_p,
            max_tokens=config.max_tokens,
            frequency_penalty=config.frequency_penalty,
            presence_penalty=config.presence_penalty,
            strict_json_mode=config.strict_json_mode,
            prompt_version=config.prompt_version,
            schema_version=config.schema_version,
        )

    def _load_system_prompt(self) -> str:
        """
        Loads and caches `parser_prompt.txt` verbatim. Raises
        `PromptLoadError` if the file is missing or unreadable --
        never falls back to an inline default, since a silent fallback
        would mean the Language Agent could run with a system prompt
        no one reviewed or versioned.
        """
        if self._system_prompt_cache is None:
            path = self._paths.parser_prompt_path
            if not path.is_file():
                raise PromptLoadError(
                    f"Parser prompt file not found: {path}. Expected "
                    f"the Phase 3.3 runtime asset at this path -- see "
                    f"backend/prompts/README.md."
                )
            try:
                self._system_prompt_cache = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise PromptLoadError(
                    f"Failed to read parser prompt file {path}: {exc}"
                ) from exc
        return self._system_prompt_cache

    def _load_prompt_config(self) -> PromptAssetConfig:
        """
        Loads, parses, and caches `prompt_config.yaml`. Raises
        `PromptLoadError` for a missing file or invalid YAML, and lets
        `PromptAssetConfig.from_mapping` raise the same exception type
        for a structurally incomplete file -- from this method's
        caller's perspective, every way this step can fail is one
        exception type.
        """
        if self._prompt_config_cache is None:
            path = self._paths.prompt_config_path
            if not path.is_file():
                raise PromptLoadError(
                    f"Prompt config file not found: {path}. Expected "
                    f"the Phase 3.3 runtime asset at this path -- see "
                    f"backend/prompts/README.md."
                )
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise PromptLoadError(
                    f"Failed to load prompt config file {path}: {exc}"
                ) from exc
            if not isinstance(raw, dict):
                raise PromptLoadError(
                    f"Prompt config file {path} did not parse to a "
                    f"YAML mapping (got {type(raw).__name__})."
                )
            self._prompt_config_cache = PromptAssetConfig.from_mapping(raw, source=path)
        return self._prompt_config_cache

    def _load_few_shot_block(self) -> Optional[str]:
        """
        Loads and formats few-shot examples from
        `PromptAssetPaths.few_shot_examples_path`, if configured --
        returns `None` when that path is unset (the default), meaning
        no few-shot content is added and this method's caller falls
        back to `parser_prompt.txt`'s own inline worked examples
        unchanged.

        The expected file shape matches
        `datasets/language/prompts/examples.json`: a JSON object with
        an `"examples"` array of `{"input": ..., "expected_output":
        ...}` entries (see that file for the authoritative shape). This
        method only ever reads that shape -- it does not know or care
        that the file happens to live under `datasets/language/`,
        since the path is fully caller-configured.
        """
        if self._paths.few_shot_examples_path is None:
            return None
        if self._few_shot_cache is not None:
            return self._few_shot_cache

        path = self._paths.few_shot_examples_path
        if not path.is_file():
            raise PromptLoadError(
                f"Configured few-shot examples file not found: {path}."
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PromptLoadError(
                f"Failed to load few-shot examples file {path}: {exc}"
            ) from exc

        examples: List[Dict[str, Any]] = (
            raw.get("examples", []) if isinstance(raw, dict) else []
        )
        selected = examples[: self._paths.few_shot_example_count]
        if not selected:
            self._few_shot_cache = None
            return None

        formatted = ["ADDITIONAL FEW-SHOT EXAMPLES"]
        for index, example in enumerate(selected, start=1):
            formatted.append(
                f"\nExample {index}:\n"
                f"Input: {example.get('input', '')}\n"
                f"Output: {json.dumps(example.get('expected_output', {}))}"
            )
        self._few_shot_cache = "\n".join(formatted)
        return self._few_shot_cache
