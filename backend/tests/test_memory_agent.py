"""
test_memory_agent.py

Purpose
-------
Unit tests for `memory.agent.MemoryAgent`/`MemoryQueryContext`/
`PlannerMemoryContext` -- Phase 6.3 spec section 21's "Unit tests:
Memory Agent... task memory context... graceful fallback."
"""

from __future__ import annotations

from pathlib import Path

from memory.agent import MemoryAgent, MemoryQueryContext, PlannerMemoryContext
from memory.config import MemoryConfig
from memory.models import MemoryProvenance, MemoryStatus, MemoryType
from memory.semantics import EpisodicDetails, FailureDetails


def _config(tmp_path: Path) -> MemoryConfig:
    return MemoryConfig(
        enabled=True,
        database_path=tmp_path / "memory.db",
        vector_store_path=tmp_path / "vector_store",
    )


class TestMemoryQueryContext:
    def test_to_query_text_joins_populated_fields_in_fixed_order(self):
        context = MemoryQueryContext(
            goal="find", object="mug", target="table", location="kitchen"
        )
        assert context.to_query_text() == "find mug table kitchen"

    def test_to_query_text_skips_unset_fields(self):
        context = MemoryQueryContext(object="mug")
        assert context.to_query_text() == "mug"

    def test_to_query_text_includes_observations(self):
        context = MemoryQueryContext(object="mug", observations=["seen on counter"])
        assert context.to_query_text() == "mug seen on counter"

    def test_empty_context_yields_empty_query(self):
        assert MemoryQueryContext().to_query_text() == ""


class TestPlannerMemoryContextSummary:
    def test_is_empty_true_for_no_results(self):
        assert PlannerMemoryContext(query="x").is_empty is True

    def test_summary_never_includes_raw_memory_content(self):
        from memory.retrieval import MemoryResult
        from memory.semantics import build_semantic_memory

        memory = build_semantic_memory(
            "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
        )
        result = MemoryResult(
            memory=memory,
            similarity=0.9,
            final_score=0.9,
            ranking_components={},
            retrieval_metadata={},
        )
        summary = PlannerMemoryContext(query="mug", results=[result]).summary()
        assert summary["query"] == "mug"
        assert summary["count"] == 1
        assert summary["memory_ids"] == [memory.memory_id]
        assert "content" not in summary
        assert "metadata" not in summary


