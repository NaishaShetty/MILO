"""
orchestration (backend/orchestration)

Purpose
-------
Phase 6.3's integration glue: the one package in this repository
allowed to depend on both `backend/planner/`+`backend/execution/` (the
robot's "do the task" pipeline) AND `backend/memory/` (the "remember
the experience" subsystem) -- `TaskRunner` (`task_runner.py`) is the
closed causal loop the phase spec's core principle asks for:

```
Task -> retrieve memory -> plan (memory-conditioned) -> execute
     -> capture experience -> persist memory -> (future task) -> retrieve
```

Why this loop lives here, not inside `planner/`, `execution/`, or
`memory/`
------------------------------------------------------------------------
Each of those three packages is independently useful and independently
tested without this one: `backend/planner/` never imports
`backend/execution/`; `backend/execution/` never writes to a database
itself (`execution/controller.py`'s own docstring); `backend/memory/`
knows nothing about `ExecutionRecord`/`Plan` (`memory/agent.py`'s own
docstring). `TaskRunner` is where those three meet -- translating an
`ExecutionRecord` into `memory.semantics.EpisodicDetails`/
`FailureDetails`, building a `memory.agent.MemoryQueryContext` from a
`SingleTask`, and deciding *when* an observation is worth remembering
(section 12/13's "controlled pathway," never every frame). None of
that translation logic belongs inside any of the three packages it
translates between, per each one's own "do not redesign unless a
concrete integration defect requires it" boundary.

No new task/episode/execution model
------------------------------------------
`TaskRunner` reuses `schemas.task.SingleTask`, `planner.models.Plan`/
`PlanningResult`, and `execution.models.ExecutionRecord` exactly as
Phase 3/4/5 left them -- `episode_id` is a plain string this module
mints once per `run()` call and threads through `MemoryQueryContext`,
`MemoryAgent.remember_episode()`/`remember_failure()`, and `Memory.
episode_id`, matching the identifier Phase 6.1 already anticipated
(`ExecutionRecord.execution_id` for a live execution; `TaskRunner`'s
own `episode_id` for the memory-facing identifier, since a task can
fail during planning, before an `ExecutionRecord` ever exists).
"""
