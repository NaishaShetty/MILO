"""
test_execution_resolver.py

Purpose
-------
Unit tests for `execution.resolver.ObjectResolver` -- exact name
matching, distance-based tie-breaking, pass-through of an
already-resolved AI2-THOR id, no-match handling, and the `_ALIASES`
vocabulary bridge (`"refrigerator"` <-> `"Fridge"`) added after a real
AI2-THOR run showed the plain match failing on this project's own
"store the apple in the refrigerator" demo -- see
`docs/phases/phase5_execution.md`'s "Post-implementation fixes".
"""

from __future__ import annotations

from execution.resolver import ObjectResolver


def _metadata(objects):
    return {"objects": objects}


def test_resolves_exact_case_insensitive_match():
    resolver = ObjectResolver()
    metadata = _metadata(
        [{"objectId": "Apple|1", "objectType": "Apple", "distance": 1.0}]
    )
    assert resolver.resolve("apple", metadata) == "Apple|1"
    assert resolver.resolve("APPLE", metadata) == "Apple|1"


def test_returns_none_when_no_object_matches():
    resolver = ObjectResolver()
    metadata = _metadata(
        [{"objectId": "Apple|1", "objectType": "Apple", "distance": 1.0}]
    )
    assert resolver.resolve("banana", metadata) is None


def test_returns_none_for_empty_or_missing_name():
    resolver = ObjectResolver()
    metadata = _metadata([])
    assert resolver.resolve(None, metadata) is None
    assert resolver.resolve("", metadata) is None


def test_passes_through_an_already_resolved_object_id():
    resolver = ObjectResolver()
    # Contains AI2-THOR's own "|" id separator -- treated as already
    # resolved, no metadata lookup performed.
    assert resolver.resolve("Apple|+00.90|+00.90|-00.28", {"objects": []}) == (
        "Apple|+00.90|+00.90|-00.28"
    )


def test_prefers_the_nearest_candidate_when_multiple_match():
    resolver = ObjectResolver()
    metadata = _metadata(
        [
            {"objectId": "Mug|far", "objectType": "Mug", "distance": 5.0},
            {"objectId": "Mug|near", "objectType": "Mug", "distance": 0.5},
        ]
    )
    assert resolver.resolve("mug", metadata) == "Mug|near"


def test_refrigerator_resolves_against_real_ai2thor_fridge_object_type():
    # Confirmed against a real AI2-THOR instance: the objectType is
    # "Fridge", not "Refrigerator" -- the exact mismatch that made the
    # README's canonical demo task fail end to end before this alias
    # was added.
    resolver = ObjectResolver()
    metadata = _metadata(
        [{"objectId": "Fridge|1", "objectType": "Fridge", "distance": 1.0}]
    )
    assert resolver.resolve("refrigerator", metadata) == "Fridge|1"


def test_fridge_alias_resolves_in_reverse_too():
    resolver = ObjectResolver()
    metadata = _metadata(
        [{"objectId": "Refrigerator|1", "objectType": "Refrigerator", "distance": 1.0}]
    )
    assert resolver.resolve("fridge", metadata) == "Refrigerator|1"
