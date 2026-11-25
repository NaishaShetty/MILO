"""Roadmap 2, Phase 7: stage timings, waterfall, run report, scene map."""

from __future__ import annotations

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.synthetic import Faults, SyntheticSimulator
from novel.eval_novel import scene
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from schemas.task import SingleTask
from tracelog.recorder import TraceRecorder
from tracelog.stats import STAGES, report, stage_stats, waterfall
from tracelog.store import TraceStore


def _missions(tmp_path, n=3, fault="none"):
    store = TraceStore(tmp_path / "t.db")
    poses = iter(
        [
            {
                "position": {"x": i * 0.5, "y": 0.9, "z": 1.0 - i * 0.25},
                "rotation": {"y": 90.0},
            }
            for i in range(100)
        ]
    )
    ids = []
    for _ in range(n):
        sim = SyntheticSimulator(scene(), Faults(kind=fault, target="apple", times=1))
        orch = Orchestrator(
            PlannerAgentWrapper(create_planner("rule_based")),
            ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
            trace_recorder=TraceRecorder(store, pose_source=lambda: next(poses)),
        )
        ids.append(
            orch.run(SingleTask(goal="store", object="apple", target="fridge")).task_id
        )
    return store, ids


def test_stage_stats_give_p50_and_p95_per_stage_and_action(tmp_path):
    store, _ = _missions(tmp_path)
    stats = stage_stats(store)
    assert stats["missions"] == 3
    assert set(stats["stages"]) == set(STAGES)
    total = stats["stages"]["total_ms"]
    assert total["n"] == 3 and total["p50"] <= total["p95"]
    assert stats["stages"]["planning_ms"]["n"] == 3
    assert {"navigate", "pickup", "place", "open", "close"} <= set(stats["actions"])


def test_waterfall_orders_plan_steps_and_reflection(tmp_path):
    store, ids = _missions(tmp_path, 1, fault="blocked_path")
    bars = waterfall(store.get(ids[0]))
    kinds = [b["kind"] for b in bars]
    assert kinds[0] == "plan" and "step" in kinds and "reflection" in kinds
    assert all(b["start_ms"] >= 0 and b["ms"] >= 0 for b in bars)
    assert any(b.get("status") == "failed" for b in bars)  # the blocked first try


def test_steps_record_milos_pose_for_the_map(tmp_path):
    store, ids = _missions(tmp_path, 1)
    poses = [
        r["data"]["pose"] for r in store.get(ids[0])["records"] if r["kind"] == "step"
    ]
    assert poses and set(poses[0]) == {"x", "z", "yaw"}


def test_run_report_is_one_readable_page(tmp_path):
    store, ids = _missions(tmp_path, 1)
    md = report(store.get(ids[0]))
    assert md.startswith("# MILO run report")
    assert "**Outcome:** succeeded" in md and "| 1 | locate" in md
    assert (
        "## Checks against the world" in md and "✓ the apple is in/on the fridge" in md
    )


def test_api_stats_waterfall_report_and_scene_map(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api.app import app
    from tests.test_api_phase3 import _wire

    store, ids = _missions(tmp_path, 2)
    monkeypatch.setenv("MILO_TRACE_DB", str(tmp_path / "t.db"))
    client = TestClient(app)
    stats = client.get("/api/v1/traces/stats").json()
    assert stats["missions"] == 2 and stats["stages"]["total_ms"]["n"] == 2
    assert client.get(f"/api/v1/traces/{ids[0]}/waterfall").json()["bars"]
    rep = client.get(f"/api/v1/traces/{ids[0]}/report")
    assert rep.status_code == 200 and rep.headers["content-type"].startswith(
        "text/markdown"
    )
    assert "attachment" in rep.headers["content-disposition"]
    assert client.get("/api/v1/traces/nope/report").status_code == 404

    objs = scene()
    objs[0]["position"] = {"x": 1.0, "y": 0.0, "z": 2.0}
    sim = _wire(SyntheticSimulator(objs, Faults()))
    sim.objects  # noqa: B018 -- the wired simulator
    body = client.get("/api/v1/scene/map").json()
    assert body["has_positions"] is True
    assert {"id", "type", "x", "z", "visible", "in"} <= set(body["objects"][0])
    assert isinstance(body["beliefs"], list) and isinstance(body["path"], list)
