"""
test_orchestration_task_runner.py

Purpose
-------
Integration and end-to-end tests for `orchestration.task_runner.
TaskRunner` -- Phase 6.3 spec section 21's "Integration tests"
(Planner<->MemoryAgent, Executor<->MemoryAgent) and section 22's "Golden
Memory Test": a deterministic, multi-run proof that memory persists
across a simulated restart and demonstrably changes planner behavior,
plus a failure/recovery scenario. Everything here runs against
`FakeSimulator` (zero AI2-THOR dependency, matching every other Phase 5
test in this suite) and `RuleBasedPlanner` (deterministic, zero LLM
dependency).
"""

from __future__ import annotations

import sqlite3

from _execution_test_helpers import FakeSimulator

from execution.models import ExecutionStatus
from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from memory.models import MemoryProvenance, MemoryType
from orchestration.task_runner import TaskRunner
from planner.rule_based import RuleBasedPlanner
from schemas.task import SingleTask


def _config(tmp_path):
    return MemoryConfig(
        enabled=True,
        database_path=tmp_path / "memory.db",
        vector_store_path=tmp_path / "vector_store",
    )


def _mug_table_scene():
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


def _fridge_scene():
    return [
        {
            "objectId": "Fridge|1",
            "objectType": "Fridge",
            "distance": 1.0,
            "isOpen": False,
        }
    ]


class TestPlannerMemoryAgentIntegration:
    def test_retrieval_reaches_planner_end_to_end(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        agent.remember_observation(
            "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
        )
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))

        assert not result.memory_context.is_empty
        targets = [s.target for s in result.planning_result.plan.steps]
        assert "table" in targets


class TestExecutorMemoryAgentIntegration:
    def test_successful_execution_creates_episodic_memory(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))

        assert result.succeeded
        assert result.episodic_memory is not None
        assert result.episodic_memory.memory_type == MemoryType.EPISODIC
        assert agent.engine.manager.get(result.episodic_memory.memory_id) is not None

    def test_successful_execution_forms_one_observation_via_parent_receptacle(
        self, tmp_path
    ):
        agent = MemoryAgent.from_config(_config(tmp_path))
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))

        assert len(result.observation_memories) == 1
        observation = result.observation_memories[0]
        assert observation.memory_type == MemoryType.SEMANTIC
        assert observation.metadata["subject"] == "mug"
        assert observation.metadata["object"] == "table"

    def test_no_receptacle_means_no_observation(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        scene = [
            {
                "objectId": "Fridge|1",
                "objectType": "Fridge",
                "distance": 1.0,
                "isOpen": False,
            }
        ]
        runner = TaskRunner(
            RuleBasedPlanner(), FakeSimulator(objects=scene), memory_agent=agent
        )
        result = runner.run(SingleTask(goal="find", object="fridge"))

        assert result.succeeded
        assert result.observation_memories == []

    def test_failed_execution_creates_failure_memory_with_real_cause(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        sim = FakeSimulator(objects=_fridge_scene(), fail_actions={"navigate"})
        runner = TaskRunner(RuleBasedPlanner(), sim, memory_agent=agent)
        result = runner.run(SingleTask(goal="find", object="fridge"))

        assert result.execution_record.status == ExecutionStatus.FAILED
        assert result.failure_memory is not None
        assert result.failure_memory.memory_type == MemoryType.FAILURE
        assert result.failure_memory.metadata["cause"] is not None
        assert result.episodic_memory is None

    def test_failure_cause_is_unknown_when_no_step_error_exists(self, tmp_path):
        # A plan with zero steps never reaches ExecutionController with a
        # failing step -- exercised via a goal this planner cannot
        # produce steps for, which fails at the *planning* stage
        # instead, verifying "unknown" (never fabricated) cause there.
        agent = MemoryAgent.from_config(_config(tmp_path))
        runner = TaskRunner(
            RuleBasedPlanner(), FakeSimulator(objects=[]), memory_agent=agent
        )
        result = runner.run(SingleTask(goal="store"))  # missing required object/target

        assert result.execution_record is None
        assert result.failure_memory is not None
        assert result.failure_memory.metadata["cause"] is None


class TestMemoryOptionalAndSafe:
    def test_memory_disabled_still_completes_the_task(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        result = runner.run(SingleTask(goal="find", object="mug"), memory_enabled=False)

        assert result.succeeded
        assert result.memory_context is None
        assert result.episodic_memory is None
        assert result.observation_memories == []

    def test_no_memory_agent_at_all_still_completes_the_task(self):
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=None,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))
        assert result.succeeded

    def test_unavailable_memory_agent_degrades_to_normal_planning(self, tmp_path):
        blocking = tmp_path / "blocking"
        blocking.write_text("x")
        agent = MemoryAgent.from_config(
            MemoryConfig(
                enabled=True,
                database_path=blocking / "memory.db",
                vector_store_path=tmp_path / "vs",
            )
        )
        assert agent.is_available() is False
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))
        assert result.succeeded

    def test_empty_memory_database_still_plans_and_executes(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))
        assert result.memory_context.is_empty
        assert result.succeeded

    def test_retrieval_exception_does_not_prevent_task_completion(
        self, tmp_path, monkeypatch
    ):
        agent = MemoryAgent.from_config(_config(tmp_path))
        monkeypatch.setattr(
            agent.engine,
            "retrieve",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))
        assert result.memory_context.is_empty
        assert result.succeeded

    def test_malformed_stored_memory_does_not_break_retrieval(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        agent.remember_observation(
            "mug",
            "located_on",
            "table",
            provenance=MemoryProvenance.OBSERVATION,
        )
        # Corrupt the row directly -- simulates a malformed on-disk record.
        conn = sqlite3.connect(str(agent.engine.manager._store._database_path))  # type: ignore[attr-defined]
        conn.execute("UPDATE memories SET metadata = 'not valid json'")
        conn.commit()
        conn.close()

        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))
        # Corrupted record is skipped (per RetrievalEngine's own
        # "memory and structured store drifted -- skip" policy), never
        # crashes the run.
        assert result.succeeded


