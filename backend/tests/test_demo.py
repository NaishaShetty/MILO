"""Roadmap 2, Phase 9: the recorded demo missions."""

from __future__ import annotations

import json

from demo.record import DemoSim, record, sketch
from learning.synthetic import Faults
from novel.eval_novel import scene


def test_the_schematic_is_an_image_and_the_sim_has_positions():
    sim = DemoSim(scene(), Faults())
    img = sketch(sim)
    assert img.shape == (200, 320, 3)
    meta = sim.get_metadata()
    assert meta["agent"]["position"]["x"] > 0
    assert all(
        "position" in o for o in meta["objects"] if o["objectType"].lower() == "fridge"
    )


def test_recording_writes_every_mission_and_its_trace(tmp_path):
    missions = record(tmp_path)
    titles = [m["title"] for m in missions]
    assert len(missions) == 6 and "Memory poisoning, defence ON" in titles
    assert all(m["outcome"] == "succeeded" for m in missions)
    index = json.loads((tmp_path / "missions.json").read_text())
    for m in index:
        trace = json.loads((tmp_path / "traces" / f"{m['id']}.json").read_text())
        steps = [r for r in trace["records"] if r["kind"] == "step"]
        assert steps and steps[0]["data"].get("frame") and steps[0]["data"].get("pose")
    reused = next(m for m in index if m["title"] == "The taught skill, reused")
    trace = json.loads((tmp_path / "traces" / f"{reused['id']}.json").read_text())
    plan = next(r for r in trace["records"] if r["kind"] == "plan")["data"]["plan"]
    assert plan["metadata"]["novel"]["source"] == "skill"
