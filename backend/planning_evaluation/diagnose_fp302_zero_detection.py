"""
diagnose_fp302_zero_detection.py

Purpose
-------
One-off diagnostic script (not a regression test) reproducing
`milo-v1.1-fp302-t4a`'s tier4_multi_step failure up through sub-goal
1's failed `place`, then inspecting the actual camera/agent state at
the exact frame that produced zero detections in prior investigations
-- saves the raw RGB frame to disk and dumps agent pose/camera and the
held alarm clock's own live metadata, to find the real cause instead
of guessing.

How to run
-----------
    cd backend
    PYTHONPATH=. python planning_evaluation/diagnose_fp302_zero_detection.py
"""

import uuid

from PIL import Image

from memory_evaluation.experiment_real import _seed_initial_state_from_live_metadata
from orchestration.task_runner import TaskRunner
from planner.rule_based import RuleBasedPlanner
from planning_evaluation.loader import load_tasks
from simulator.simulator import Simulator
from vision.detectors.grounding_dino_detector import GroundingDINODetector


def main():
    tasks = load_tasks(version="1.1")
    bt = next(t for t in tasks if t.task_id == "milo-v1.1-fp302-t4a")
    sub_tasks = bt.to_single_tasks()

    simulator = Simulator(scene=bt.scene)
    simulator.start()

    # Sub-goal 1: alarmclock -> drawer (known to fail at `place`)
    sub1 = sub_tasks[0]
    pre_metadata = simulator.get_metadata()
    initial_state = _seed_initial_state_from_live_metadata(sub1, pre_metadata)
    runner = TaskRunner(RuleBasedPlanner(), simulator)
    runner.run(
        sub1,
        episode_id=str(uuid.uuid4()),
        memory_enabled=False,
        initial_state=initial_state,
    )

    # Now at the exact point the prior investigation captured a scene
    # for sub-goal 2 -- inspect everything about this frame.
    metadata = simulator.get_metadata()
    agent = metadata["agent"]
    print("agent position:", agent["position"])
    print("agent rotation:", agent["rotation"])
    print("agent cameraHorizon:", agent.get("cameraHorizon"))

    alarmclock = next(o for o in metadata["objects"] if o["objectType"] == "AlarmClock")
    print("\nalarmclock live metadata:")
    print("  objectId:", alarmclock["objectId"])
    print("  isPickedUp:", alarmclock.get("isPickedUp"))
    print("  visible:", alarmclock.get("visible"))
    print("  position:", alarmclock.get("position"))
    print("  distance:", alarmclock.get("distance"))

    image = simulator.get_rgb().copy()
    print("\nframe shape:", image.shape)
    print("frame mean brightness:", image.mean())
    print("frame min/max:", image.min(), image.max())

    out_path = "/tmp/fp302_critical_frame.png"
    Image.fromarray(image).save(out_path)
    print(f"\nsaved frame to {out_path}")

    # Try detection at a very low threshold to see if ANYTHING is
    # picked up at all, even far below any usable confidence -- tells
    # us whether this is "detector sees something faint" vs "detector
    # sees nothing resembling an alarm clock at all."
    detector = GroundingDINODetector(box_threshold=0.02, text_threshold=0.02)
    from scene.metadata_keys import SceneMetadata
    from scene.scene import Scene

    scene = Scene()
    scene.metadata[SceneMetadata.DETECTION_PROMPT] = "alarmclock. cd. drawer. shelf."
    scene = detector.process(image, scene)
    print(f"\ndetections at box_threshold=0.02: {len(scene.detections)}")
    for d in scene.detections:
        print(f"  {d.label}: confidence={d.confidence:.4f} bbox={d.bbox}")

    simulator.stop()


if __name__ == "__main__":
    main()
