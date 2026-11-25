"""Phase A: episode log schema, synthetic generator, dataset builder and splits."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.build_dataset import assign_splits, build, split_scenes
from learning.episode_log import EpisodeLogger, SchemaMismatchError
from learning.features import failure_type, world_features
from learning.generate import generate, run_episode
from learning.schema import FAILURE_TYPES, SCHEMA_VERSION, STEP_COLUMNS
from learning.synthetic import Faults, SyntheticSimulator, make_scene
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from schemas.task import SingleTask


def test_schema_version_is_recorded_and_enforced(tmp_path):
    db = tmp_path / "log.db"
    EpisodeLogger(db)
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0] == str(SCHEMA_VERSION)
        conn.execute("UPDATE meta SET value='999'")
        conn.commit()
    with pytest.raises(SchemaMismatchError):
        EpisodeLogger(db)


def test_a_mission_writes_a_complete_trace(tmp_path):
    db = tmp_path / "log.db"
    scene = make_scene("scene_t", 0)
    item = next(o["objectType"].lower() for o in scene if o.get("pickupable"))
    sim = SyntheticSimulator(scene)
    orch = Orchestrator(
        PlannerAgentWrapper(create_planner("rule_based")),
        ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
        episode_logger=EpisodeLogger(db),
    )
    orch.episode_context = {
        "scene_id": "scene_t",
        "seed": 0,
        "task_text": f"pick up the {item}",
    }
    state = orch.run(SingleTask(goal="pick_up", object=item))

    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        ep = conn.execute("SELECT * FROM episodes").fetchone()
        steps = [
            dict(r) for r in conn.execute("SELECT * FROM steps ORDER BY step_index")
        ]
    assert ep["outcome"] == state.status.value == "succeeded"
    assert ep["scene_id"] == "scene_t" and ep["planner"] == "rule_based"
    assert json.loads(ep["parsed_task"])["goal"] == "pick_up"
    assert [s["action"] for s in steps] == ["locate", "navigate", "pickup"]
    assert set(steps[0]) == {name for name, _ in STEP_COLUMNS}
    assert all(s["success"] == 1 and s["failure_type"] == "none" for s in steps)
    assert all(s["verdict"] == "continue" for s in steps)
    before, after = json.loads(steps[2]["before"]), json.loads(steps[2]["after"])
    assert before["held"] == "none" and after["held"] == item
    assert before["reachable"] == 1 and steps[2]["remaining_steps"] == 0


def test_injected_faults_produce_labelled_failures(tmp_path):
    db = tmp_path / "log.db"
    scene = make_scene("scene_f", 0)
    item = next(o["objectType"].lower() for o in scene if o.get("pickupable"))
    sim = SyntheticSimulator(scene, Faults("blocked_path", item, times=99))
    orch = Orchestrator(
        PlannerAgentWrapper(create_planner("rule_based")),
        ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
        episode_logger=EpisodeLogger(db),
    )
    state = orch.run(SingleTask(goal="pick_up", object=item))
    assert state.status.value == "failed"
    with closing(sqlite3.connect(db)) as conn:
        kinds = {
            r[0] for r in conn.execute("SELECT failure_type FROM steps WHERE success=0")
        }
        replans = conn.execute("SELECT replans FROM episodes").fetchone()[0]
    assert kinds == {"blocked"} and replans >= 1


def test_failure_type_labels():
    assert failure_type(None, None, True) == "none"
    assert failure_type("ACTION_TIMEOUT", "x", False) == "timeout"
    assert failure_type("OBJECT_NOT_FOUND", "no live object", False) == "wrong_object"
    assert (
        failure_type("SIMULATOR_ERROR", "cannot pick up: object not visible", False)
        == "not_visible"
    )
    assert (
        failure_type("SIMULATOR_ERROR", "cannot pick up: object not reachable", False)
        == "not_reachable"
    )
    assert failure_type("NAVIGATION_FAILED", "path blocked", False) == "blocked"
    assert failure_type("SIMULATOR_ERROR", "hand is full", False) == "other"
    assert set(FAILURE_TYPES) >= {"none", "blocked", "timeout", "other"}


def test_world_features_are_deterministic_and_complete():
    meta = SyntheticSimulator(make_scene("scene_x", 1)).get_metadata()
    name = next(o["objectType"] for o in meta["objects"] if o.get("pickupable"))
    a, b = world_features(meta, name), world_features(meta, name)
    assert a == b
    assert set(a) == {
        "target_found",
        "visible",
        "distance",
        "is_open",
        "is_on",
        "reachable",
        "held",
        "object_class",
    }
    assert world_features(meta, "nonexistent")["target_found"] == 0


def test_scenes_are_deterministic():
    assert make_scene("scene_1", 0) == make_scene("scene_1", 0)
    assert make_scene("scene_1", 0) != make_scene("scene_2", 0)


# -- generator + builder --------------------------------------------------------


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("flywheel")
    generate(root / "episodes", episodes=240, scenes=12, seed=3, workers=2, batch=20)
    report = build(root / "episodes", root / "dataset", seed=0)
    return root, report


def test_dataset_builds_with_one_command_and_a_report(dataset):
    root, report = dataset
    out = root / "dataset"
    for name in (
        "train.csv",
        "val.csv",
        "test.csv",
        "report.json",
        "report.md",
        "manifest.json",
    ):
        assert (out / name).exists()
    assert report["total_episodes"] == 240 and report["total_labelled_steps"] > 500
    assert report["failure_types"]["none"] > 0
    assert sum(v for k, v in report["failure_types"].items() if k != "none") > 50
    assert (
        report["failure_types"]["wrong_object"] > 0
    )  # missing-object fault is covered
    assert "| split |" in (out / "report.md").read_text()


def test_no_episode_or_scene_overlap_between_splits(dataset):
    root, _ = dataset
    import csv

    def load(name):
        with open(root / "dataset" / f"episodes_{name}.csv") as f:
            return list(csv.DictReader(f))

    eps = {n: load(n) for n in ("train", "val", "test")}
    ids = {n: {e["episode_id"] for e in rows} for n, rows in eps.items()}
    assert (
        not (ids["train"] & ids["val"])
        and not (ids["train"] & ids["test"])
        and not (ids["val"] & ids["test"])
    )
    scenes = {n: {e["scene_id"] for e in rows} for n, rows in eps.items()}
    assert (
        scenes["test"]
        and not (scenes["test"] & scenes["train"])
        and not (scenes["test"] & scenes["val"])
    )
    # Steps never leak either: each step row's episode is only in its own split.
    for name in ("train", "val", "test"):
        with open(root / "dataset" / f"{name}.csv") as f:
            step_eps = {r["episode_id"] for r in csv.DictReader(f)}
        assert step_eps <= ids[name]


def test_splits_are_deterministic_and_cover_everything():
    episodes = {f"e{i}": f"scene_{i % 10}" for i in range(100)}
    a = assign_splits(episodes, 0.2, 0.15, seed=7)
    assert a == assign_splits(episodes, 0.2, 0.15, seed=7)
    assert set(a.values()) == {"train", "val", "test"}
    train_val, test = split_scenes([f"scene_{i}" for i in range(10)], 0.2, 7)
    assert len(test) == 2 and not set(test) & set(train_val)


def test_generation_is_resumable_and_deterministic(tmp_path):
    out = tmp_path / "eps"
    assert generate(out, 30, 5, seed=1, workers=1, batch=10) == 30
    assert generate(out, 30, 5, seed=1, workers=1, batch=10) == 0  # nothing left to do
    assert generate(out, 45, 5, seed=1, workers=1, batch=10) == 15  # only the new ones


def test_one_episode_is_fully_determined_by_its_seed(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    run_episode(a, 2, 5, seed=9)
    run_episode(b, 2, 5, seed=9)

    def rows(p: Path):
        with closing(sqlite3.connect(p)) as c:
            return c.execute(
                "SELECT action, target, success, failure_type FROM steps ORDER BY attempt, step_index"
            ).fetchall()

    assert rows(a) == rows(b)
