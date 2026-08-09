"""
repair.py

Purpose
-------
Implements conservative, deterministic *syntactic* repair of an LLM
response's raw text, as a last resort `recovery.py` reaches for only
after `ResponseParser.parse()` (`response_parser.py`) has already
failed. This module never touches the meaning of a response -- only
the non-JSON wrapper text real models occasionally emit around an
otherwise-correct JSON object (extra prose before/after a fenced code
block, a fence that isn't the entire response, an assistant preamble
like "Sure, here's the JSON:"). See this project's Phase 3.5
requirements, "Safe Response Repair", for the exact SAFE/UNSAFE
distinction this module is built to respect.

Why this is not part of `ResponseParser`
----------------------------------------------
`ResponseParser` already strips a markdown fence that wraps the
*entire* response -- a cheap, unconditional normalization applied on
every call, documented as safe in that module's own docstring. This
module handles the harder, more speculative case: wrapper text that is
*not* the entire response, where "safe" depends on being able to prove
the extracted candidate is valid, standalone JSON before trusting it.
Because that proof can fail (the candidate might not be valid JSON, or
there might be more than one plausible candidate), this is a distinct,
fallible operation with its own return contract (`Optional[str]`) --
folding it into `ResponseParser.parse()`, which currently either
succeeds or raises, would blur "this is the normal path" with "this is
a best-effort rescue attempt", which `recovery.py` needs to be able to
tell apart (a rescued response is recorded as `recovered=True`
observability data -- see `failures.py`'s `RuntimeMetadata`).

What this module must never do
-----------------------------------
- Never modify a single character *inside* the extracted JSON
  candidate -- only decide which substring of the original text *is*
  the candidate. The candidate's content reaches `SchemaValidator`
  completely unmodified, so a model's actual field values (e.g. "blue
  bottle" when the user asked for a red mug) are never silently
  rewritten -- that would be a semantic change, not a formatting one,
  and this phase's requirements are explicit that such a change must
  never happen automatically.
- Never guess at a repair when more than one plausible JSON object
  substring exists, and never repair anything if the result does not
  independently parse as valid JSON -- an unprovable repair is not a
  repair, it is a guess, and this module returns `None` in that case
  so `recovery.py` can classify the outcome as `SAFE_REPAIR_FAILED`
  rather than silently fabricating a result.
"""

from __future__ import annotations

import json
import re
from typing import Optional

# Matches a fenced code block *anywhere* in the text (unlike
# `response_parser.py`'s `_FULL_FENCE_PATTERN`, which only matches when
# the fence is the entire response) -- covers "Sure, here you go:\n
# ```json\n{...}\n```\nLet me know if that helps!". `re.DOTALL` so the
# JSON body inside the fence, which spans multiple lines, is captured
# as one group.
_FENCE_ANYWHERE_PATTERN = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def _extract_fenced_candidate(text: str) -> Optional[str]:
    """
    Looks for exactly one markdown code fence in `text` and returns its
    inner content if found. Returns `None` if no fence is present, or
    if more than one fence is found -- multiple fences make "which one
    is the real answer" ambiguous, and this module never guesses (see
    this module's docstring).
    """
    matches = _FENCE_ANYWHERE_PATTERN.findall(text)
    if len(matches) != 1:
        return None
    return matches[0].strip()


def _extract_braced_candidate(text: str) -> Optional[str]:
    """
    Scans `text` for exactly one balanced, top-level `{...}` substring
    and returns it. This is what rescues a response like "The parsed
    task is: {...}" with no code fence at all. Brace-depth counting is
    string-aware (a `{`/`}` inside a JSON string literal does not affect
    depth) so a field value containing a literal brace character does
    not corrupt the scan.

    Returns `None` if no `{` is found, if the braces are never balanced
    (a truncated response), or if scanning finds a second top-level
    `{...}` region after the first closes -- exactly the "more than one
    plausible candidate" case this module refuses to guess between.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    end: Optional[int] = None
    for index in range(start, len(text)):
        char = text[index]
        if escape_next:
            escape_next = False
            continue
        if char == "\\" and in_string:
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break

    if end is None:
        # Braces never balanced -- a truncated or malformed response,
        # not something this module can safely rescue.
        return None

    remainder = text[end + 1 :].strip()
    if remainder:
        # Trailing non-whitespace content after the first balanced
        # object could be a second candidate, or trailing prose that
        # itself might hide meaningful content -- either way, not
        # provably safe to discard. See this module's docstring.
        return None

    return text[start : end + 1]


class SafeResponseRepairer:
    """
    Stateless best-effort repairer for a raw LLM response string.
    Mirrors `ResponseParser`'s "no constructor state" shape -- see that
    class's docstring for why.
    """

    def repair(self, content: str) -> Optional[str]:
        """
        Attempts to recover a single, standalone, valid-JSON-object
        substring from `content`. Tries the fenced-block strategy
        first (the far more common real-world case -- most instruction
        -following models that add wrapper text still fence the JSON
        itself), then the balanced-brace strategy. Returns the
        recovered JSON text (still a string -- re-validation is
        `ResponseParser`'s job, not this module's, per this module's
        docstring on not duplicating that logic) or `None` if neither
        strategy produces a candidate that independently parses as a
        JSON object.
        """
        for candidate in (
            _extract_fenced_candidate(content),
            _extract_braced_candidate(content),
        ):
            if candidate is None:
                continue
            if self._is_valid_json_object(candidate):
                return candidate
        return None

    @staticmethod
    def _is_valid_json_object(candidate: str) -> bool:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return False
        return isinstance(parsed, dict)
