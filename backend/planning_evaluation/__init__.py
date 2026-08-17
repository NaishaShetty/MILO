"""
planning_evaluation (backend/planning_evaluation)

Purpose
-------
Phase E: the `milo_benchmark` dataset (`dataset/v1.0/tasks.json`) and
the runner that scores this project's planners against it
(`run_benchmark.py`), plus a memory-conditioned vs memory-off
companion (`run_memory_ablation.py`). Lives under `backend/`, not
`benchmarks/planning/`, for the same reason the language and
perception benchmarks do (see `benchmarks/README.md`'s "implemented
elsewhere" sections): it imports `simulator.simulator.Simulator`,
`planner.rule_based`/`planner.behavior_tree`, `orchestration.
task_runner.TaskRunner`, and `memory.agent.MemoryAgent` directly, so
keeping it here avoids a cross-tree import and a second,
disconnected copy of the same scoring logic. `benchmarks/planning/`
holds only a pointer `README.md`, matching the existing precedent.

Relationship to `memory_evaluation/`
-------------------------------------
Reuses `memory_evaluation.experiment_real`'s live-metadata-seeding
helper and `memory_evaluation.run_floorplan_sweep`'s scene/task
authoring discipline (every object/target name confirmed against a
live `get_metadata()` scan before being written into the dataset --
see `dataset/v1.0/tasks.json`'s own `generated_by` field). Kept as a
separate package rather than added to `memory_evaluation/` because
this one is a *published, versioned dataset* meant to be consumed by
other agents/planners, not an internal ablation study -- see
`dataset/v1.0/README.md`'s Hugging Face dataset card for the
publishing contract that distinction implies (stable task IDs, a
frozen v1.0, semver-style extension going forward).
"""