class TestFromConfig:
    def test_from_config_produces_available_agent(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        assert agent.is_available() is True

    def test_from_config_degrades_gracefully_on_construction_failure(self, tmp_path):
        # Point the database at a path whose parent is a file, not a
        # directory -- SQLiteMemoryStore's own init fails loudly, but
        # MemoryAgent.from_config() must not propagate that.
        blocking_file = tmp_path / "blocking"
        blocking_file.write_text("not a directory")
        config = MemoryConfig(
            enabled=True,
            database_path=blocking_file / "memory.db",
            vector_store_path=tmp_path / "vector_store",
        )
        agent = MemoryAgent.from_config(config)
        assert agent.is_available() is False


class TestRetrieveRelevantMemories:
    def test_retrieves_stored_memories_matching_the_query(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        agent.remember_observation(
            "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
        )
        context = agent.retrieve_relevant_memories(MemoryQueryContext(object="mug"))
        assert not context.is_empty
        assert context.query == "mug"
        assert context.results[0].memory.metadata["object"] == "table"

    def test_empty_database_returns_empty_context(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        context = agent.retrieve_relevant_memories(MemoryQueryContext(object="mug"))
        assert context.is_empty

    def test_empty_query_text_short_circuits_to_empty_context(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        agent.remember_observation(
            "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
        )
        context = agent.retrieve_relevant_memories(MemoryQueryContext())
        assert context.is_empty

    def test_unavailable_agent_returns_empty_context(self):
        agent = MemoryAgent(engine=None)
        context = agent.retrieve_relevant_memories(MemoryQueryContext(object="mug"))
        assert context.is_empty

    def test_retrieval_exception_is_caught_and_returns_empty_context(
        self, tmp_path, monkeypatch
    ):
        agent = MemoryAgent.from_config(_config(tmp_path))
        agent.remember_observation(
            "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("vector store unavailable")

        monkeypatch.setattr(agent.engine, "retrieve", _boom)
        context = agent.retrieve_relevant_memories(MemoryQueryContext(object="mug"))
        assert context.is_empty

    def test_memory_type_filter_is_forwarded(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        agent.remember_observation(
            "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
        )
        agent.remember_episode(
            EpisodicDetails(task_summary="bring mug", outcome="success"),
            episode_id="ep-1",
        )
        context = agent.retrieve_relevant_memories(
            MemoryQueryContext(object="mug"), memory_types=[MemoryType.EPISODIC]
        )
        assert all(r.memory.memory_type == MemoryType.EPISODIC for r in context.results)


class TestRememberEpisode:
    def test_stores_and_returns_episodic_memory(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        memory = agent.remember_episode(
            EpisodicDetails(task_summary="bring mug", outcome="success"),
            episode_id="ep-1",
            task_id="task-1",
        )
        assert memory is not None
        assert memory.memory_type == MemoryType.EPISODIC
        assert memory.episode_id == "ep-1"
        assert memory.task_id == "task-1"
        assert agent.engine.manager.get(memory.memory_id) is not None

    def test_unavailable_agent_returns_none_without_raising(self):
        agent = MemoryAgent(engine=None)
        memory = agent.remember_episode(
            EpisodicDetails(task_summary="x", outcome="success"), episode_id="ep-1"
        )
        assert memory is None

    def test_write_failure_returns_none_without_raising(self, tmp_path, monkeypatch):
        agent = MemoryAgent.from_config(_config(tmp_path))
        monkeypatch.setattr(
            agent.engine,
            "store_and_index",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")),
        )
        memory = agent.remember_episode(
            EpisodicDetails(task_summary="x", outcome="success"), episode_id="ep-1"
        )
        assert memory is None

    def test_recovered_failure_ids_link_both_directions(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        failure = agent.remember_failure(
            FailureDetails(
                task="reach fridge", action="navigate", failure_reason="blocked"
            ),
            episode_id="ep-fail",
        )
        episode = agent.remember_episode(
            EpisodicDetails(task_summary="reach fridge", outcome="success"),
            episode_id="ep-success",
            recovered_failure_ids=[failure.memory_id],
        )
        assert episode.metadata["recovered_from"] == [failure.memory_id]
        refetched_failure = agent.engine.manager.get(failure.memory_id)
        assert refetched_failure.metadata["recovered_by"] == episode.memory_id


class TestRememberFailure:
    def test_stores_failure_with_evidence_based_cause(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        memory = agent.remember_failure(
            FailureDetails(
                task="reach fridge",
                action="navigate",
                failure_reason="blocked by chair",
                cause="chair in path",
            ),
            episode_id="ep-1",
        )
        assert memory.metadata["cause"] == "chair in path"

    def test_unknown_cause_is_never_fabricated(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        memory = agent.remember_failure(
            FailureDetails(
                task="reach fridge", action="navigate", failure_reason="failed"
            ),
            episode_id="ep-1",
        )
        assert memory.metadata["cause"] is None
        assert "unknown" in memory.content.lower() or "Cause:" not in memory.content


class TestRememberObservation:
    def test_stores_semantic_memory(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        memory = agent.remember_observation(
            "mug",
            "located_on",
            "table",
            provenance=MemoryProvenance.OBSERVATION,
            confidence=0.9,
        )
        assert memory.memory_type == MemoryType.SEMANTIC
        assert memory.status == MemoryStatus.ACTIVE

    def test_conflicting_observation_tags_relationship_not_overwrite(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        first = agent.remember_observation(
            "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
        )
        second = agent.remember_observation(
            "mug", "located_on", "cabinet", provenance=MemoryProvenance.OBSERVATION
        )
        assert agent.engine.manager.get(first.memory_id) is not None
        assert {
            "memory_id": first.memory_id,
            "relation": "conflicts_with",
        } in second.metadata["related_memories"]

    def test_unavailable_agent_returns_none(self):
        agent = MemoryAgent(engine=None)
        assert (
            agent.remember_observation(
                "mug", "located_on", "table", provenance=MemoryProvenance.OBSERVATION
            )
            is None
        )


class TestLinkRecovery:
    def test_unavailable_agent_is_a_safe_no_op(self):
        agent = MemoryAgent(engine=None)
        agent.link_recovery("does-not-exist", ["also-does-not-exist"])  # must not raise

    def test_missing_ids_are_handled_without_raising(self, tmp_path):
        agent = MemoryAgent.from_config(_config(tmp_path))
        agent.link_recovery("does-not-exist", ["also-does-not-exist"])  # must not raise
