"""
real_scenarios.py (backend/memory_evaluation)

Purpose
-------
Phase B's task set: the same kind of memory-relevant episode groupings
`scenarios.py` defines for `FakeSimulator`, adapted for a REAL AI2-THOR
scene (`FloorPlan1`, this project's default -- see
`config/*_config.py`). See `experiment_real.py`'s docstring for why a
separate module exists rather than reusing `scenarios.py` directly.

Why these episodes look different from `scenarios.py`'s
------------------------------------------------------------
`scenarios.py`'s `EpisodeSpec.objects` lets each episode hand
`FakeSimulator` an arbitrary, hand-authored scene (so "the mug moved to
the cabinet" is just a different `objects` list). A real AI2-THOR scene
cannot be rewritten between episodes without extending `simulator.
simulator.Simulator` with object-teleportation methods it does not
currently expose (out of scope for this pass -- see `docs/roadmap.md`).
Every episode here therefore runs against the SAME, real, unmodified
`FloorPlan1` scene, restarted (fresh Unity process) between episodes so
no episode inherits leftover held-object/pose state from the one before
it -- exactly `run_scenario`'s "fresh simulator per episode" contract,
just paid for with a real process restart instead of a cheap object
re-construction.

Object/target names are FloorPlan1's real, confirmed `objectType`
values, lowercased (`execution.resolver.ObjectResolver` matches
case-insensitively) -- "fridge", not "refrigerator" (the one confirmed
alias `resolver.py` carries), so every task resolves to a real object
with zero guessing.

What this task set demonstrates, concretely
------------------------------------------------
- **Category A (object recall)**: the same `find` task run twice.
  Under `memory_on`, episode 2's plan should show `_apply_memory_hint`'s
  effect (an extra `locate`/`navigate` pair ahead of the object itself).
- **Category B (episodic experience)**: `find` an object, then a
  related task on the same object.
- **Category C (closed-receptacle place)**: `place`/`store` into a
  real, physically-closed receptacle (cabinet/fridge/drawer are closed
  by default in this scene -- confirmed via a live `get_metadata()`
  scan) -- the exact case `rule_based.py`'s `_deposit()` fix (Phase A)
  and `TaskRunner.run(..., initial_state=...)` (this phase) exist to
  handle correctly end to end, and the exact case the Phase 8.7 audit
  reproduced as a live failure.
- **Category D (non-container place)**: `place` onto a flat surface
  (`countertop`) -- confirms the fix does NOT insert a spurious
  open/close for a destination that was never a container, matching
  `test_planner_rule_based.py::test_place_goal_has_no_open_close_for_non_container_target`.
- **Category E (natural failure)**: `open` on an object AI2-THOR
  itself will reject as not openable (`apple`) -- a real execution
  failure with no `FakeSimulator.fail_actions` hack needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from schemas.task import SingleTask


@dataclass(frozen=True)
class RealEpisodeSpec:
    label: str
    task: SingleTask
    #: Human-readable, never used to alter scoring -- matches
    #: `scenarios.EpisodeSpec.expectation`'s own convention.
    expectation: str = ""


@dataclass(frozen=True)
class RealScenario:
    scenario_id: str
    category: str
    description: str
    seed: int
    episodes: List[RealEpisodeSpec] = field(default_factory=list)


REAL_CATEGORY_A_OBJECT_RECALL = RealScenario(
    scenario_id="RA_object_recall_mug",
    category="A_object_location_recall",
    description=(
        "Find the mug twice in the same, real, unchanged FloorPlan1 "
        "scene. Memory should let the second episode prioritize the "
        "location learned in the first."
    ),
    seed=2001,
    episodes=[
        RealEpisodeSpec(
            label="episode_1_first_visit",
            task=SingleTask(goal="find", object="mug", task_id="RA-mug-ep1"),
            expectation="No prior memory; plan searches for the mug directly.",
        ),
        RealEpisodeSpec(
            label="episode_2_recall",
            task=SingleTask(goal="find", object="mug", task_id="RA-mug-ep2"),
            expectation=(
                "Under memory_on, the plan's first target should be the "
                "remembered location, not the mug itself."
            ),
        ),
    ],
)

REAL_CATEGORY_B_EPISODIC_EXPERIENCE = RealScenario(
    scenario_id="RB_episodic_experience_bowl",
    category="B_episodic_experience",
    description=(
        "Find the bowl, then pick it up in a later episode. Memory "
        "should let the second episode skip exploration for a location "
        "it already learned."
    ),
    seed=2002,
    episodes=[
        RealEpisodeSpec(
            label="episode_1_find",
            task=SingleTask(goal="find", object="bowl", task_id="RB-bowl-ep1"),
            expectation="Establishes an episodic memory + location observation.",
        ),
        RealEpisodeSpec(
            label="episode_2_pick_up",
            task=SingleTask(goal="pick_up", object="bowl", task_id="RB-bowl-ep2"),
            expectation=(
                "Under memory_on, the plan may prioritize the "
                "remembered location before acquiring the bowl."
            ),
        ),
    ],
)

REAL_CATEGORY_C_CLOSED_RECEPTACLE = RealScenario(
    scenario_id="RC_closed_receptacle_apple_cabinet",
    category="C_closed_receptacle_place",
    description=(
        "Place the apple in the cabinet, twice. The cabinet is closed "
        "by default in this scene (confirmed live) -- exercises the "
        "Phase A `_deposit()` fix plus this phase's `initial_state` "
        "seeding under real AI2-THOR physics, and is the exact "
        "scenario shape the Phase 8.7 audit's live mission reproduced "
        "as a failure."
    ),
    seed=2003,
    episodes=[
        RealEpisodeSpec(
            label="episode_1_first_placement",
            task=SingleTask(
                goal="place", object="apple", target="cabinet", task_id="RC-apple-ep1"
            ),
            expectation=(
                "Cabinet starts closed; the plan must open it before "
                "placing, then AI2-THOR must accept the placement."
            ),
        ),
        RealEpisodeSpec(
            label="episode_2_repeat",
            task=SingleTask(
                goal="place", object="apple", target="cabinet", task_id="RC-apple-ep2"
            ),
            expectation=(
                "Same task repeated (fresh scene each episode -- the "
                "cabinet is closed again) -- under memory_on, the plan "
                "may additionally prioritize the remembered apple "
                "location."
            ),
        ),
    ],
)

REAL_CATEGORY_C2_CLOSED_RECEPTACLE_FRIDGE = RealScenario(
    scenario_id="RC2_closed_receptacle_egg_fridge",
    category="C_closed_receptacle_place",
    description=(
        "Store the egg in the fridge, twice -- a second, distinct "
        "closed-receptacle object/container pair, using the 'store' "
        "goal template (which already unconditionally opened/closed "
        "even before Phase A) as a same-category comparison point "
        "against Category C's 'place' goal."
    ),
    seed=2004,
    episodes=[
        RealEpisodeSpec(
            label="episode_1_first_storage",
            task=SingleTask(
                goal="store", object="egg", target="fridge", task_id="RC2-egg-ep1"
            ),
            expectation="Fridge starts closed; plan opens it before storing.",
        ),
        RealEpisodeSpec(
            label="episode_2_repeat",
            task=SingleTask(
                goal="store", object="egg", target="fridge", task_id="RC2-egg-ep2"
            ),
            expectation="Repeated under a fresh (closed-again) scene.",
        ),
    ],
)

REAL_CATEGORY_D_NON_CONTAINER_PLACE = RealScenario(
    scenario_id="RD_non_container_place_mug_countertop",
    category="D_non_container_place",
    description=(
        "Place the mug on the countertop -- a flat, non-openable "
        "surface. Confirms the closed-receptacle fix does not insert a "
        "spurious open/close for a destination that was never a "
        "container."
    ),
    seed=2005,
    episodes=[
        RealEpisodeSpec(
            label="episode_1_place_on_countertop",
            task=SingleTask(
                goal="place",
                object="mug",
                target="countertop",
                task_id="RD-mug-ep1",
            ),
            expectation="No open/close steps; plan is locate/navigate/pickup/locate/navigate/place.",
        ),
        RealEpisodeSpec(
            label="episode_2_repeat",
            task=SingleTask(
                goal="place",
                object="mug",
                target="countertop",
                task_id="RD-mug-ep2",
            ),
            expectation="Repeated -- under memory_on, may prioritize the remembered mug location.",
        ),
    ],
)

REAL_CATEGORY_E_NATURAL_FAILURE = RealScenario(
    scenario_id="RE_natural_failure_open_apple",
    category="E_natural_execution_failure",
    description=(
        "Attempt to 'open' the apple -- not an openable object in "
        "AI2-THOR. A real execution failure with no FakeSimulator "
        "fail_actions hack needed; verifies a FAILURE memory is formed "
        "with a real cause under both a first attempt and a retry."
    ),
    seed=2006,
    episodes=[
        RealEpisodeSpec(
            label="episode_1_first_attempt",
            task=SingleTask(goal="open", object="apple", task_id="RE-apple-task"),
            expectation="AI2-THOR rejects opening a non-openable object; execution fails.",
        ),
        RealEpisodeSpec(
            label="episode_2_retry",
            task=SingleTask(goal="open", object="apple", task_id="RE-apple-task"),
            expectation=(
                "Same task_id retried -- the apple is still not "
                "openable, so this always fails again regardless of "
                "condition; measures whether memory_on at least links "
                "the failure via `MemoryAgent.link_recovery()` machinery "
                "without fabricating a success."
            ),
        ),
    ],
)

REAL_CATEGORY_F_OBJECT_SWEEP = RealScenario(
    scenario_id="RF_object_sweep",
    category="F_object_variety",
    description=(
        "Distinct single-object tasks across different goals/objects in "
        "the same real scene -- breadth rather than repetition, so the "
        "comparison isn't dominated by only mug/apple/cabinet."
    ),
    seed=2007,
    episodes=[
        RealEpisodeSpec(
            label="episode_1_pick_up_spoon",
            task=SingleTask(goal="pick_up", object="spoon", task_id="RF-spoon"),
            expectation="Simple 3-step acquire.",
        ),
        RealEpisodeSpec(
            label="episode_2_find_pot",
            task=SingleTask(goal="find", object="pot", task_id="RF-pot"),
            expectation="Simple 2-step perceive.",
        ),
        RealEpisodeSpec(
            label="episode_3_open_drawer",
            task=SingleTask(goal="open", object="drawer", task_id="RF-drawer-open"),
            expectation="Drawer is openable; should succeed.",
        ),
        RealEpisodeSpec(
            label="episode_4_store_potato_fridge",
            task=SingleTask(
                goal="store", object="potato", target="fridge", task_id="RF-potato"
            ),
            expectation="Closed-receptacle store, distinct object pair.",
        ),
    ],
)

ALL_REAL_SCENARIOS: List[RealScenario] = [
    REAL_CATEGORY_A_OBJECT_RECALL,
    REAL_CATEGORY_B_EPISODIC_EXPERIENCE,
    REAL_CATEGORY_C_CLOSED_RECEPTACLE,
    REAL_CATEGORY_C2_CLOSED_RECEPTACLE_FRIDGE,
    REAL_CATEGORY_D_NON_CONTAINER_PLACE,
    REAL_CATEGORY_E_NATURAL_FAILURE,
    REAL_CATEGORY_F_OBJECT_SWEEP,
]
