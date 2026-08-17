"""
run_floorplan_sweep.py (backend/memory_evaluation)

Purpose
-------
Phase D: everything else in this project (`real_scenarios.py`,
`experiment_real.py`, the Phase B ablation) has only ever run against
`FloorPlan1` -- README.md's "Limited scene/task diversity" limitation
and `docs/roadmap.md`'s "Broader scene/task diversity" future-work row.
This script runs the same `TaskRunner(RuleBasedPlanner(), Simulator())`
pipeline used elsewhere against 5 real AI2-THOR scenes spanning all
four iTHOR room types (kitchen x2, living room, bedroom, bathroom),
single condition (no memory on/off comparison -- this is a
success/failure generalization check, not an ablation), and logs a
per-episode success/failure table plus the concrete failure reason for
anything that doesn't succeed.

Why the task set is authored per scene, not shared
------------------------------------------------------
`real_scenarios.py`'s task set uses FloorPlan1's confirmed kitchen
objectTypes (mug, apple, fridge, ...) -- none of these exist in a
living room/bedroom/bathroom scene. Every task below was chosen from a
live `get_metadata()` scan of its target scene (same discipline
`real_scenarios.py`'s own docstring describes for FloorPlan1), not
guessed from AI2-THOR documentation, so every task is known to resolve
against a real object before the sweep ever runs -- a task failing is
therefore a real pipeline finding, not an authoring mistake.

Why 3 tasks per scene (find / pick_up / store)
------------------------------------------------
Mirrors the three goal handlers `rule_based.py`'s `GOAL_HANDLERS`
exercises most differently (`_goal_perceive`, `_goal_pick_up`,
`_goal_store`) -- `find` alone would only prove object resolution
works; `pick_up` adds `_acquire`'s navigate/pickup pair; `store` adds
`_deposit`'s open/place/close container logic (`_goal_store` at
`rule_based.py:302-314`), the exact code path the Phase 8.7 audit's
closed-receptacle bug lived in. Three tasks per scene is enough to
exercise all three without turning this into a full benchmark.

Output
------
Writes `experiments/results/floorplan_sweep_<timestamp>.json` (full
detail per episode: goal/object/target, success, plan, failure cause)
and a matching `_episodes.csv`, same convention as
`run_ablation_real.py`. Prints a one-line-per-episode summary to
stdout as it runs.

How to run
-----------
Opt-in gated (launches a real Unity subprocess per episode -- 15 total
here, one scene restart per episode, same "fresh simulator per
episode" policy `real_scenarios.py` uses):

    cd backend
    RUN_SIMULATOR_TESTS=true python -m memory_evaluation.run_floorplan_sweep
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_evaluation.experiment_real import _seed_initial_state_from_live_metadata
from orchestration.task_runner import TaskRunner
from planner.rule_based import RuleBasedPlanner
from schemas.task import SingleTask
from simulator.simulator import Simulator

RESULTS_DIR = Path(__file__).resolve().parents[2] / "experiments" / "results"


@dataclass(frozen=True)
class SceneTask:
    label: str
    task: SingleTask


@dataclass(frozen=True)
class SceneSpec:
    scene: str
    room_type: str
    tasks: List[SceneTask] = field(default_factory=list)


#: Chosen from a live `get_metadata()` scan of each scene (see module
#: docstring) -- every object/target name below is a confirmed real
#: `objectType` in that scene, lowercased to match
#: `execution.resolver.ObjectResolver`'s case-insensitive matching.
SCENES: List[SceneSpec] = [
    SceneSpec(
        scene="FloorPlan1",
        room_type="kitchen",
        tasks=[
            SceneTask("find_mug", SingleTask(goal="find", object="mug", task_id="fp1-find")),
            SceneTask("pick_up_apple", SingleTask(goal="pick_up", object="apple", task_id="fp1-pickup")),
            SceneTask(
                "store_bread_in_fridge",
                SingleTask(goal="store", object="bread", target="fridge", task_id="fp1-store"),
            ),
        ],
    ),
    SceneSpec(
        scene="FloorPlan5",
        room_type="kitchen",
        tasks=[
            SceneTask("find_bowl", SingleTask(goal="find", object="bowl", task_id="fp5-find")),
            SceneTask("pick_up_potato", SingleTask(goal="pick_up", object="potato", task_id="fp5-pickup")),
            SceneTask(
                "store_mug_in_cabinet",
                SingleTask(goal="store", object="mug", target="cabinet", task_id="fp5-store"),
            ),
        ],
    ),
    SceneSpec(
        scene="FloorPlan201",
        room_type="living_room",
        tasks=[
            SceneTask("find_laptop", SingleTask(goal="find", object="laptop", task_id="fp201-find")),
            SceneTask("pick_up_newspaper", SingleTask(goal="pick_up", object="newspaper", task_id="fp201-pickup")),
            SceneTask(
                "store_remotecontrol_in_drawer",
                SingleTask(goal="store", object="remotecontrol", target="drawer", task_id="fp201-store"),
            ),
        ],
    ),
    SceneSpec(
        scene="FloorPlan301",
        room_type="bedroom",
        tasks=[
            SceneTask("find_alarmclock", SingleTask(goal="find", object="alarmclock", task_id="fp301-find")),
            SceneTask("pick_up_pillow", SingleTask(goal="pick_up", object="pillow", task_id="fp301-pickup")),
            SceneTask(
                "store_book_in_drawer",
                SingleTask(goal="store", object="book", target="drawer", task_id="fp301-store"),
            ),
        ],
    ),
    SceneSpec(
        scene="FloorPlan401",
        room_type="bathroom",
        tasks=[
            SceneTask("find_soapbar", SingleTask(goal="find", object="soapbar", task_id="fp401-find")),
            SceneTask("pick_up_towel", SingleTask(goal="pick_up", object="towel", task_id="fp401-pickup")),
            SceneTask(
                "store_spraybottle_on_shelf",
                SingleTask(goal="store", object="spraybottle", target="shelf", task_id="fp401-store"),
            ),
        ],
    ),
]


@dataclass
class SweepEpisodeResult:
    scene: str
    room_type: str
    label: str
    goal: Optional[str]
    object: Optional[str]
    target: Optional[str]
    success: bool
    plan_success: bool
    action_count: int
    plan_step_count: int
    plan_targets: List[Optional[str]]
    failure_cause: Optional[str]
    wall_clock_ms: float


def run_scene(spec: SceneSpec) -> List[SweepEpisodeResult]:
    results: List[SweepEpisodeResult] = []
    for scene_task in spec.tasks:
        task = scene_task.task
        simulator = Simulator(scene=spec.scene)
        simulator.start()
        try:
            metadata = simulator.get_metadata()
            initial_state = _seed_initial_state_from_live_metadata(task, metadata)
            runner = TaskRunner(RuleBasedPlanner(), simulator)
            started = time.perf_counter()
            run_result = runner.run(
                task,
                episode_id=str(uuid.uuid4()),
                memory_enabled=False,
                initial_state=initial_state,
            )
            wall_clock_ms = (time.perf_counter() - started) * 1000.0

            plan = run_result.planning_result.plan
            plan_targets = [s.target for s in plan.steps] if plan is not None else []
            action_count = (
                len(run_result.execution_record.step_results)
                if run_result.execution_record is not None
                else 0
            )
            failure_cause = (
                run_result.failure_memory.metadata.get("cause")
                if run_result.failure_memory is not None
                else None
            )

            result = SweepEpisodeResult(
                scene=spec.scene,
                room_type=spec.room_type,
                label=scene_task.label,
                goal=task.goal,
                object=task.object,
                target=task.target or task.target_location,
                success=run_result.succeeded,
                plan_success=run_result.planning_result.success,
                action_count=action_count,
                plan_step_count=len(plan_targets),
                plan_targets=plan_targets,
                failure_cause=failure_cause,
                wall_clock_ms=wall_clock_ms,
            )
            results.append(result)
            print(
                f"[{spec.scene:>12}] {scene_task.label:<28} "
                f"{'OK' if result.success else 'FAIL':<4} "
                f"({wall_clock_ms:.0f}ms)"
                + (f"  cause={failure_cause}" if failure_cause else "")
            )
        except Exception as exc:  # noqa: BLE001 -- record, don't abort the sweep
            wall_clock_ms = 0.0
            result = SweepEpisodeResult(
                scene=spec.scene,
                room_type=spec.room_type,
                label=scene_task.label,
                goal=task.goal,
                object=task.object,
                target=task.target or task.target_location,
                success=False,
                plan_success=False,
                action_count=0,
                plan_step_count=0,
                plan_targets=[],
                failure_cause=f"harness_exception: {exc!r}",
                wall_clock_ms=wall_clock_ms,
            )
            results.append(result)
            print(f"[{spec.scene:>12}] {scene_task.label:<28} EXC   {exc!r}")
        finally:
            simulator.stop()
    return results


def main() -> None:
    if os.environ.get("RUN_SIMULATOR_TESTS", "").lower() != "true":
        print(
            "Skipped: set RUN_SIMULATOR_TESTS=true to run this sweep "
            "(it launches a real AI2-THOR/Unity subprocess per episode)."
        )
        sys.exit(0)

    all_results: List[SweepEpisodeResult] = []
    for spec in SCENES:
        all_results.extend(run_scene(spec))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"floorplan_sweep_{timestamp}.json"
    csv_path = RESULTS_DIR / f"floorplan_sweep_{timestamp}_episodes.csv"

    episodes = [asdict(r) for r in all_results]
    scenes_summary: Dict[str, Dict[str, Any]] = {}
    for spec in SCENES:
        scene_results = [r for r in all_results if r.scene == spec.scene]
        scenes_summary[spec.scene] = {
            "room_type": spec.room_type,
            "total": len(scene_results),
            "succeeded": sum(1 for r in scene_results if r.success),
        }

    report = {
        "reproducibility": {
            "generated_at_utc": timestamp,
            "simulator": "Simulator (real AI2-THOR/Unity, restarted between episodes)",
            "planner": "RuleBasedPlanner",
            "memory_enabled": False,
            "scenes": [s.scene for s in SCENES],
        },
        "scenes_summary": scenes_summary,
        "episodes": episodes,
        "totals": {
            "total_episodes": len(all_results),
            "succeeded": sum(1 for r in all_results if r.success),
            "failed": sum(1 for r in all_results if not r.success),
        },
    }

    json_path.write_text(json.dumps(report, indent=2, default=str))
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(episodes[0].keys()))
        writer.writeheader()
        writer.writerows(episodes)

    print()
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(
        f"Totals: {report['totals']['succeeded']}/{report['totals']['total_episodes']} succeeded"
    )


if __name__ == "__main__":
    main()
