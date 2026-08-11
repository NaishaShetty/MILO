# Planning Architecture

Documents the actual planner implementation (`backend/planner/`) and
its relationship to task parsing, execution, MILO state, and AI2-THOR.
Did not exist before Phase 8.5's final pass (a confirmed gap) — written
directly from the real source, not from the roadmap's aspirational
description.

## Real planner strategies (all three genuinely exist)

`backend/planner/factory.py`'s `PlannerType` registers exactly three
concrete `Planner` implementations — no more, no fewer:

| `PlannerType` | Class | File |
|---|---|---|
| `rule_based` | `RuleBasedPlanner` | `planner/rule_based.py` |
| `react` | `ReActPlanner` | `planner/react.py` |
| `behavior_tree` | `BehaviorTreePlanner` | `planner/behavior_tree.py` |

`create_planner(planner_type, ...)` is the single selection point —
callers (`api/routes/planner.py`, `Orchestrator`) never import a
concrete planner class directly, so adding a fourth strategy later is
a one-line registration in `_REGISTRY`, not a multi-file change. This
verified live: `POST /api/v1/tasks` (which builds its planner via
`build_orchestrator`) produced a real `Plan` with
`"planner_type": "rule_based"` during Stage 3's live AI2-THOR
validation (see the Phase 8.5 completion report).

`ReActPlanner` accepts an `LLMClient` and an optional
`fallback_to_rule_based` (default `True`) — if the LLM-driven ReAct
loop can't produce a valid plan, it falls back to `RuleBasedPlanner`
rather than failing the task outright; this fallback is planner-internal
and unrelated to the LLM *provider* fallback question (§13 of the
Stage 2 spec) — it never silently switches providers, only plan
*generation strategy*.

## Planner input/output contract

Every strategy implements the same abstract `Planner.plan()`
(`planner/planner.py`):

```
Planner.plan(task: SingleTask, world_state: WorldState, memory_context: ...) -> PlanningResult
Planner.replan(task, world_state, memory_context) -> PlanningResult
```

- **Input**: a validated `SingleTask` (from Language Understanding —
  `backend/language/`, never a raw string), a `WorldState`
  (`planner/state.py`, a symbolic representation, not a live AI2-THOR
  frame), and retrieved memory context.
- **Output**: a `PlanningResult` (`planner/models.py`) wrapping a
  `Plan` — an ordered sequence of `PlanStep`s (`action`, `target`,
  `parameters`, `description`, `preconditions`, `postconditions`,
  `status`). `Plan.strategy` records which of the three planner types
  actually produced it. Planning never calls AI2-THOR or dispatches a
  simulator action — that is `execution.controller.ExecutionController`'s
  job, entirely separate from this package.

`PlanValidator` (`planner/validator.py`) checks a `Plan`'s internal
consistency (precondition/postcondition ordering, target references)
independent of which strategy produced it — every concrete planner is
constructed with a `PlanValidator` and validates its own output before
returning.

## Replanning

`Orchestrator` (`backend/orchestration/orchestrator.py`), not the
planner itself, decides *when* to replan — see the Reflection doc for
the exact rule. When it does, it calls the same planner instance's
`replan(task, world_state, memory_context)`, bounded by
`max_replans` (default `DEFAULT_MAX_REPLANS`, `orchestrator.py`). Each
replan attempt is a fresh planning call against the *current*
`WorldState` (which reflects what execution has already learned/failed
at), not a blind retry of the identical plan.

## Relationship to MILO state

The orchestrator's real `TaskStatus` values map directly to
`MiloState` (see `docs/architecture/milo_state_system.md`):
`planning → planning`, `replanning → replanning`. These are not
UI-invented labels — they are the literal `TaskStatus` enum members
(`backend/agents/task_state.py`) the orchestrator sets while a
`Planner.plan()`/`replan()` call is in flight.

## Relationship to AI2-THOR

Planning is deliberately simulator-agnostic — no planner class imports
`ai2thor` or `simulator.simulator`. A `Plan`'s steps are abstract
(`action: "navigate"`, `target: "apple"`), and it is
`ExecutionController` that translates each step into real AI2-THOR API
calls. This separation was verified live in Stage 3: the same
`rule_based`-produced plan (`locate → navigate → pickup`) executed
against a real running AI2-THOR simulator with zero planner-side
awareness of AI2-THOR's existence.

## Planner comparison endpoint

`POST /api/v1/planner/evaluate` (see `docs/architecture/api_contracts.md`
§8) runs every requested strategy against the same task and reports
measured (not fabricated) success/validity/latency/step-count metrics
— this is real, existing infrastructure for comparing the three
strategies above, not a planned/future capability.
