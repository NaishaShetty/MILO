"""
task_ablation.py (backend/memory_evaluation)

Purpose
-------
Section 13 of the Phase 6.4 spec, at task level: reuses the exact four
`RankingWeights` configs `memory_evaluation.ablation` already defines
for Phase 6.2's retrieval-only evaluation (`run_evaluation.py`), and
runs it against two benchmark scenarios once per config to see whether
ranking-formula choice actually changes planner behavior/task outcome
-- not just Recall@K/MRR in isolation:

- Category A (`A_object_recall_mug`) has exactly one qualifying
  location-hint memory -- a control case with nothing for the ranking
  formula to differentiate between.
- Category E (`E_conflicting_memory_mug`) seeds two competing,
  conflicting memories for the same object -- the case where ranking
  formula choice could plausibly change *which* memory the planner
  acts on, and therefore whether the task succeeds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from memory_evaluation.ablation import ABLATION_CONFIGS
from memory_evaluation.experiment import EpisodeResult, run_scenario
from memory_evaluation.scenarios import (
    CATEGORY_A_OBJECT_RECALL,
    CATEGORY_E_CONFLICTING_MEMORY,
)

_SCENARIOS = {
    "A_object_recall": CATEGORY_A_OBJECT_RECALL,
    "E_conflicting_memory": CATEGORY_E_CONFLICTING_MEMORY,
}


def run_task_level_ablation(
    database_dir: Path,
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Runs every scenario in `_SCENARIOS` under `memory_on` once per
    ranking-weights config; returns
    `{scenario_key: {config_name: [episode_dict, ...]}}`."""
    report: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for scenario_key, scenario in _SCENARIOS.items():
        by_config: Dict[str, List[Dict[str, Any]]] = {}
        for config_name, weights in ABLATION_CONFIGS.items():
            episodes: List[EpisodeResult] = run_scenario(
                scenario,
                "memory_on",
                database_dir / scenario_key / config_name,
                weights=weights,
            )
            by_config[config_name] = [ep.to_dict() for ep in episodes]
        report[scenario_key] = by_config
    return report
