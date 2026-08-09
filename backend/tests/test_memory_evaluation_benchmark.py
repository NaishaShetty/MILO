"""
test_memory_evaluation_benchmark.py

Purpose
-------
Regression coverage for Phase 6.4's benchmark infrastructure
(`memory_evaluation/scenarios.py`, `experiment.py`, `memory_size.py`,
`pollution.py`, `task_ablation.py`, `run_benchmark.py`). These tests
lock in the *actual, measured* behavior discovered while building the
benchmark -- including the negative findings (memory increasing action
count on this planner, and stale memory causing outright task failure
in the "hard stale" case) -- as regression tests, not just narrative in
a report: if a future change to `RuleBasedPlanner`/`TaskRunner`
silently alters this behavior, these tests should fail and force that
change to be a deliberate, documented one.

Persistence-across-restart is already covered by
`test_orchestration_task_runner.py::TestPersistenceAcrossRestart` and
`TestGoldenMemoryTest` -- not duplicated here.
"""

from __future__ import annotations

from memory_evaluation.experiment import run_scenario, run_scenario_both_conditions
from memory_evaluation.memory_size import run_memory_size_experiment
from memory_evaluation.pollution import run_pollution_check
from memory_evaluation.scenarios import (
    ALL_SCENARIOS,
    CATEGORY_A_OBJECT_RECALL,
    CATEGORY_C_FAILURE_RECOVERY,
    CATEGORY_D_STALE_MEMORY,
    CATEGORY_E_CONFLICTING_MEMORY,
)
from memory_evaluation.task_ablation import run_task_level_ablation


class TestEveryScenarioRunsUnderBothConditions:
    def test_all_scenarios_run_without_error(self, tmp_path):
        for scenario in ALL_SCENARIOS:
            results = run_scenario_both_conditions(
                scenario, tmp_path / scenario.scenario_id
            )
            assert len(results["memory_off"]) == len(scenario.episodes)
            assert len(results["memory_on"]) == len(scenario.episodes)

    def test_memory_off_never_retrieves_memory(self, tmp_path):
        for scenario in ALL_SCENARIOS:
            off_results = run_scenario(
                scenario, "memory_off", tmp_path / scenario.scenario_id
            )
            for ep in off_results:
                assert ep.memory_context_count == 0
                assert ep.memory_used_in_plan is False


class TestCategoryAObjectRecall:
    def test_memory_on_prioritizes_remembered_location(self, tmp_path):
        results = run_scenario(CATEGORY_A_OBJECT_RECALL, "memory_on", tmp_path)
        assert results[0].memory_context_count == 0  # nothing to recall yet
        recall = results[1]
        assert recall.memory_context_count > 0
        assert recall.plan_targets[0] == "table"
        assert recall.success is True

    def test_memory_off_plans_identically_across_episodes(self, tmp_path):
        results = run_scenario(CATEGORY_A_OBJECT_RECALL, "memory_off", tmp_path)
        assert results[0].plan_targets == results[1].plan_targets == ["mug", "mug"]

    def test_memory_on_uses_more_actions_than_memory_off_here(self, tmp_path):
        # Documents the measured (not assumed) finding: on this
        # planner/simulator, the memory hint *adds* a locate+navigate
        # pair ahead of the object's own grounding rather than
        # replacing it, so memory_on costs more actions here, not fewer.
        off = run_scenario(CATEGORY_A_OBJECT_RECALL, "memory_off", tmp_path / "off")
        on = run_scenario(CATEGORY_A_OBJECT_RECALL, "memory_on", tmp_path / "on")
        assert on[1].action_count > off[1].action_count


class TestCategoryCFailureRecovery:
    def test_memory_on_links_recovery_to_the_prior_failure(self, tmp_path):
        results = run_scenario(CATEGORY_C_FAILURE_RECOVERY, "memory_on", tmp_path)
        blocked, retried = results
        assert blocked.success is False
        assert blocked.failure_cause is not None
        assert retried.success is True
        assert retried.recovered_from is not None

    def test_memory_off_still_recovers_but_without_a_recovery_link(self, tmp_path):
        results = run_scenario(CATEGORY_C_FAILURE_RECOVERY, "memory_off", tmp_path)
        blocked, retried = results
        assert blocked.success is False
        assert retried.success is True
        assert retried.recovered_from is None


