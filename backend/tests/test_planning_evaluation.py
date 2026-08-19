"""
test_planning_evaluation.py

Purpose
-------
Unit tests for `planning_evaluation.loader`/`live_state` -- the
parts of the Phase E `milo_benchmark` harness that need no live
AI2-THOR simulator (`run_benchmark.py`/`run_memory_ablation.py`
themselves are opt-in gated behind `RUN_SIMULATOR_TESTS=true`, same as
every other real-AI2-THOR harness in this project, and are not
exercised here).

How to run
-----------
    cd backend
    python -m pytest tests/test_planning_evaluation.py -v
"""

from __future__ import annotations

from planning_evaluation.live_state import (
    TIER1_LOCATE_GOALS,
    GroundedTier1Result,
    check_goal_live,
    check_goal_live_grounded,
    check_goal_live_multi,
)
from planning_evaluation.loader import load_tasks
from scene.detection import Detection
from scene.scene import Scene
from schemas.task import SingleTask


def test_dataset_loads_25_tasks_across_5_scenes():
    tasks = load_tasks()
    assert len(tasks) == 25
    assert {t.scene for t in tasks} == {
        "FloorPlan1",
        "FloorPlan5",
        "FloorPlan201",
        "FloorPlan301",
        "FloorPlan401",
    }
    assert {t.difficulty_tier for t in tasks} == {
        "tier1_locate",
        "tier2_pickup",
        "tier3_store",
    }


def test_every_task_id_is_unique():
    tasks = load_tasks()
    ids = [t.task_id for t in tasks]
    assert len(ids) == len(set(ids))


def test_to_single_task_round_trips_fields():
    tasks = load_tasks()
    bt = next(t for t in tasks if t.task_id == "milo-v1-fp1-t3a")
    single = bt.to_single_task()
    assert single.goal == "store"
    assert single.object == "bread"
    assert single.target == "fridge"
    assert single.task_id == "milo-v1-fp1-t3a"


def _obj(object_id, object_type, **kwargs):
    return {"objectId": object_id, "objectType": object_type, **kwargs}


def test_check_goal_live_pickup_true_when_held():
    task = SingleTask(goal="pick_up", object="apple")
    metadata = {"objects": [_obj("Apple|1", "Apple", isPickedUp=True)]}
    assert check_goal_live(task, metadata) is True


def test_check_goal_live_pickup_false_when_not_held():
    task = SingleTask(goal="pick_up", object="apple")
    metadata = {"objects": [_obj("Apple|1", "Apple", isPickedUp=False)]}
    assert check_goal_live(task, metadata) is False


def test_check_goal_live_store_true_when_contained_and_not_held():
    task = SingleTask(goal="store", object="mug", target="cabinet")
    metadata = {
        "objects": [
            _obj("Mug|1", "Mug", isPickedUp=False, parentReceptacles=["Cabinet|1"]),
            _obj("Cabinet|1", "Cabinet"),
        ]
    }
    assert check_goal_live(task, metadata) is True


def test_check_goal_live_store_false_when_still_held():
    task = SingleTask(goal="store", object="mug", target="cabinet")
    metadata = {
        "objects": [
            _obj("Mug|1", "Mug", isPickedUp=True, parentReceptacles=["Cabinet|1"]),
            _obj("Cabinet|1", "Cabinet"),
        ]
    }
    assert check_goal_live(task, metadata) is False


def test_check_goal_live_open_and_close():
    open_task = SingleTask(goal="open", object="fridge")
    close_task = SingleTask(goal="close", object="fridge")
    open_metadata = {"objects": [_obj("Fridge|1", "Fridge", isOpen=True)]}
    closed_metadata = {"objects": [_obj("Fridge|1", "Fridge", isOpen=False)]}

    assert check_goal_live(open_task, open_metadata) is True
    assert check_goal_live(open_task, closed_metadata) is False
    assert check_goal_live(close_task, closed_metadata) is True
    assert check_goal_live(close_task, open_metadata) is False


