"""
scenarios.py (backend/memory_evaluation)

Purpose
-------
Phase 6.4's benchmark task suite: a deterministic, version-controlled
set of multi-episode scenarios exercising the five memory-relevant
behaviors the phase spec asks for (object location recall, episodic
experience, failure recovery, stale memory, conflicting memory). Built
entirely from real project types -- `schemas.task.SingleTask`,
`_execution_test_helpers.FakeSimulator`-shaped object dicts, and
`memory.agent.MemoryAgent`'s own public write API for seeding
preconditions -- never a parallel task representation, and never a
fabricated object location injected outside those normal write paths.

Every scenario is a sequence of `EpisodeSpec`s run in order against one
shared `TaskRunner`/`MemoryAgent`/`MemoryConfig` (a fresh simulator per
episode, since each episode is a new visit to the scene): memory formed
in episode N is available -- when the condition is `memory_on` -- to
episode N+1, exactly like separate task invocations on the same robot
across time.

Determinism note
-----------------
This benchmark is entirely deterministic: `RuleBasedPlanner` +
`FakeSimulator`, no LLM call, no randomness anywhere in the loop.
`seed` is recorded on every scenario for reproducibility bookkeeping
only -- running a scenario twice with the same seed always produces
byte-identical results. See `run_benchmark.py`'s docstring for what
that does (and does not) mean for the statistics reported over this
suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from schemas.task import SingleTask


@dataclass(frozen=True)
class EpisodeSpec:
    """One episode within a scenario: a task, the scene it runs against,
    and any controlled simulator failure."""

    label: str
    task: SingleTask
    objects: List[Dict[str, Any]]
    fail_actions: Optional[Set[str]] = None
    #: What this episode is meant to demonstrate -- human-readable,
    #: never used to alter scoring; purely for report generation.
    expectation: str = ""


@dataclass(frozen=True)
class BenchmarkScenario:
    """A named, versioned, multi-episode benchmark case."""

    scenario_id: str
    category: str
    description: str
    seed: int
    episodes: List[EpisodeSpec]
    #: (subject, predicate, object, confidence) triples seeded via
    #: `MemoryAgent.remember_observation()` -- the same public write
    #: path production observations use -- before episode 1, only when
    #: the condition being run is `memory_on`. Empty for scenarios that
    #: rely solely on memory formed during their own episodes.
    preconditions: List[Tuple[str, str, str, float]] = field(default_factory=list)


def _mug_on_table() -> List[Dict[str, Any]]:
    return [
        {
            "objectId": "Mug|1",
            "objectType": "Mug",
            "distance": 1.0,
            "isOpen": None,
            "parentReceptacle": "Table|1",
        },
        {"objectId": "Table|1", "objectType": "Table", "distance": 2.0, "isOpen": None},
    ]


def _mug_on_cabinet_table_present() -> List[Dict[str, Any]]:
    """Environment change: the mug moved, but the old receptacle
    ("table") is still physically present in the scene -- a "soft"
    staleness case."""
    return [
        {
            "objectId": "Mug|1",
            "objectType": "Mug",
            "distance": 1.0,
            "isOpen": None,
            "parentReceptacle": "Cabinet|1",
        },
        {"objectId": "Table|1", "objectType": "Table", "distance": 3.0, "isOpen": None},
        {
            "objectId": "Cabinet|1",
            "objectType": "Cabinet",
            "distance": 2.0,
            "isOpen": True,
        },
    ]


def _mug_on_cabinet_table_removed() -> List[Dict[str, Any]]:
    """Environment change: the mug moved AND the old receptacle no
    longer exists in the scene at all -- a "hard" staleness case."""
    return [
        {
            "objectId": "Mug|1",
            "objectType": "Mug",
            "distance": 1.0,
            "isOpen": None,
            "parentReceptacle": "Cabinet|1",
        },
        {
            "objectId": "Cabinet|1",
            "objectType": "Cabinet",
            "distance": 2.0,
            "isOpen": True,
        },
    ]


def _mug_on_cabinet_with_table_present() -> List[Dict[str, Any]]:
    """Current reality matches the newer of the two conflicting
    memories (`mug located_on cabinet`); the older memory's referenced
    object (`table`) is also still present, so either resolves."""
    return [
        {
            "objectId": "Mug|1",
            "objectType": "Mug",
            "distance": 1.0,
            "isOpen": None,
            "parentReceptacle": "Cabinet|1",
        },
        {"objectId": "Table|1", "objectType": "Table", "distance": 3.0, "isOpen": None},
        {
            "objectId": "Cabinet|1",
            "objectType": "Cabinet",
            "distance": 2.0,
            "isOpen": True,
        },
    ]


def _fridge_scene() -> List[Dict[str, Any]]:
    return [
        {
            "objectId": "Fridge|1",
            "objectType": "Fridge",
            "distance": 1.0,
            "isOpen": False,
        }
    ]


# ---------------------------------------------------------------------
# Category A -- Object Location Recall
# ---------------------------------------------------------------------

CATEGORY_A_OBJECT_RECALL = BenchmarkScenario(
    scenario_id="A_object_recall_mug",
    category="A_object_location_recall",
    description=(
        "Find the same object (the mug) twice, in the same, unchanged "
        "scene. Memory should let the second episode prioritize the "
        "location learned in the first."
    ),
    seed=1001,
    episodes=[
        EpisodeSpec(
            label="episode_1_first_visit",
            task=SingleTask(goal="find", object="mug", task_id="A-mug-ep1"),
            objects=_mug_on_table(),
            expectation="No prior memory; plan searches for the mug directly.",
        ),
        EpisodeSpec(
            label="episode_2_recall",
            task=SingleTask(goal="find", object="mug", task_id="A-mug-ep2"),
            objects=_mug_on_table(),
            expectation=(
                "Under memory_on, the plan's first target should be the "
                "remembered location (table), not the mug itself."
            ),
        ),
    ],
)

# ---------------------------------------------------------------------
# Category B -- Episodic Experience
# ---------------------------------------------------------------------

CATEGORY_B_EPISODIC_EXPERIENCE = BenchmarkScenario(
    scenario_id="B_episodic_experience_mug",
    category="B_episodic_experience",
    description=(
        "Find the mug, then perform a related task on the same object "
        "(bring it to the table). Memory should let the second episode "
        "skip exploration for a location it already learned."
    ),
    seed=1002,
    episodes=[
        EpisodeSpec(
            label="episode_1_find",
            task=SingleTask(goal="find", object="mug", task_id="B-mug-ep1"),
            objects=_mug_on_table(),
            expectation="Establishes an episodic memory + location observation.",
        ),
        EpisodeSpec(
            label="episode_2_related_task",
            task=SingleTask(
                goal="bring", object="mug", target="table", task_id="B-mug-ep2"
            ),
            objects=_mug_on_table(),
            expectation=(
                "Under memory_on, the plan may need fewer/earlier-targeted "
                "steps to locate the mug before acting on it."
            ),
        ),
    ],
)

# ---------------------------------------------------------------------
# Category C -- Failure Recovery
# ---------------------------------------------------------------------

CATEGORY_C_FAILURE_RECOVERY = BenchmarkScenario(
    scenario_id="C_failure_recovery_fridge",
    category="C_failure_recovery",
    description=(
        "Reach the fridge; the first attempt is blocked (navigate always "
        "fails). Retry the same task once the obstacle is cleared."
    ),
    seed=1003,
    episodes=[
        EpisodeSpec(
            label="episode_1_blocked",
            task=SingleTask(goal="find", object="fridge", task_id="C-fridge-task"),
            objects=_fridge_scene(),
            fail_actions={"navigate"},
            expectation="Execution fails; a FAILURE memory is created with a real cause.",
        ),
        EpisodeSpec(
            label="episode_2_retry_cleared",
            task=SingleTask(goal="find", object="fridge", task_id="C-fridge-task"),
            objects=_fridge_scene(),
            expectation=(
                "Same task_id retried with the obstacle cleared -- "
                "measures whether the run succeeds and whether recovery "
                "is linked to the earlier failure."
            ),
        ),
    ],
)

# ---------------------------------------------------------------------
# Category D -- Stale Memory
# ---------------------------------------------------------------------

CATEGORY_D_STALE_MEMORY = BenchmarkScenario(
    scenario_id="D_stale_memory_mug",
    category="D_stale_memory",
    description=(
        "Learn the mug's location, then the environment changes twice: "
        "first a 'soft' move (the old receptacle is still physically "
        "present), then a 'hard' move (the old receptacle no longer "
        "exists in the scene at all). Tests whether stale memory causes "
        "wasted actions, outright task failure, or is correctly "
        "superseded."
    ),
    seed=1004,
    episodes=[
        EpisodeSpec(
            label="episode_1_learn_location",
            task=SingleTask(goal="find", object="mug", task_id="D-mug-ep1"),
            objects=_mug_on_table(),
            expectation="Establishes 'mug located_on table' as an observed memory.",
        ),
        EpisodeSpec(
            label="episode_2_soft_stale",
            task=SingleTask(goal="find", object="mug", task_id="D-mug-ep2"),
            objects=_mug_on_cabinet_table_present(),
            expectation=(
                "Mug moved to the cabinet; the table object still exists "
                "in the scene, so a stale memory-hinted step can still "
                "resolve (extra, wasted actions) without failing the task."
            ),
        ),
        EpisodeSpec(
            label="episode_3_hard_stale",
            task=SingleTask(goal="find", object="mug", task_id="D-mug-ep3"),
            objects=_mug_on_cabinet_table_removed(),
            expectation=(
                "Mug moved to the cabinet AND the table no longer exists "
                "in the scene at all -- a stale memory-hinted step "
                "targeting 'table' cannot resolve. Tests whether this "
                "breaks the whole task."
            ),
        ),
    ],
)

# ---------------------------------------------------------------------
# Category E -- Conflicting Memory
# ---------------------------------------------------------------------

CATEGORY_E_CONFLICTING_MEMORY = BenchmarkScenario(
    scenario_id="E_conflicting_memory_mug",
    category="E_conflicting_memory",
    description=(
        "Two conflicting observations exist for the same object before "
        "the episode starts: an older, lower-confidence one (table) and "
        "a newer, higher-confidence one (cabinet, matching current "
        "reality). Verifies the planner receives both and that the "
        "conflict is handled safely, not that full belief revision "
        "occurs."
    ),
    seed=1005,
    preconditions=[
        ("mug", "located_on", "table", 0.6),
        ("mug", "located_on", "cabinet", 0.9),
    ],
    episodes=[
        EpisodeSpec(
            label="episode_1_conflicting_evidence",
            task=SingleTask(goal="find", object="mug", task_id="E-mug-ep1"),
            objects=_mug_on_cabinet_with_table_present(),
            expectation=(
                "Both conflicting memories should be retrievable; the "
                "higher-ranked one should inform the plan; the task "
                "should still succeed via real object resolution "
                "regardless of which memory is used."
            ),
        ),
    ],
)

ALL_SCENARIOS: List[BenchmarkScenario] = [
    CATEGORY_A_OBJECT_RECALL,
    CATEGORY_B_EPISODIC_EXPERIENCE,
    CATEGORY_C_FAILURE_RECOVERY,
    CATEGORY_D_STALE_MEMORY,
    CATEGORY_E_CONFLICTING_MEMORY,
]
