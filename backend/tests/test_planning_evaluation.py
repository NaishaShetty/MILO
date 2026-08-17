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

from planning_evaluation.live_state import check_goal_live
from planning_evaluation.loader import load_tasks
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