def test_check_goal_live_locate_existence_only():
    task = SingleTask(goal="find", object="mug")
    assert check_goal_live(task, {"objects": [_obj("Mug|1", "Mug")]}) is True
    assert check_goal_live(task, {"objects": []}) is False


def test_check_goal_live_unregistered_goal_is_unverifiable():
    task = SingleTask(goal="turn_on", object="lamp")
    assert check_goal_live(task, {"objects": [_obj("Lamp|1", "Lamp")]}) is None


# ---------------------------------------------------------------------
# check_goal_live_grounded() -- perception-grounded tier1_locate dual
# check (see live_state.py's docstring addendum). No real simulator/GPU
# needed here: `vision_agent` is a small fake exposing the same
# `.perceive(prompt) -> Scene` shape `VisionAgentWrapper` has, same
# lightweight-synthetic-`Scene` pattern `test_planner_grounding.py`
# already uses.
# ---------------------------------------------------------------------


class _FakeVisionAgent:
    """Fake `VisionAgentWrapper`: `.perceive()` returns a pre-built `Scene`."""

    def __init__(self, scene: Scene) -> None:
        self._scene = scene

    def perceive(self, prompt: str) -> Scene:
        return self._scene


def test_grounded_check_is_noop_for_non_tier1_goal():
    task = SingleTask(goal="pick_up", object="mug")
    result = check_goal_live_grounded(
        task, {"objects": []}, vision_agent=_FakeVisionAgent(Scene(detections=[]))
    )
    assert result == GroundedTier1Result(exists_in_scene=None, perceived_by_agent=None)


def test_grounded_check_exists_true_perceived_false_when_object_in_metadata_but_not_detected():
    """
    The exact divergence this whole check exists to catch: the object
    is real (in AI2-THOR's live metadata) but the vision stack's `Scene`
    has no detection for it -- `exists_in_scene=True`,
    `perceived_by_agent=False`, kept as two separate booleans, never
    merged.
    """
    task = SingleTask(goal="find", object="mug")
    metadata = {"objects": [_obj("Mug|1", "Mug")]}
    empty_scene = Scene(detections=[])

    result = check_goal_live_grounded(
        task, metadata, vision_agent=_FakeVisionAgent(empty_scene)
    )

    assert result.exists_in_scene is True
    assert result.perceived_by_agent is False


def test_grounded_check_both_signals_agree_when_object_detected():
    task = SingleTask(goal="find", object="mug")
    metadata = {"objects": [_obj("Mug|1", "Mug")]}
    scene = Scene(
        detections=[Detection(label="mug", confidence=0.9, bbox=[0, 0, 1, 1])]
    )

    result = check_goal_live_grounded(
        task, metadata, vision_agent=_FakeVisionAgent(scene)
    )

    assert result.exists_in_scene is True
    assert result.perceived_by_agent is True


def test_grounded_check_exists_false_and_perceived_false_when_object_absent_everywhere():
    task = SingleTask(goal="find", object="mug")
    result = check_goal_live_grounded(
        task, {"objects": []}, vision_agent=_FakeVisionAgent(Scene(detections=[]))
    )
    assert result.exists_in_scene is False
    assert result.perceived_by_agent is False


def test_grounded_check_perceived_by_agent_is_none_when_no_vision_agent_supplied():
    """
    No vision stack available for this episode (e.g. construction
    failed) -- `perceived_by_agent` stays `None` ("unmeasured"), never
    silently coerced to `False` ("measured, not found"); `exists_in_scene`
    is still computed since it needs no vision at all.
    """
    task = SingleTask(goal="find", object="mug")
    metadata = {"objects": [_obj("Mug|1", "Mug")]}

    result = check_goal_live_grounded(task, metadata, vision_agent=None)

    assert result.exists_in_scene is True
    assert result.perceived_by_agent is None


