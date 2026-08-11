# MILO — Known Limitations

Honest, specific boundaries — written so nobody (including a future
contributor) mistakes a deliberate scope limit for a bug, or claims a
capability that isn't real.

## Simulation only

MILO runs against AI2-THOR, a simulated environment. There is no
physical robot, and no ROS/hardware integration. `Simulator`
(`backend/simulator/simulator.py`) is written as the sole seam a future
physical-robot backend (or a different simulator) would need to replace
— but that replacement does not exist today.

## Simulator is off by default and single-instance

`VISION_ENABLE_SIMULATOR=false` by default — most of the API (`/tasks`,
`/execution`, `/agents`, `/vision/perceive`, the new `/tasks/{id}/robot`)
503s until it's explicitly enabled with a working AI2-THOR/Unity install.
Only one `Simulator` exists per backend process, and only one task can
run at a time (`_TaskStore` returns 409 on a second concurrent
`POST /tasks`) — there is no multi-robot or multi-task concurrency.

## Navigation is teleport-based, not path planning

`AI2ThorEnv.navigate_to()` uses AI2-THOR's `GetInteractablePoses` +
`TeleportFull` to jump to a valid interactable pose near the target
object — it does not compute or execute a walked path through the
environment. This is a documented scope decision (see
`backend/simulator/ai2thor_env.py`'s docstring and
`docs/phases/phase5_execution.md`), not a bug.

## No push/streaming transport

Every "live" UI update in this project — task status, agent status,
plan progress, robot state, activity feed — is polling-based
(`usePolling.ts`), not WebSocket/SSE. There is no backend infrastructure
for either. This is a deliberate choice (see that hook's own docstring)
rather than a missing feature; adding a push transport would be
disproportionate to what today's usage needs.

## Events are in-memory, not persisted

The structured event log (`backend/agents/events.py`) that backs the
Activity page and Mission Control's activity feed lives in process
memory only — a backend restart discards all history. `TaskState`
history is similarly process-local.

## `MiloState`'s `perceiving`/`navigating` are unreachable

The canonical `MiloState` type (`frontend/src/state/miloState.ts`)
defines 15 logical states, but only 13 are ever actually produced by
`MiloStateContext` — `perceiving` and `navigating` have no backend
`TaskStatus` value that maps to them today. They exist as
forward-compatible entries in the type and asset-mapping tables, not as
reachable UI states. This is called out rather than silently worked
around: adding a real producer for either would require a backend
`TaskStatus` change, out of Phase 8.6's scope (see
`docs/architecture/demo_and_visualization.md`).

## Language understanding requires a real LLM provider

Instruction parsing (`LanguageAgent`) calls a real LLM (OpenAI, Gemini,
or a local Qwen-compatible server) — there is no offline/rule-based
fallback for natural language understanding. Without a configured
provider/API key, task creation fails at the parse step.

## No experiment/benchmark results are fabricated

MILO Lab's "Recent Experiments"/"Lab Stats" only ever show real,
persisted results from actually-run benchmarks — when nothing has run,
it says so (`"No experiments have been run yet."`, `"unavailable"` for
an unmeasured success rate), never a placeholder number. There is
currently no published, formal benchmark suite result set — running one
is future work, not part of this phase.

## Multi-step (`MultiTask`) instructions are unsupported by the live task API

`POST /api/v1/tasks` rejects (422) any instruction that parses to a
`MultiTask` — the orchestrator only runs single-goal instructions today.
