"""
test_language_repair.py

Purpose
-------
Verifies `SafeResponseRepairer` recovers a JSON object from every
documented SAFE wrapper pattern (a fenced block with surrounding prose,
bare prose-wrapped JSON with no fence), and -- just as importantly --
refuses to guess when a response is genuinely ambiguous or malformed,
per this module's UNSAFE examples (multiple candidate objects, a
truncated response, content with no JSON at all). It also verifies the
one hard safety invariant: the *content* of a recovered JSON object is
never altered, only the wrapper text around it is discarded.
"""

from __future__ import annotations

from language.repair import SafeResponseRepairer


class TestSafeRepairs:
    def test_recovers_json_from_fence_with_surrounding_prose(self) -> None:
        text = (
            'Sure, here\'s the task:\n```json\n{"task_type": "single", '
            '"goal": "fetch"}\n```\nLet me know if that helps!'
        )
        repaired = SafeResponseRepairer().repair(text)
        assert repaired == '{"task_type": "single", "goal": "fetch"}'

    def test_recovers_json_from_bare_prose_prefix(self) -> None:
        # Trailing content after the balanced object is deliberately
        # NOT covered here -- see TestUnsafeRefusals below for why a
        # trailing remainder is refused rather than discarded.
        text = 'The parsed task is: {"task_type": "single", "goal": "fetch"}'
        repaired = SafeResponseRepairer().repair(text)
        assert repaired == '{"task_type": "single", "goal": "fetch"}'

    def test_never_alters_field_values_inside_the_candidate(self) -> None:
        text = 'Here you go:\n```json\n{"object": "blue bottle"}\n```\n'
        repaired = SafeResponseRepairer().repair(text)
        assert repaired is not None
        # The exact substring, character for character -- proves no
        # rewriting of content occurred, only wrapper removal.
        assert '"object": "blue bottle"' in repaired

    def test_handles_braces_inside_string_values(self) -> None:
        text = 'Result: {"note": "use {curly} braces safely"}'
        repaired = SafeResponseRepairer().repair(text)
        assert repaired == '{"note": "use {curly} braces safely"}'


class TestUnsafeRefusals:
    def test_refuses_when_multiple_fences_present(self) -> None:
        text = '```json\n{"a": 1}\n```\nor maybe\n```json\n{"a": 2}\n```'
        assert SafeResponseRepairer().repair(text) is None

    def test_refuses_truncated_response(self) -> None:
        text = '{"task_type": "single", "goal": "fetch"'
        assert SafeResponseRepairer().repair(text) is None

    def test_refuses_when_no_json_present(self) -> None:
        text = "I cannot help with that request."
        assert SafeResponseRepairer().repair(text) is None

    def test_refuses_trailing_content_after_balanced_object(self) -> None:
        text = '{"a": 1} and also {"b": 2}'
        assert SafeResponseRepairer().repair(text) is None

    def test_refuses_invalid_json_inside_fence(self) -> None:
        text = "```json\n{not valid json}\n```"
        assert SafeResponseRepairer().repair(text) is None