def test_grounded_check_records_perception_error_without_crashing():
    class _BrokenVisionAgent:
        def perceive(self, prompt: str) -> Scene:
            raise RuntimeError("camera unavailable")

    task = SingleTask(goal="find", object="mug")
    metadata = {"objects": [_obj("Mug|1", "Mug")]}

    result = check_goal_live_grounded(task, metadata, vision_agent=_BrokenVisionAgent())

    assert result.exists_in_scene is True
    assert result.perceived_by_agent is None
    assert result.perception_error is not None
    assert "camera unavailable" in result.perception_error


def test_tier1_locate_goals_matches_check_goal_live_vocabulary():
    # Regression guard: `check_goal_live_grounded()` reuses the exact
    # same goal-group constant `check_goal_live()`'s tier1 branch does
    # (see live_state.py) -- this must never drift.
    assert set(TIER1_LOCATE_GOALS) == {
        "find",
        "search_for",
        "locate",
        "inspect",
        "count",
    }


# ---------------------------------------------------------------------
# v1.1: scale-up (more scenes) + tier4_multi_step (two independent
# sub-goals, see loader.py's/live_state.py's docstrings).
# ---------------------------------------------------------------------


def test_v1_1_dataset_extends_v1_0_with_more_scenes_and_a_tier4_tier():
    tasks = load_tasks(version="1.1")
    assert len(tasks) == 54
    assert {t.scene for t in tasks} == {
        "FloorPlan1",
        "FloorPlan5",
        "FloorPlan201",
        "FloorPlan301",
        "FloorPlan401",
        "FloorPlan202",
        "FloorPlan302",
        "FloorPlan402",
        "FloorPlan203",
    }
    assert {t.difficulty_tier for t in tasks} == {
        "tier1_locate",
        "tier2_pickup",
        "tier3_store",
        "tier4_multi_step",
    }
    ids = [t.task_id for t in tasks]
    assert len(ids) == len(set(ids))


def test_v1_1_tier4_tasks_have_two_subtasks_each():
    tasks = load_tasks(version="1.1")
    tier4 = [t for t in tasks if t.difficulty_tier == "tier4_multi_step"]
    assert len(tier4) == 9
    for bt in tier4:
        assert bt.subtasks is not None
        assert len(bt.subtasks) == 2
        # Distinct objects -- "two independent sub-goals", not the same
        # object touched twice.
        assert bt.subtasks[0].object != bt.subtasks[1].object


def test_v1_1_frozen_v1_0_tasks_scoring_fields_match_v1_0():
    # v1.0 stays frozen per its own versioning policy -- every task_id
    # that also exists in v1.0 must round-trip to the exact same
    # SCORING-RELEVANT fields (scene/goal/object/target/instruction) in
    # v1.1's copy of it, so a score computed against either file's copy
    # of a v1.0 task_id is directly comparable.
    #
    # This does NOT assert the two rows are byte-identical JSON --
    # `notes` (free-text, non-scoring) was deliberately edited on 2
    # tasks when v1.1 was authored: `milo-v1-fp301-t3a` (cosmetic
    # addition) and `milo-v1-fp401-t3a` (substantively rewritten to
    # reflect the `_deposit()` non-openable-target bug now being fixed,
    # where v1.0's note still says it is unfixed -- see
    # `dataset/v1.1/README.md`'s "What's new in v1.1" section). `notes`
    # is intentionally not compared here for that reason.
    v1_0_tasks = {t.task_id: t for t in load_tasks(version="1.0")}
    v1_1_tasks = {t.task_id: t for t in load_tasks(version="1.1")}
    shared_ids = set(v1_0_tasks) & set(v1_1_tasks)
    assert shared_ids == set(v1_0_tasks)  # every v1.0 task_id survives into v1.1
    for task_id in shared_ids:
        old, new = v1_0_tasks[task_id], v1_1_tasks[task_id]
        assert old.scene == new.scene
        assert old.goal == new.goal
        assert old.object == new.object
        assert old.target == new.target
        assert old.instruction == new.instruction