class TestPersistenceAcrossRestart:
    def test_memory_survives_reconstructing_every_memory_component(self, tmp_path):
        config = _config(tmp_path)
        agent = MemoryAgent.from_config(config)
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        runner.run(SingleTask(goal="find", object="mug"))
        del agent, runner

        restarted_agent = MemoryAgent.from_config(config)
        restarted_runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=restarted_agent,
        )
        result = restarted_runner.run(SingleTask(goal="find", object="mug"))
        assert not result.memory_context.is_empty
        assert "table" in [s.target for s in result.planning_result.plan.steps]


class TestGoldenMemoryTest:
    """Phase 6.3 spec section 22 -- the full four-run causal loop."""

    def test_golden_memory_loop(self, tmp_path):
        config = _config(tmp_path)
        scene = _mug_table_scene

        # -- Run 1: find the mug, no prior memory -----------------------
        agent1 = MemoryAgent.from_config(config)
        runner1 = TaskRunner(
            RuleBasedPlanner(), FakeSimulator(objects=scene()), memory_agent=agent1
        )
        run1 = runner1.run(SingleTask(goal="find", object="mug"))

        assert run1.succeeded
        assert run1.memory_context.is_empty  # nothing to retrieve yet
        assert run1.episodic_memory is not None
        assert len(run1.observation_memories) == 1
        del agent1, runner1

        # -- Restart: fresh MemoryAgent/RetrievalEngine/store instances --
        agent2 = MemoryAgent.from_config(config)

        # -- Run 2: find the mug again -- memory should now be retrieved
        #    and change the plan --------------------------------------
        runner2 = TaskRunner(
            RuleBasedPlanner(), FakeSimulator(objects=scene()), memory_agent=agent2
        )
        run2 = runner2.run(SingleTask(goal="find", object="mug"))

        assert not run2.memory_context.is_empty
        targets2 = [s.target for s in run2.planning_result.plan.steps]
        assert targets2[0] == "table"  # plan prioritizes the remembered location
        assert run2.succeeded
        del runner2

        # -- Run 3: controlled obstacle -- reaching the fridge fails ----
        fridge_task = SingleTask(goal="find", object="fridge", task_id="fridge-task")
        blocked_sim = FakeSimulator(objects=_fridge_scene(), fail_actions={"navigate"})
        runner3 = TaskRunner(RuleBasedPlanner(), blocked_sim, memory_agent=agent2)
        run3 = runner3.run(fridge_task)

        assert run3.execution_record.status == ExecutionStatus.FAILED
        assert run3.failure_memory is not None
        assert run3.failure_memory.metadata["cause"]
        del runner3

        # -- Restart again, obstacle removed, retry the same task -------
        agent3 = MemoryAgent.from_config(config)
        clear_sim = FakeSimulator(objects=_fridge_scene())
        runner4 = TaskRunner(RuleBasedPlanner(), clear_sim, memory_agent=agent3)
        run4 = runner4.run(fridge_task)  # same task_id as run 3

        assert run4.succeeded
        assert run4.episodic_memory is not None
        assert run4.episodic_memory.metadata.get("recovered_from") == [
            run3.failure_memory.memory_id
        ]
        relinked_failure = agent3.engine.manager.get(run3.failure_memory.memory_id)
        assert (
            relinked_failure.metadata.get("recovered_by")
            == run4.episodic_memory.memory_id
        )


class TestPerformanceBaseline:
    def test_latencies_are_recorded_and_non_negative(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=agent,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))

        for key in (
            "memory_retrieval_ms",
            "planning_ms",
            "execution_ms",
            "memory_write_ms",
        ):
            assert key in result.latencies_ms
            assert result.latencies_ms[key] >= 0.0

    def test_planning_latency_without_memory_is_also_recorded(self, tmp_path):
        runner = TaskRunner(
            RuleBasedPlanner(),
            FakeSimulator(objects=_mug_table_scene()),
            memory_agent=None,
        )
        result = runner.run(SingleTask(goal="find", object="mug"))
        assert "memory_retrieval_ms" not in result.latencies_ms
        assert result.latencies_ms["planning_ms"] >= 0.0
