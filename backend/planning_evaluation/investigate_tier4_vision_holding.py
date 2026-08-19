"""
investigate_tier4_vision_holding.py

Purpose
-------
Honest, real re-run of the two `tier4_multi_step` episodes that hit
the `WorldState`-reseeding gap (`docs/roadmap.md`):
`milo-v1.1-fp302-t4a`, `milo-v1.1-fp201-t4a`. Runs each task's two
sub-goals twice against real AI2-THOR: once exactly as
`run_benchmark.py._run_multi_subtask_episode` does today (symbolic
re-seeding only, `_seed_initial_state_from_live_metadata`), and once
with `planner.grounding.ground_world_state()`'s new vision-grounded
`is_open`/`robot_holding` layered on top before each sub-goal plans --
to find out whether the vision-grounded held-object heuristic actually
catches the "hand still full after a failed place" failure mode, or
not.

This is a standalone investigation script (not a change to
`run_benchmark.py` itself) so the comparison is explicit and
reviewable -- see this repo's `docs/roadmap.md` for where the result
gets recorded.

How to run
-----------
    cd backend
    PYTHONPATH=. python planning_evaluation/investigate_tier4_vision_holding.py
"""

import uuid

from memory_evaluation.experiment_real import _seed_initial_state_from_live_metadata
from orchestration.task_runner import TaskRunner
from planner.grounding import ground_world_state
from planner.rule_based import RuleBasedPlanner
from planning_evaluation.live_state import check_goal_live_multi
from planning_evaluation.loader import load_tasks
from simulator.simulator import Simulator
from vision.depth.ground_truth_depth_estimator import GroundTruthDepthEstimator
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.scene_graph.heuristic_scene_graph import HeuristicSceneGraph
from vision.segmenters.sam2_segmenter import SAM2Segmenter
from vision.tracking.iou_tracker import IoUTracker
from vision.vision_agent import VisionAgent

TARGET_TASK_IDS = {"milo-v1.1-fp302-t4a", "milo-v1.1-fp201-t4a"}


def _run_episode(bt, *, use_vision: bool):
    tasks = bt.to_single_tasks()
    simulator = Simulator(scene=bt.scene, render_depth=use_vision)
    simulator.start()

    vision_agent = None
    if use_vision:
        detector = GroundingDINODetector()
        segmenter = SAM2Segmenter()
        depth = GroundTruthDepthEstimator(depth_provider=simulator.get_depth)
        vision_agent = VisionAgent(
            simulator,
            detector=detector,
            segmenter=segmenter,
            depth=depth,
            tracker=IoUTracker(),
            scene_graph=HeuristicSceneGraph(),
        )

    # Every object/target name across ALL sub-goals of this task, not
    # just the current one -- see this run's first attempt (narrowed
    # to only the current sub-goal's own object/target) for why that
    # matters: a held-object heuristic is only as good as what the
    # detection prompt asks the detector to look for, and a prior
    # sub-goal's still-held object is invisible to a prompt that never
    # names it.
    all_names = sorted({n for t in tasks for n in (t.object, t.target) if n})

    sub_reports = []
    try:
        for sub_task in tasks:
            pre_metadata = simulator.get_metadata()
            initial_state = _seed_initial_state_from_live_metadata(
                sub_task, pre_metadata
            )
            symbolic_holding_before_vision = initial_state.robot_holding

            if use_vision:
                assert vision_agent is not None
                prompt = ". ".join(all_names) + "."
                scene = vision_agent.perceive(prompt)
                print(
                    f"    [debug] prompt={prompt!r} "
                    f"detections={[(d.label, round(d.depth, 3) if d.depth is not None else None) for d in scene.detections]}"
                )
                ground_world_state(scene, initial_state)

            runner = TaskRunner(RuleBasedPlanner(), simulator)
            run_result = runner.run(
                sub_task,
                episode_id=str(uuid.uuid4()),
                memory_enabled=False,
                initial_state=initial_state,
            )

            sub_failure = None
            if run_result.execution_record is not None:
                for step in run_result.execution_record.step_results:
                    if step.error is not None:
                        sub_failure = step.error.message
                        break
            if sub_failure is None and not run_result.planning_result.success:
                sub_failure = (
                    "; ".join(run_result.planning_result.errors) or "planning failed"
                )

            sub_reports.append(
                {
                    "object": sub_task.object,
                    "target": sub_task.target,
                    "symbolic_robot_holding_before_vision": (
                        symbolic_holding_before_vision
                    ),
                    "robot_holding_seeded": initial_state.robot_holding,
                    "execution_success": run_result.succeeded,
                    "plan_success": run_result.planning_result.success,
                    "failure": sub_failure,
                }
            )

        post_metadata = simulator.get_metadata()
        multi_result = check_goal_live_multi(tasks, post_metadata)
        return {
            "goal_success": multi_result.all_succeeded,
            "per_subtask": list(multi_result.per_subtask),
            "sub_reports": sub_reports,
        }
    finally:
        simulator.stop()


def main():
    all_tasks = load_tasks(version="1.1")
    targets = [t for t in all_tasks if t.task_id in TARGET_TASK_IDS]
    assert len(targets) == len(
        TARGET_TASK_IDS
    ), f"expected {len(TARGET_TASK_IDS)} tasks, found {len(targets)}"

    for bt in targets:
        print(
            f"\n{'=' * 70}\n{bt.task_id} ({bt.scene}) -- {bt.instruction}\n{'=' * 70}"
        )

        print(
            "\n--- baseline (symbolic re-seeding only, as run_benchmark.py does today) ---"
        )
        baseline = _run_episode(bt, use_vision=False)
        for r in baseline["sub_reports"]:
            print(
                f"  sub-goal {r['object']}->{r['target']}: "
                f"symbolic_holding_before_vision={r['symbolic_robot_holding_before_vision']!r} "
                f"seeded_holding={r['robot_holding_seeded']!r} "
                f"execution_success={r['execution_success']} "
                f"failure={r['failure']!r}"
            )
        print(f"  goal_success={baseline['goal_success']}")

        print("\n--- with vision-grounded is_open/robot_holding layered on top ---")
        vision = _run_episode(bt, use_vision=True)
        for r in vision["sub_reports"]:
            print(
                f"  sub-goal {r['object']}->{r['target']}: "
                f"symbolic_holding_before_vision={r['symbolic_robot_holding_before_vision']!r} "
                f"seeded_holding={r['robot_holding_seeded']!r} "
                f"execution_success={r['execution_success']} "
                f"failure={r['failure']!r}"
            )
        print(f"  goal_success={vision['goal_success']}")

        print(
            f"\n  VERDICT for {bt.task_id}: "
            f"baseline goal_success={baseline['goal_success']} -> "
            f"vision-grounded goal_success={vision['goal_success']}"
        )


if __name__ == "__main__":
    main()
