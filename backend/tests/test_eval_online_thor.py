"""The paired real-mission comparison's summary (no simulator needed)."""

from __future__ import annotations

from learning.eval_online_thor import jobs, summarise


def _side(ok, aborted=False, off=None, used=0):
    return {"success": ok, "wasted_steps": 0 if ok else 3, "replans": 0, "retries": 1,
            "steps": 4, "aborted_by_model": aborted, "predictor_switched_off": off,
            "learned_decisions_used": used}  # fmt: skip


def test_pairs_are_counted_by_which_side_succeeded():
    pairs = [
        {"rule": _side(True), "learned": _side(True)},
        {"rule": _side(False), "learned": _side(True, used=1)},
        {"rule": _side(False), "learned": _side(False, aborted=True, used=1)},
        {"rule": _side(True), "learned": _side(False, off="too slow")},
    ]
    s = summarise(pairs)
    assert s["pairs"] == 4
    assert s["rule_based"]["mission_success"] == 0.5
    assert s["learned"]["mission_success"] == 0.5
    assert (s["pairs_only_learned_succeeded"], s["pairs_only_rule_succeeded"]) == (1, 1)
    assert s["aborted_by_learned"] == 1 and s["aborted_would_have_failed_anyway"] == 1.0
    assert s["learned_runs_where_predictor_switched_off"] == 1
    assert s["learned_runs_where_it_made_a_decision"] == 2


def test_only_held_out_scenes_are_used():
    from learning.collect_thor import HELD_OUT_SCENES

    assert {scene for scene, _ in jobs(60)} == set(HELD_OUT_SCENES)
