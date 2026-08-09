"""
pollution.py (backend/memory_evaluation)

Purpose
-------
Section 17 of the Phase 6.4 spec: verify the semantic-memory formation
policy (`orchestration.task_runner.TaskRunner._form_observation()`)
does not store every observation -- i.e. that memory growth is
controlled, not a per-frame/per-task dump. Runs every benchmark
scenario's episodes once under `memory_on` (each against its own
memory subsystem, matching `experiment.run_scenario`'s existing
isolation) and compares the number of successful, object-naming
episodes -- an upper bound on how many observations *could* have been
formed -- against how many `SEMANTIC`/`EPISODIC`/`FAILURE` memories
were actually persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from memory.models import MemoryType
from memory_evaluation.experiment import _build_memory_agent, run_scenario
from memory_evaluation.scenarios import ALL_SCENARIOS


@dataclass
class PollutionReport:
    total_episodes: int
    successful_episodes_naming_an_object: int
    semantic_memories_created: int
    episodic_memories_created: int
    failure_memories_created: int
    total_memories_created: int

    def to_dict(self) -> Dict[str, Any]:
        ratio = (
            round(
                self.semantic_memories_created
                / self.successful_episodes_naming_an_object,
                3,
            )
            if self.successful_episodes_naming_an_object
            else 0.0
        )
        return {
            "total_episodes": self.total_episodes,
            "successful_episodes_naming_an_object": (
                self.successful_episodes_naming_an_object
            ),
            "semantic_memories_created": self.semantic_memories_created,
            "episodic_memories_created": self.episodic_memories_created,
            "failure_memories_created": self.failure_memories_created,
            "total_memories_created": self.total_memories_created,
            "semantic_memories_per_successful_object_episode": ratio,
        }


def run_pollution_check(database_dir: Path) -> PollutionReport:
    """
    Runs every scenario's episodes once under `memory_on`, then counts
    each scenario's own final memory store -- semantic-memory growth
    should stay well below one-per-episode (per `TaskRunner`'s
    documented "at most one observation per successful run, for the
    task's primary object only" policy).
    """
    total_episodes = 0
    successful_naming_object = 0
    total_semantic = 0
    total_episodic = 0
    total_failure = 0

    for scenario in ALL_SCENARIOS:
        episode_results = run_scenario(
            scenario, "memory_on", database_dir / scenario.scenario_id
        )
        for ep in episode_results:
            total_episodes += 1
            if ep.success and ep.object:
                successful_naming_object += 1

        scenario_agent = _build_memory_agent(database_dir / scenario.scenario_id)
        assert scenario_agent.engine is not None  # see memory_size.py's own note
        memories = scenario_agent.engine.manager.list()
        total_semantic += sum(
            1 for m in memories if m.memory_type == MemoryType.SEMANTIC
        )
        total_episodic += sum(
            1 for m in memories if m.memory_type == MemoryType.EPISODIC
        )
        total_failure += sum(1 for m in memories if m.memory_type == MemoryType.FAILURE)

    return PollutionReport(
        total_episodes=total_episodes,
        successful_episodes_naming_an_object=successful_naming_object,
        semantic_memories_created=total_semantic,
        episodic_memories_created=total_episodic,
        failure_memories_created=total_failure,
        total_memories_created=total_semantic + total_episodic + total_failure,
    )
