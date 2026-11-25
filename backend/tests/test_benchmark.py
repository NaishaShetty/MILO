"""Roadmap 2, Phase 6: fixed benchmark, ablations, fault recovery, CI gate, leaderboard API."""

from __future__ import annotations

import json

from benchmark.ci import check
from benchmark.run import NoReflection, markdown, run, run_case, summarise
from benchmark.suite import (
    FAULT_KINDS,
    ci_subset,
    fault_cases,
    full_suite,
    known_cases,
    novel_cases,
)


def test_the_suite_is_fixed_and_covers_known_novel_and_every_fault():
    assert len(known_cases()) == 23 and len(novel_cases()) == 8
    assert [c.case_id for c in full_suite()] == [c.case_id for c in full_suite()]
    assert {c.fault for c in fault_cases()} == set(FAULT_KINDS)
    sub = ci_subset()
    assert {c.fault for c in sub if c.fault != "none"} == set(FAULT_KINDS)
    assert len(sub) < len(full_suite()) + len(fault_cases())


def test_runs_are_reproducible():
    case = next(c for c in fault_cases() if c.fault == "blocked_path")
    a, b = run_case(case, "rule_based"), run_case(case, "rule_based")
    assert a == b and a["success"] is True and a["replans"] + a["steps"] > 0


def test_classical_planners_fail_novel_commands_and_the_novel_planner_solves_them():
    case = novel_cases()[0]
    assert run_case(case, "rule_based")["success"] is False
    assert run_case(case, "novel")["success"] is True


def test_without_reflection_a_recoverable_fault_ends_the_mission():
    case = next(c for c in fault_cases() if c.fault == "blocked_path")
    assert run_case(case, "rule_based")["success"] is True
    assert run_case(case, "rule_based", reflection=False)["success"] is False
    assert NoReflection.__mro__[1].__name__ == "ReflectionAgent"


def test_summary_and_report_shape():
    rep = run("ci", ["rule_based", "novel"], "reference", ablations=False)
    rb = rep["planners"]["rule_based"]
    assert 0 < rb["known"]["success"] <= 1 and rb["novel"]["success"] == 0
    assert set(rb["recovery_by_fault"]) == set(FAULT_KINDS)
    nov = rep["planners"]["novel"]
    assert nov["known"]["success"] is None and nov["novel"]["success"] == 1.0
    md = markdown(rep)
    assert "| novel | not run | 100% |" in md and "Recovery by fault kind" in md
    assert summarise([])["success"] is None


def test_ci_gate_fails_on_a_drop_beyond_the_margin():
    base = {"rule_based": 0.70, "novel": 1.0}
    assert check(base, {"rule_based": 0.68, "novel": 1.0}, 0.05) == []
    problems = check(base, {"rule_based": 0.60, "novel": 1.0}, 0.05)
    assert problems and "rule_based" in problems[0]
    assert check(base, {"rule_based": 0.7}, 0.05) == ["novel: missing from this run"]


def test_leaderboard_api_reads_latest_and_history(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import api.routes.benchmark as route
    from api.app import app

    (tmp_path / "latest.json").write_text(
        json.dumps({"subset": "full", "planners": {}, "by_case": {"x": []}})
    )
    (tmp_path / "history.jsonl").write_text(
        '{"date": "d", "subset": "full", "planners": {}}\nnot json\n'
    )
    monkeypatch.setattr(route, "DIR", tmp_path)
    body = TestClient(app).get("/api/v1/benchmark").json()
    assert body["latest"] == {"subset": "full", "planners": {}}
    assert body["history"] == [{"date": "d", "subset": "full", "planners": {}}]
