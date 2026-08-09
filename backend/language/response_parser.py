"""
response_parser.py

Purpose
-------
Converts an `LLMResponse`'s raw text content (`llm_client.py`) into a
plain Python `dict` that `SchemaValidator` can attempt to validate as a
`ParsedInstruction`. This is the layer that absorbs the gap between
"what an LLM actually outputs" (text that is *supposed* to be JSON, per
`parser_prompt.txt`'s instructions, but is produced by a model, not a
serializer) and "what a schema validator expects" (a Python object).

Why this is a separate component from `SchemaValidator`
------------------------------------------------------------
Two genuinely different failure modes live on either side of this
boundary. A response that isn't valid JSON at all (extra prose before
the object, a truncated response, empty output) is a *syntax* problem
this module detects without ever knowing what a `SingleTask` is. A
response that *is* valid JSON but has the wrong fields, wrong enum
values, or violates a cross-field invariant is a *schema* problem only
`SchemaValidator` (and, through it, Phase 3.2's Pydantic models) can
detect. Merging these into one component would mean every future schema
change (Phase 3.2 evolving) also risks touching JSON-syntax handling,
and every future provider-output quirk (this module evolving) risks
touching schema logic. Keeping them separate means each can change
independently -- exactly the separation of concerns this whole
`backend/language/` package is built around.

Where the "provider response wrapper" line is drawn
----------------------------------------------------------
`LLMClient` already unwraps the provider's *transport* envelope (e.g.
OpenAI's `choices[0].message.content`) before this module ever sees
anything -- see `llm_client.py`'s module docstring. What this module
handles is *content-level* wrapping the model itself may have produced
inside that already-extracted text: most commonly, a markdown code
fence (` ```json ... ``` `) around an otherwise-valid JSON object, which
real models produce occasionally even when explicitly instructed not
to (see `parser_prompt.txt`'s JSON-only output contract). Stripping a
fence is not "fabricating missing fields" -- the JSON payload itself is
used verbatim, only the non-JSON wrapper text around it is discarded.

What this module must never do
-----------------------------------
- Never invent a value for a missing field -- if the model's output is
  incomplete, `json.loads` either succeeds (producing whatever partial
  structure the model actually emitted, which `SchemaValidator` will
  then correctly reject if a required field is absent) or fails
  outright; this module does not paper over either case.
- Never call the LLM (that's `LLMClient`'s job, already done by the
  time a response reaches here).
- Never perform semantic/schema validation (that's `SchemaValidator`'s
  job, next in the pipeline).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from language.exceptions import ResponseParsingError
from language.llm_client import LLMResponse

# Matches an entire string that is a single fenced code block, e.g.
# "```json\n{...}\n```" or "```\n{...}\n```", capturing the fenced
# content. Anchored to the whole (stripped) string with DOTALL so a
# multi-line JSON body inside the fence is captured as one group --
# deliberately conservative: this only strips a fence that wraps the
# *entire* response, never a fence found partway through otherwise
# unstructured text, which would risk silently discarding real content
# instead of a pure formatting artifact.
_FULL_FENCE_PATTERN = re.compile(
    r"^```(?:json)?\s*\n(.*?)\n?```$",
    re.DOTALL,
)


class ResponseParser:
    """
    Stateless converter from `LLMResponse` to a Python `dict`. No
    constructor arguments and no instance state: this class exists to
    give the operation a name and a place to attach tests, not because
    it needs to remember anything between calls -- see this
    repository's "avoid unnecessary abstractions" engineering
    requirement.
    """

    def parse(self, response: LLMResponse) -> Dict[str, Any]:
        """
        Returns the parsed JSON object as a `dict`, or raises
        `ResponseParsingError`. Every rejection path below corresponds
        to one line in this module's docstring on what "reject
        unexpected output" means in practice -- each is deliberately
        specific in its message so a failure is diagnosable from the
        exception alone.
        """
        content = response.content

        if content is None or not content.strip():
            # An empty/whitespace-only response is never valid output
            # for a prompt that always asks for exactly one JSON
            # object -- treated as a parsing failure rather than
            # something `SchemaValidator` could ever meaningfully
            # reject with a useful per-field error.
            raise ResponseParsingError(
                "LLM response was empty; expected a JSON object."
            )

        text = self._strip_full_markdown_fence(content.strip())

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ResponseParsingError(
                f"LLM response was not valid JSON: {exc}"
            ) from exc

        if not isinstance(data, dict):
            # `parser_prompt.txt` always specifies a single JSON
            # *object* (never a bare array, string, or number) as the
            # output contract -- anything else, even if syntactically
            # valid JSON, cannot possibly satisfy `ParsedInstruction`
            # and is rejected here rather than being handed to
            # `SchemaValidator` to fail on with a less specific error.
            raise ResponseParsingError(
                f"LLM response was valid JSON but not a JSON object "
                f"(got {type(data).__name__})."
            )

        return data

    @staticmethod
    def _strip_full_markdown_fence(text: str) -> str:
        """
        Removes a markdown code fence that wraps the *entire* response,
        if present, and returns its inner content unchanged. Returns
        `text` unmodified when no such fence is found -- the common
        case, since `parser_prompt.txt` asks for bare JSON with no
        fence at all.
        """
        match = _FULL_FENCE_PATTERN.match(text)
        return match.group(1) if match else text