def test_benchmark_task_to_single_tasks_flat_row_returns_one_task():
    bt = next(t for t in load_tasks(version="1.1") if t.task_id == "milo-v1-fp1-t3a")
    singles = bt.to_single_tasks()
    assert len(singles) == 1
    assert singles[0].goal == "store"
    assert singles[0].task_id == "milo-v1-fp1-t3a"


def test_benchmark_task_to_single_tasks_tier4_row_returns_two_ordered_tasks():
    bt = next(t for t in load_tasks(version="1.1") if t.task_id == "milo-v1.1-fp1-t4a")
    singles = bt.to_single_tasks()
    assert [s.object for s in singles] == ["knife", "cup"]
    assert [s.target for s in singles] == ["drawer", "cabinet"]
    assert [s.goal for s in singles] == ["store", "store"]
    # Suffixed task_ids so per-subtask episodes stay individually
    # identifiable without colliding with the parent task_id.
    assert singles[0].task_id == "milo-v1.1-fp1-t4a-sub1"
    assert singles[1].task_id == "milo-v1.1-fp1-t4a-sub2"


def test_to_single_task_raises_for_a_tier4_multi_subtask_row():
    bt = next(t for t in load_tasks(version="1.1") if t.task_id == "milo-v1.1-fp1-t4a")
    try:
        bt.to_single_task()
        raise AssertionError("expected ValueError for a multi-subtask row")
    except ValueError:
        pass


# ---------------------------------------------------------------------
# check_goal_live_multi() -- tier4_multi_step's success-predicate
# extension: AND across every independent sub-goal, evaluated against
# one shared post-execution metadata snapshot.
# ---------------------------------------------------------------------


def test_check_goal_live_multi_true_when_every_subtask_holds():
    tasks = [
        SingleTask(goal="store", object="knife", target="drawer"),
        SingleTask(goal="store", object="cup", target="cabinet"),
    ]
    metadata = {
        "objects": [
            _obj(
                "Knife|1",
                "Knife",
                isPickedUp=False,
                parentReceptacles=["Drawer|1"],
            ),
            _obj("Drawer|1", "Drawer"),
            _obj("Cup|1", "Cup", isPickedUp=False, parentReceptacles=["Cabinet|1"]),
            _obj("Cabinet|1", "Cabinet"),
        ]
    }
    result = check_goal_live_multi(tasks, metadata)
    assert result.per_subtask == [True, True]
    assert result.all_succeeded is True


def test_check_goal_live_multi_false_when_only_one_subtask_holds():
    """
    The case tier4 exists to catch: a planner that completes the first
    sub-goal but mis-sequences/never reaches the second must not be
    scored a success -- `all_succeeded` requires BOTH, not "at least
    one."
    """
    tasks = [
        SingleTask(goal="store", object="knife", target="drawer"),
        SingleTask(goal="store", object="cup", target="cabinet"),
    ]
    metadata = {
        "objects": [
            _obj(
                "Knife|1",
                "Knife",
                isPickedUp=False,
                parentReceptacles=["Drawer|1"],
            ),
            _obj("Drawer|1", "Drawer"),
            # Cup never made it into the cabinet -- still held.
            _obj("Cup|1", "Cup", isPickedUp=True, parentReceptacles=[]),
            _obj("Cabinet|1", "Cabinet"),
        ]
    }
    result = check_goal_live_multi(tasks, metadata)
    assert result.per_subtask == [True, False]
    assert result.all_succeeded is False


def test_check_goal_live_multi_false_when_both_subtasks_fail():
    tasks = [
        SingleTask(goal="store", object="knife", target="drawer"),
        SingleTask(goal="store", object="cup", target="cabinet"),
    ]
    metadata = {"objects": []}
    result = check_goal_live_multi(tasks, metadata)
    assert result.per_subtask == [False, False]
    assert result.all_succeeded is False


def test_check_goal_live_multi_empty_list_does_not_succeed():
    # Defensive: an empty subtask list should never read as a vacuous
    # success.
    assert check_goal_live_multi([], {"objects": []}).all_succeeded is False
