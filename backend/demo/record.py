"""
record.py (backend/demo)

Records the demo missions the hosted UI replays with no simulator or GPU:

1. a new task MILO works out ("chill the apple"), with the plan's checks;
2. a skill taught in words, run back once, then reused on another object in another room;
3. memory poisoning: the same "put the apple away" with the defence off (the poisoned
   memory wins) and on (it is quarantined; the apple goes where the user said);
4. recovering from a blocked path (reflection + replanning).

The synthetic simulator has no camera, so each step gets a small **schematic sketch**
of the room (drawn from the simulator's object state, labelled as a sketch) and a pose
on a fixed floor plan for the scene map.

    cd backend && python -m demo.record --out ../frontend/public/demo
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from agents.execution_agent import ExecutionAgentWrapper
from agents.memory_agent import MemoryAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.synthetic import Faults, SyntheticSimulator
from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from novel.eval_novel import commands, scene
from novel.planner import NovelPlanner
from novel.providers import ScriptedProvider
from novel.safety import Constraints
from novel.skills import SkillLibrary
from novel.teach import proposal_from_words
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from schemas.task import SingleTask
from tracelog.recorder import TraceRecorder
from tracelog.store import TraceStore

REPO = Path(__file__).resolve().parents[2]
#: A fixed floor plan (metres) for the demo's schematic and scene map.
LAYOUT = {
    "fridge": (0.5, 3.5), "countertop": (1.8, 3.6), "cabinet": (3.1, 3.6), "drawer": (4.2, 3.5),
    "table": (2.0, 1.8), "shelf": (4.6, 1.6), "sofa": (1.0, 0.4), "television": (3.4, 0.3),
    "lightswitch": (5.0, 3.0), "faucet": (1.8, 3.9),
}  # fmt: skip


class DemoSim(SyntheticSimulator):
    """The synthetic simulator plus a fixed floor plan: object positions and MILO's
    pose (it stands at the last thing it walked to)."""

    def __init__(self, objects, faults):
        super().__init__(objects, faults)
        self.at = (2.5, 2.4)

    def _place(self, name: str):
        return LAYOUT.get(name.lower())

    def navigate_to(self, object_id: str):
        event = super().navigate_to(object_id)
        if event.metadata.get("lastActionSuccess"):
            obj = self._obj(object_id)
            name = (obj or {}).get("objectType", "").lower()
            home = self._place(name) or self._parent_place(obj)
            if home:
                self.at = (home[0], home[1] - 0.4)
        return event

    def _parent_place(self, obj):
        parents = (obj or {}).get("parentReceptacles") or []
        return self._place(str(parents[0]).split("|")[0]) if parents else None

    def get_metadata(self):
        meta = super().get_metadata()
        for o in meta["objects"]:
            spot = self._place(o["objectType"]) or self._parent_place(o)
            if spot:
                o["position"] = {"x": spot[0], "y": 0.9, "z": spot[1]}
        meta["agent"] = {
            "position": {"x": self.at[0], "y": 0.9, "z": self.at[1]},
            "rotation": {"y": 0.0},
        }
        return meta


def sketch(sim: DemoSim) -> np.ndarray:
    """A 320x200 schematic of the room in MILO's colours (not a camera image)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 200), (255, 246, 229))
    d = ImageDraw.Draw(img)
    sx = lambda x: int(20 + x / 5.4 * 280)  # noqa: E731
    sz = lambda z: int(180 - z / 4.2 * 160)  # noqa: E731
    meta = SyntheticSimulator.get_metadata(sim)
    for name, (x, z) in LAYOUT.items():
        obj = next(
            (o for o in meta["objects"] if o["objectType"].lower() == name), None
        )
        if obj is None:
            continue
        fill = (255, 224, 184) if not obj.get("isOpen") else (255, 210, 90)
        if obj.get("isToggled"):
            fill = (255, 210, 90)
        d.rounded_rectangle(
            [sx(x) - 22, sz(z) - 12, sx(x) + 22, sz(z) + 12],
            radius=6,
            fill=fill,
            outline=(42, 24, 16),
            width=2,
        )
        d.text((sx(x) - 20, sz(z) - 6), name[:9], fill=(42, 24, 16))
    held = {h["objectType"].lower() for h in meta["inventoryObjects"]}
    for i, o in enumerate(o for o in meta["objects"] if o.get("pickupable")):
        parents = o.get("parentReceptacles") or []
        if o["objectType"].lower() in held or not parents:
            continue
        spot = LAYOUT.get(str(parents[0]).split("|")[0].lower())
        if spot:
            cx, cz = sx(spot[0]) - 16 + (i % 5) * 8, sz(spot[1]) + 16
            d.ellipse(
                [cx - 4, cz - 4, cx + 4, cz + 4],
                fill=(255, 138, 43),
                outline=(42, 24, 16),
            )
    rx, rz = sx(sim.at[0]), sz(sim.at[1])
    d.ellipse([rx - 9, rz - 9, rx + 9, rz + 9], fill=(42, 24, 16))
    d.rectangle([rx - 5, rz - 3, rx + 5, rz + 1], fill=(255, 179, 71))
    if held:
        d.text(
            (rx + 12, rz - 6), "holding " + ", ".join(sorted(held)), fill=(179, 74, 0)
        )
    d.text((6, 4), "schematic view (no camera)", fill=(107, 90, 78))
    return np.asarray(img)


