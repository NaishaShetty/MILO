"""Real AI2-THOR episode collection: task building and the scene split (no simulator)."""

from __future__ import annotations

import random

from learning.build_dataset import assign_splits
from learning.collect_thor import HELD_OUT_SCENES, TRAIN_SCENES, jobs, thor_task

SCENE = [
    {
        "objectType": "Apple",
        "pickupable": True,
        "toggleable": False,
        "isToggled": False,
    },
    {"objectType": "Fridge", "openable": True, "receptacle": True, "isToggled": False},
    {"objectType": "CounterTop", "receptacle": True, "isToggled": False},
    {"objectType": "LightSwitch", "toggleable": True, "isToggled": True},
]


def test_scene_lists_are_disjoint_and_cover_every_room_type():
    assert set(TRAIN_SCENES) & set(HELD_OUT_SCENES) == set()
    assert len(HELD_OUT_SCENES) == 20 and len(TRAIN_SCENES) == 100
    for base in ("FloorPlan30", "FloorPlan230", "FloorPlan330", "FloorPlan430"):
        assert base in HELD_OUT_SCENES


def test_half_the_episodes_run_in_held_out_scenes():
    todo = jobs(600)
    held = [s for s, _ in todo if s in HELD_OUT_SCENES]
    assert len(todo) == 600 and len(held) == 300
    assert len(set(todo)) == 600  # every episode id is unique


def test_tasks_only_use_switchable_things_as_switches():
    rng = random.Random(0)
    for _ in range(200):
        task, text = thor_task(rng, SCENE)
        if task.goal in ("turn_on", "turn_off"):
            assert (
                task.object == "lightswitch"
            )  # every object has isToggled; only this toggles
        if task.goal in ("open", "close"):
            assert task.object == "fridge"
        assert text


def test_no_task_in_an_empty_scene():
    assert thor_task(random.Random(0), []) is None


def test_explicit_held_out_scenes_become_the_test_split():
    episodes = {"a": "scene_1", "b": "scene_2", "c": "FloorPlan30", "d": "FloorPlan26"}
    split = assign_splits(
        episodes, 0.2, 0.0, 0, test_scenes=["FloorPlan26", "FloorPlan30"]
    )
    assert split == {"a": "train", "b": "train", "c": "test", "d": "test"}