class TestCategoryDStaleMemory:
    def test_soft_stale_still_succeeds_with_extra_actions(self, tmp_path):
        results = run_scenario(CATEGORY_D_STALE_MEMORY, "memory_on", tmp_path)
        _, soft_stale, _ = results
        assert soft_stale.success is True
        assert soft_stale.memory_context_count > 0
        assert soft_stale.plan_targets[0] == "table"  # the stale hint is still used

    def test_hard_stale_causes_task_failure_under_memory_on(self, tmp_path):
        # The key, honest negative finding this category exists to
        # surface: `TaskRunner` always runs `WorldState.initial()` (an
        # empty world state -- Vision is not wired in as of Phase 6.3/
        # 6.4), so `RuleBasedPlanner`'s "current perception overrides
        # stale memory" branch never fires in this integration. When
        # the memory-hinted location no longer exists in the scene at
        # all, the inserted locate step cannot resolve and the whole
        # task fails -- even though the target object itself is
        # perfectly reachable.
        results = run_scenario(CATEGORY_D_STALE_MEMORY, "memory_on", tmp_path)
        _, _, hard_stale = results
        assert hard_stale.success is False

    def test_hard_stale_succeeds_under_memory_off(self, tmp_path):
        # Same scene, same task, memory simply never consulted -- the
        # robot finds the mug directly and succeeds. This is the
        # controlled baseline proving the failure above is caused by
        # the stale memory hint, not by the scene change itself.
        results = run_scenario(CATEGORY_D_STALE_MEMORY, "memory_off", tmp_path)
        _, _, hard_stale = results
        assert hard_stale.success is True


class TestCategoryEConflictingMemory:
    def test_both_conflicting_memories_are_retrieved(self, tmp_path):
        results = run_scenario(CATEGORY_E_CONFLICTING_MEMORY, "memory_on", tmp_path)
        (episode,) = results
        assert episode.memory_context_count == 2

    def test_higher_confidence_more_recent_memory_wins_the_plan_and_task_still_succeeds(
        self, tmp_path
    ):
        results = run_scenario(CATEGORY_E_CONFLICTING_MEMORY, "memory_on", tmp_path)
        (episode,) = results
        assert episode.plan_targets[0] == "cabinet"  # higher confidence, newer
        assert episode.success is True

    def test_memory_off_ignores_the_seeded_conflict_entirely(self, tmp_path):
        results = run_scenario(CATEGORY_E_CONFLICTING_MEMORY, "memory_off", tmp_path)
        (episode,) = results
        assert episode.memory_context_count == 0
        assert episode.success is True


class TestMemorySizeExperiment:
    def test_real_memory_still_surfaces_despite_distractor_volume(self, tmp_path):
        results = run_memory_size_experiment(tmp_path, sizes=(5, 20))
        for result in results:
            assert result.real_memory_retrieved is True
            assert result.task_success is True
            assert result.retrieval_latency_ms >= 0.0

    def test_memory_count_reflects_distractors_plus_real_fact(self, tmp_path):
        results = run_memory_size_experiment(tmp_path, sizes=(5,))
        assert results[0].memory_count == 6  # 5 distractors + 1 real observation


class TestMemoryPollution:
    def test_semantic_memory_growth_is_bounded_not_per_frame(self, tmp_path):
        report = run_pollution_check(tmp_path)
        assert report.total_episodes > 0
        # Controlled growth: nowhere near "one semantic memory per
        # every field in every scene object" -- bounded by the number
        # of successful, object-naming episodes (plus a small, fixed
        # number of scenario preconditions seeded once, not per
        # episode).
        assert report.semantic_memories_created <= report.total_episodes + 5


class TestTaskLevelAblation:
    def test_every_ranking_config_still_uses_memory_when_only_one_candidate_exists(
        self, tmp_path
    ):
        report = run_task_level_ablation(tmp_path)
        assert set(report.keys()) == {"A_object_recall", "E_conflicting_memory"}
        for episodes in report["A_object_recall"].values():
            recall_episode = episodes[1]
            assert recall_episode["plan_targets"][0] == "table"
            assert recall_episode["success"] is True

    def test_every_ranking_config_resolves_the_conflict_and_still_succeeds(
        self, tmp_path
    ):
        report = run_task_level_ablation(tmp_path)
        for episodes in report["E_conflicting_memory"].values():
            (episode,) = episodes
            assert episode["memory_context_count"] == 2
            assert episode["success"] is True
