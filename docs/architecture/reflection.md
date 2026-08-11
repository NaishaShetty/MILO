# Reflection Architecture

Documents `ReflectionAgent` (`backend/agents/reflection_agent.py`) and
how `Orchestrator` uses it to close the retrieve → plan → execute →
reflect → remember loop. Did not exist as a dedicated doc before Phase
8.5's final pass. Written directly from the real implementation and
its own extensive module docstring — not the roadmap's description.

## What reflection is, and deliberately is not

`ReflectionAgent` is **deterministic and rule-based, not a second
planner**. Its own module docstring states this explicitly (quoting
the project's Phase 7.11 requirement): *"Reflection should not become
a second uncontrolled planner. The Planner remains responsible for
generating plans."* Every rule below inspects data (an `ExecutionRecord`
plus classified `AgentFailure`s) and returns a verdict — none of them
constructs a `Plan` or a `PlanStep`.

## When reflection happens

`Orchestrator._run_attempt()` (`orchestration/orchestrator.py`) calls
`ReflectionAgent.reflect(record, failures, attempt, max_attempts)`
immediately after one execution attempt finishes — every attempt,
success or failure, not only on failure. `TaskState.status` is set to
`reflecting` for the duration (mapped to `MiloState: "reflecting"` —
see `docs/architecture/milo_state_system.md`), and the elapsed time is
recorded in `task_state.latencies_ms["reflection_ms"]`.

## What it receives

- The finished `ExecutionRecord` (`execution/models.py`) — real
  per-step results from `ExecutionController`.
- A list of `AgentFailure`s, translated from that record by
  `ExecutionAgentWrapper.failures_from_record()`, optionally refined by
  `NavigationAgent.diagnose()` — both computed by `Orchestrator` itself;
  `ReflectionAgent` never imports another agent's module (this
  project's "no agent imports another agent's module" rule).
- The current attempt number and `max_attempts` (from
  `Orchestrator`'s `max_replans` bound).

## The seven rules (verbatim from the real implementation)

1. `record.status == SUCCESS` → **`continue`**, `store_memory=True`.
2. No failure was recorded at all → **`abort`** (never invents a cause).
3. `INVALID_ACTION`/`INVALID_PLAN` → **`abort`** unconditionally — the
   plan itself is malformed; replanning from the same task description
   would reproduce it.
4. Attempts exhausted (`attempt >= max_attempts`) → **`abort`**.
5. `PATH_BLOCKED`/`NAVIGATION_FAILURE`/`OBJECT_NOT_FOUND`/
   `ENVIRONMENT_CHANGED` → **`replan`** — a different plan (route,
   target resolution) could plausibly resolve these; retrying the
   identical plan would not.
6. Any other `recoverable=True` failure → **`retry`** — the same plan,
   re-attempted (e.g. a flaky dispatch).
7. Otherwise → **`abort`**.

`store_memory` is `True` only for the two *terminal* outcomes
(`continue`, `abort`) — `retry`/`replan` are mid-loop and never trigger
a memory write, matching this project's "avoid memory pollution"
policy: exactly one memory per task, once it actually terminates, never
one per attempt.

## Memory updates on terminal outcome

`Orchestrator._remember_terminal()` writes exactly one memory when a
task actually ends:

| Outcome | `MemoryType` written | Real fields |
|---|---|---|
| Success (`continue` verdict, task terminates successfully) | `EPISODIC` | `task_summary` (the task's goal), `outcome: "success"`, `location` (from the real final `WorldState`), `relevant_objects` (the task's real `object`/`target`) |
| Failure (`abort` verdict, or replans exhausted) | `FAILURE` | `task`, `action` (the specific failing step's action), `failure_reason`/`cause` (the real `ExecutionError.message`), `error_code`, `outcome: "failed"` |

Both go through `MemoryAgentWrapper.remember_episode()`/
`remember_failure()` (never a raw SQL insert from the orchestrator
itself). The written memory's id/type is appended to
`task_state.created_memories` and an `EventType.MEMORY_UPDATED` event
is published — both real, observable outputs (`GET /api/v1/tasks/{id}`,
`GET /api/v1/tasks/{id}/events`).

**Verified live** (Stage 3 of Phase 8.5): a real "Bring me the apple"
task that succeeded via real AI2-THOR execution produced exactly one
`created_memories` entry — confirming this path runs for real, not
only in unit tests.

## `SEMANTIC` and `USER` memory types

`MemoryType` (`backend/memory/models.py`) also defines `SEMANTIC` and
`USER` — these exist in the schema and are used by `backend/memory/`'s
retrieval/ranking machinery (see `docs/phases/phase6_memory.md`), but
`Orchestrator`'s reflection loop itself only ever *writes*
`EPISODIC`/`FAILURE` memories on task completion. `SEMANTIC`/`USER`
memories, if populated, come from a different write path (not part of
the reflection loop this document covers) — do not assume the
orchestrator writes them; it doesn't.

## How future tasks benefit

Memory written here is read back by `Orchestrator`'s earlier
`retrieving_memory` step (before planning) via the same `MemoryAgentWrapper`
— a failure memory from a past task can surface as retrieved context
for a similar future instruction, letting the planner/LLM avoid a
previously-failed approach. This is the real "learning loop": write on
reflection, read on retrieval — no separate training or model-update
step exists or is claimed.
