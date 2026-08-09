"""
test_language_prompt_builder.py

Purpose
-------
Verifies `PromptBuilder`'s asset-loading and `LLMRequest`-assembly
behavior: successful loads, missing files, malformed configuration,
correct propagation of `prompt_version`/`schema_version`, asset
caching, and opt-in few-shot injection.

Test strategy
-----------------
Most tests use isolated, hand-written fixture files under `tmp_path`
rather than the real `backend/prompts/` assets, so this suite is not
coupled to `parser_prompt.txt`'s actual wording and does not need
updating every time that file's content changes (only its *shape* --
what keys `prompt_config.yaml` must have -- is under test here).
`TestRealRepositoryAssets` is the deliberate exception: it loads this
repository's actual Phase 3.3 assets to verify they are still loadable
and that `prompt_config.yaml`'s `schema_version` has not silently
drifted from `schemas.metadata.SCHEMA_VERSION` -- the exact invariant
`prompt_config.yaml`'s own docstring warns could go stale.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from language.config import PromptAssetPaths
from language.exceptions import PromptLoadError
from language.prompt_builder import PromptBuilder
from schemas.metadata import SCHEMA_VERSION

_VALID_PROMPT_CONFIG: dict = {
    "prompt_version": "9.9.9",
    "schema_version": "1.0.0",
    "decoding": {
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 512,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
    },
    "output": {
        "strict_json_mode": True,
    },
}


def _write_valid_assets(tmp_path: Path) -> PromptAssetPaths:
    prompt_path = tmp_path / "parser_prompt.txt"
    prompt_path.write_text("SYSTEM PROMPT CONTENT", encoding="utf-8")

    config_path = tmp_path / "prompt_config.yaml"
    config_path.write_text(yaml.safe_dump(_VALID_PROMPT_CONFIG), encoding="utf-8")

    return PromptAssetPaths(
        parser_prompt_path=prompt_path,
        prompt_config_path=config_path,
        few_shot_examples_path=None,
        few_shot_example_count=3,
    )


class TestPromptBuilderSuccess:
    def test_prompt_loads_successfully(self, tmp_path: Path) -> None:
        paths = _write_valid_assets(tmp_path)
        request = PromptBuilder(paths).build("Bring me the red mug.")

        assert request.system_prompt == "SYSTEM PROMPT CONTENT"
        assert request.user_message == "Bring me the red mug."

    def test_correct_prompt_version_and_schema_version(self, tmp_path: Path) -> None:
        paths = _write_valid_assets(tmp_path)
        request = PromptBuilder(paths).build("go to the kitchen")

        assert request.prompt_version == "9.9.9"
        assert request.schema_version == "1.0.0"

    def test_correct_prompt_asset_loading_of_decoding_params(
        self, tmp_path: Path
    ) -> None:
        paths = _write_valid_assets(tmp_path)
        request = PromptBuilder(paths).build("go to the kitchen")

        assert request.temperature == 0.2
        assert request.top_p == 0.9
        assert request.max_tokens == 512
        assert request.frequency_penalty == 0.0
        assert request.presence_penalty == 0.0
        assert request.strict_json_mode is True

    def test_instruction_text_passed_through_unmodified(self, tmp_path: Path) -> None:
        # PromptBuilder must never rewrite or summarize the user's
        # instruction -- see its module docstring's "preserve intent"
        # rationale.
        paths = _write_valid_assets(tmp_path)
        raw_instruction = "  Bring me the RED mug, please.  "
        request = PromptBuilder(paths).build(raw_instruction)
        assert request.user_message == raw_instruction

    def test_assets_are_cached_after_first_load(self, tmp_path: Path) -> None:
        paths = _write_valid_assets(tmp_path)
        builder = PromptBuilder(paths)

        first = builder.build("first instruction")
        # Mutate the underlying files after the first call -- if
        # PromptBuilder re-read from disk, the second call's prompt
        # version would change. It must not.
        paths.prompt_config_path.write_text(
            yaml.safe_dump({**_VALID_PROMPT_CONFIG, "prompt_version": "0.0.1"}),
            encoding="utf-8",
        )
        second = builder.build("second instruction")

        assert first.prompt_version == second.prompt_version == "9.9.9"


class TestPromptBuilderFailures:
    def test_missing_prompt_file_raises_prompt_load_error(self, tmp_path: Path) -> None:
        paths = _write_valid_assets(tmp_path)
        paths.parser_prompt_path.unlink()

        with pytest.raises(PromptLoadError):
            PromptBuilder(paths).build("go to the kitchen")

    def test_missing_prompt_config_raises_prompt_load_error(
        self, tmp_path: Path
    ) -> None:
        paths = _write_valid_assets(tmp_path)
        paths.prompt_config_path.unlink()

        with pytest.raises(PromptLoadError):
            PromptBuilder(paths).build("go to the kitchen")

    def test_malformed_yaml_raises_prompt_load_error(self, tmp_path: Path) -> None:
        paths = _write_valid_assets(tmp_path)
        paths.prompt_config_path.write_text("not: valid: yaml: [", encoding="utf-8")

        with pytest.raises(PromptLoadError):
            PromptBuilder(paths).build("go to the kitchen")

    def test_missing_required_key_raises_prompt_load_error(
        self, tmp_path: Path
    ) -> None:
        paths = _write_valid_assets(tmp_path)
        incomplete = {k: v for k, v in _VALID_PROMPT_CONFIG.items() if k != "decoding"}
        paths.prompt_config_path.write_text(
            yaml.safe_dump(incomplete), encoding="utf-8"
        )

        with pytest.raises(PromptLoadError):
            PromptBuilder(paths).build("go to the kitchen")

    def test_missing_nested_decoding_key_raises_prompt_load_error(
        self, tmp_path: Path
    ) -> None:
        paths = _write_valid_assets(tmp_path)
        broken = dict(_VALID_PROMPT_CONFIG)
        broken["decoding"] = {
            k: v
            for k, v in _VALID_PROMPT_CONFIG["decoding"].items()
            if k != "temperature"
        }
        paths.prompt_config_path.write_text(yaml.safe_dump(broken), encoding="utf-8")

        with pytest.raises(PromptLoadError):
            PromptBuilder(paths).build("go to the kitchen")


class TestFewShotInjection:
    def test_disabled_by_default(self, tmp_path: Path) -> None:
        paths = _write_valid_assets(tmp_path)
        request = PromptBuilder(paths).build("go to the kitchen")
        assert "FEW-SHOT" not in request.system_prompt

    def test_loaded_when_explicitly_configured(self, tmp_path: Path) -> None:
        paths = _write_valid_assets(tmp_path)
        examples_path = tmp_path / "examples.json"
        examples_path.write_text(
            json.dumps(
                {
                    "examples": [
                        {
                            "input": "Go to the kitchen.",
                            "expected_output": {"goal": "navigate_to"},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        paths_with_fewshot = PromptAssetPaths(
            parser_prompt_path=paths.parser_prompt_path,
            prompt_config_path=paths.prompt_config_path,
            few_shot_examples_path=examples_path,
            few_shot_example_count=1,
        )

        request = PromptBuilder(paths_with_fewshot).build("go to the kitchen")

        assert "FEW-SHOT" in request.system_prompt
        assert "Go to the kitchen." in request.system_prompt

    def test_missing_configured_fewshot_file_raises_prompt_load_error(
        self, tmp_path: Path
    ) -> None:
        paths = _write_valid_assets(tmp_path)
        paths_with_fewshot = PromptAssetPaths(
            parser_prompt_path=paths.parser_prompt_path,
            prompt_config_path=paths.prompt_config_path,
            few_shot_examples_path=tmp_path / "does_not_exist.json",
            few_shot_example_count=3,
        )

        with pytest.raises(PromptLoadError):
            PromptBuilder(paths_with_fewshot).build("go to the kitchen")


class TestRealRepositoryAssets:
    """
    Loads this repository's actual `backend/prompts/` assets -- the
    ones a real `LanguageAgent.from_config()` would load -- to catch a
    regression in the real files themselves, not just in
    `PromptBuilder`'s logic against synthetic fixtures.
    """

    def test_real_assets_load_successfully(self) -> None:
        paths = PromptAssetPaths.from_env()
        request = PromptBuilder(paths).build("Bring me the red mug.")

        assert len(request.system_prompt) > 0
        assert request.user_message == "Bring me the red mug."

    def test_real_schema_version_matches_metadata_schema_version(self) -> None:
        # This is exactly the drift `prompt_config.yaml`'s own
        # docstring warns about: if a schema bump ever lands without a
        # matching prompt_config.yaml update, this test is the signal.
        paths = PromptAssetPaths.from_env()
        request = PromptBuilder(paths).build("go to the kitchen")

        assert request.schema_version == SCHEMA_VERSION
