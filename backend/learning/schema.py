"""
schema.py (backend/learning)

The versioned schema of the episode log -- the data flywheel every learned
model trains from. Bump `SCHEMA_VERSION` on any column change; the logger
refuses to append to a database of a different version.

One row per *step attempt* in `steps`, one row per mission in `episodes`.
Feature snapshots are the numeric/categorical world facts about the step's
target taken from simulator metadata immediately before and after the step
(see `features.world_features`).
"""

from __future__ import annotations

SCHEMA_VERSION = 1

#: Labels for why a step failed. Derived from the executor's error code and
#: message; "none" for a step that succeeded.
FAILURE_TYPES = (
    "none",
    "blocked",
    "not_visible",
    "not_reachable",
    "wrong_object",
    "timeout",
    "other",
)

EPISODE_COLUMNS = [
    ("episode_id", "TEXT PRIMARY KEY"),
    ("scene_id", "TEXT NOT NULL"),
    ("seed", "INTEGER"),
    ("task_text", "TEXT"),
    ("parsed_task", "TEXT"),  # JSON
    ("task_kind", "TEXT"),
    ("planner", "TEXT"),
    ("injected_fault", "TEXT"),  # "none" or the fault kind (generator only)
    ("outcome", "TEXT"),  # succeeded | failed | cancelled
    ("replans", "INTEGER"),
    ("retries", "INTEGER"),
    ("total_steps", "INTEGER"),
    ("duration_ms", "REAL"),
    ("created_at", "REAL"),
]

STEP_COLUMNS = [
    ("episode_id", "TEXT NOT NULL"),
    ("attempt", "INTEGER NOT NULL"),  # 0 = first execution of a plan
    ("step_index", "INTEGER NOT NULL"),
    ("remaining_steps", "INTEGER"),
    ("action", "TEXT NOT NULL"),
    ("target", "TEXT"),
    ("before", "TEXT"),  # JSON world_features before the step
    ("after", "TEXT"),  # JSON world_features after the step
    ("retries_so_far", "INTEGER"),
    ("replans_so_far", "INTEGER"),
    ("memory_hits", "INTEGER"),
    ("memory_sim_max", "REAL"),
    ("memory_sim_mean", "REAL"),
    ("memory_prior_success", "REAL"),  # share of hit memories that were successes
    ("perception_conf", "REAL"),
    ("status", "TEXT"),  # completed | failed | blocked | skipped | cancelled
    ("success", "INTEGER"),  # 1 / 0 (skipped/cancelled steps are not labelled)
    ("error_code", "TEXT"),
    ("failure_type", "TEXT"),
    ("duration_ms", "REAL"),
    ("verdict", "TEXT"),  # reflection verdict for the attempt this step was in
    ("model_decisions", "TEXT"),  # JSON list, later phases
]


def create_sql() -> str:
    def cols(spec):
        return ",\n    ".join(f"{name} {typ}" for name, typ in spec)

    return f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS episodes (
    {cols(EPISODE_COLUMNS)}
);
CREATE TABLE IF NOT EXISTS steps (
    {cols(STEP_COLUMNS)}
);
CREATE INDEX IF NOT EXISTS idx_steps_episode ON steps(episode_id);
CREATE INDEX IF NOT EXISTS idx_episodes_scene ON episodes(scene_id);
"""
