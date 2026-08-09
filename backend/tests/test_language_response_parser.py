"""
test_language_response_parser.py

Purpose
-------
Verifies `ResponseParser.parse()` against every documented case: valid
JSON, invalid JSON, unexpected (non-object) output, an empty response,
and a markdown-fenced response (the one "provider response wrapper"
case this module is responsible for -- see its module docstring for
why that is distinct from `LLMClient`'s transport-envelope unwrapping).
"""

from __future__ import annotations

import pytest

from language.exceptions import ResponseParsingError
from language.llm_client import LLMResponse
from language.response_parser import ResponseParser


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, provider="fake", model="fake-model", latency_ms=0.0
    )


class TestValidJSON:
    def test_parses_object_into_dict(self) -> None:
        result = ResponseParser().parse(
            _response('{"task_type": "single", "goal": "fetch"}')
        )
        assert result == {"task_type": "single", "goal": "fetch"}

    def test_leading_trailing_whitespace_is_tolerated(self) -> None:
        result = ResponseParser().parse(_response('  \n {"task_type": "single"} \n  '))
        assert result == {"task_type": "single"}


class TestInvalidJSON:
    def test_malformed_json_raises_response_parsing_error(self) -> None:
        with pytest.raises(ResponseParsingError):
            ResponseParser().parse(_response('{"task_type": "single",}'))

    def test_truncated_json_raises_response_parsing_error(self) -> None:
        with pytest.raises(ResponseParsingError):
            ResponseParser().parse(_response('{"task_type": "single"'))

    def test_prose_before_json_raises_response_parsing_error(self) -> None:
        # The model adding a sentence before the JSON object violates
        # parser_prompt.txt's JSON-only contract -- this must be
        # rejected, not repaired by discarding the prose (that would
        # cross into "fabricating" acceptable output from an
        # instruction-violating response).
        with pytest.raises(ResponseParsingError):
            ResponseParser().parse(
                _response('Sure, here is the JSON: {"task_type": "single"}')
            )


class TestUnexpectedOutput:
    def test_top_level_array_is_rejected(self) -> None:
        with pytest.raises(ResponseParsingError):
            ResponseParser().parse(_response('[{"task_type": "single"}]'))

    def test_top_level_string_is_rejected(self) -> None:
        with pytest.raises(ResponseParsingError):
            ResponseParser().parse(_response('"just a string"'))

    def test_top_level_number_is_rejected(self) -> None:
        with pytest.raises(ResponseParsingError):
            ResponseParser().parse(_response("42"))


class TestEmptyResponse:
    def test_empty_string_raises_response_parsing_error(self) -> None:
        with pytest.raises(ResponseParsingError):
            ResponseParser().parse(_response(""))

    def test_whitespace_only_raises_response_parsing_error(self) -> None:
        with pytest.raises(ResponseParsingError):
            ResponseParser().parse(_response("   \n\t  "))


class TestMarkdownFenceWrapper:
    """
    Covers the one "provider response wrapper" case this module owns:
    a markdown code fence wrapping the model's entire JSON output --
    see this module's docstring for why this differs from
    `LLMClient`'s transport-envelope unwrapping.
    """

    def test_json_fence_is_stripped(self) -> None:
        content = '```json\n{"task_type": "single"}\n```'
        result = ResponseParser().parse(_response(content))
        assert result == {"task_type": "single"}

    def test_bare_fence_is_stripped(self) -> None:
        content = '```\n{"task_type": "single"}\n```'
        result = ResponseParser().parse(_response(content))
        assert result == {"task_type": "single"}

    def test_partial_fence_is_not_stripped_and_fails_to_parse(self) -> None:
        # A fence that does not wrap the *entire* response is left
        # alone (see this module's `_FULL_FENCE_PATTERN` docstring) --
        # this content is correctly rejected as invalid JSON rather
        # than silently repaired.
        content = 'Note: ```json\n{"task_type": "single"}\n``` was the result'
        with pytest.raises(ResponseParsingError):
            ResponseParser().parse(_response(content))