def _memory(tmp: str) -> MemoryAgent:
    return MemoryAgent.from_config(
        MemoryConfig(
            enabled=True,
            database_path=Path(tmp) / "m.db",
            vector_store_path=Path(tmp) / "v",
        )
    )


def _run(
    store: TraceStore,
    planner: Any,
    task: SingleTask,
    *,
    objects=None,
    faults=None,
    memory=None,
) -> str:
    sim = DemoSim(objects or scene(), faults or Faults())
    execution = ExecutionAgentWrapper(sim)  # type: ignore[arg-type]
    if isinstance(planner, NovelPlanner):
        planner._metadata = execution.get_metadata
    orch = Orchestrator(
        PlannerAgentWrapper(planner),
        execution,
        memory_agent=MemoryAgentWrapper(memory) if memory else None,
        trace_recorder=TraceRecorder(store, frame_source=lambda: sketch(sim),
                                     pose_source=lambda: sim.get_metadata()["agent"]),  # fmt: skip
    )
    return orch.run(task).task_id


def record(out: Path) -> List[Dict[str, Any]]:
    saved = {k: os.environ.get(k) for k in ("MILO_GOAL_CHECK", "MILO_MEMORY_DEFENCE")}
    try:
        return _record(out)
    finally:  # never leave the recording's settings behind (tests run in one process)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _record(out: Path) -> List[Dict[str, Any]]:
    os.environ["MILO_GOAL_CHECK"] = "enforce"
    reference = ScriptedProvider({i["command"]: i["answer"] for i in commands()})
    missions: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(Path(tmp) / "t.db")

        def novel(skills: SkillLibrary) -> NovelPlanner:
            return NovelPlanner(
                reference, lambda: None, constraints=Constraints.load(), skills=skills
            )

        skills = SkillLibrary(Path(tmp) / "s.db")
        mid = _run(
            store,
            novel(skills),
            SingleTask(goal="novel", estimated_goal="chill the apple"),
        )
        missions.append({"id": mid, "title": "Working out a new task",
                         "about": "\"Chill the apple\" isn't something MILO was programmed to do. It works out a plan, "
                                  "checks it, does it, and verifies the apple really is in the closed fridge."})  # fmt: skip

        taught = SkillLibrary(Path(tmp) / "taught.db")
        proposal = proposal_from_words(
            ["pick up the mug", "put it on the table"],
            DemoSim(scene(), Faults()).get_metadata(),
        )
        taught.save("set something on the table", "set the mug on the table", proposal,
                    [o["objectType"].lower() for o in scene()], status="teaching")  # fmt: skip
        mid = _run(
            store,
            novel(taught),
            SingleTask(goal="novel", estimated_goal="set the mug on the table"),
        )
        missions.append({"id": mid, "title": "A skill taught in words: the run-back",
                         "about": "Taught as two sentences (\"pick up the mug\", \"put it on the table\"), MILO runs it once to show what it understood."})  # fmt: skip
        room2 = [o for o in scene() if o["objectType"] != "Apple"]
        room2.append({"objectId": "Vase|1", "objectType": "Vase", "distance": 3.1, "visible": True,
                      "pickupable": True, "parentReceptacles": ["Shelf|1"]})  # fmt: skip
        mid = _run(
            store,
            novel(taught),
            SingleTask(goal="novel", estimated_goal="set the vase on the table"),
            objects=room2,
        )
        missions.append({"id": mid, "title": "The taught skill, reused",
                         "about": "Same wording, a new object (a vase) in a different room: MILO reuses the skill with no language model at all."})  # fmt: skip

        for defence in ("0", "1"):
            os.environ["MILO_MEMORY_DEFENCE"] = defence
            with tempfile.TemporaryDirectory() as mtmp:
                mem = _memory(mtmp)
                mem.remember_preference("apple", "stored_in", "fridge")
                mem.import_memory("apple", "located_on", "sofa")
                from memory.habits import usual_place_of

                place, rel = usual_place_of(mem.list_memories(), "apple") or (
                    "fridge",
                    "stored_in",
                )
                goal = "store" if rel == "stored_in" else "place"
                mid = _run(
                    store,
                    create_planner("rule_based"),
                    SingleTask(goal=goal, object="apple", target=place),
                    memory=mem,
                )
            missions.append({
                "id": mid,
                "title": "Memory poisoning, defence " + ("ON" if defence == "1" else "OFF"),
                "about": ("An imported memory claims the apple goes on the sofa; the user said the fridge. "
                          + ("With the defence on it is quarantined and the apple goes in the fridge."
                             if defence == "1" else "With the defence off the poisoned memory wins: the apple ends up on the sofa.")),
            })  # fmt: skip
        os.environ.pop("MILO_MEMORY_DEFENCE", None)

        mid = _run(store, create_planner("rule_based"), SingleTask(goal="store", object="egg", target="fridge"),
                   faults=Faults(kind="blocked_path", target="fridge", times=1))  # fmt: skip
        missions.append({"id": mid, "title": "Getting back on track",
                         "about": "The way to the fridge is blocked once. MILO reflects, replans, and finishes the job."})  # fmt: skip

        traces = out / "traces"
        if traces.exists():
            shutil.rmtree(traces)
        traces.mkdir(parents=True)
        for m in missions:
            trace = store.get(m["id"])
            assert trace is not None
            m["outcome"] = trace["mission"]["outcome"]
            m["task_text"] = trace["mission"]["task_text"]
            (traces / f"{m['id']}.json").write_text(json.dumps(trace))
    (out / "missions.json").write_text(json.dumps(missions, indent=2))
    latest = REPO / "benchmarks" / "latest.json"
    if latest.exists():
        data = json.loads(latest.read_text())
        data.pop("by_case", None)  # the per-case rows aren't shown and are large
        (out / "benchmark.json").write_text(json.dumps(data))
    history = REPO / "benchmarks" / "history.jsonl"
    if history.exists():
        shutil.copy(history, out / "history.jsonl")
    return missions


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=REPO / "frontend" / "public" / "demo")
    a = ap.parse_args(argv)
    missions = record(a.out)
    for m in missions:
        print(f"{m['outcome']:>10}  {m['title']}  ({m['id'][:8]})")


if __name__ == "__main__":
    main()
