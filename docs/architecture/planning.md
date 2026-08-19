# Planning Architecture

Documents the actual planner implementation (`backend/planner/`) and
its relationship to task parsing, execution, MILO state, and AI2-THOR.
Did not exist before Phase 8.5's final pass (a confirmed gap) — written
directly from the real source, not from the roadmap's aspirational
description.

## Real planner strategies (four, as of the HTN slice below)

`backend/planner/factory.py`'s `PlannerType` registers four concrete
`Planner` implementations:

| `PlannerType` | Class | File |
|---|---|---|
| `rule_based` | `RuleBasedPlanner` | `planner/rule_based.py` |
| `react` | `ReActPlanner` | `planner/react.py` |
| `behavior_tree` | `BehaviorTreePlanner` | `planner/behavior_tree.py` |
| `htn` | `HTNPlanner` | `planner/htn.py` |

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

## HTN planner (`htn`, `HTNPlanner`) — scoped slice 1

A fourth strategy, `HTNPlanner` (`planner/htn.py`), implementing real
Hierarchical Task Network decomposition over the same primitive
vocabulary and `WorldState` every other planner already uses — not a
general-purpose HTN research engine, and not (yet) a full replacement
for `RuleBasedPlanner`'s goal coverage. **Slice 1 scope**: the
`tier1_locate`/`tier2_pickup`/`tier3_store` goal shapes
(`find`/`search_for`/`locate`/`inspect`/`count`, `pick_up`,
`store`/`put_away`), plus `place`/`pick_and_place`/`open`/`close`
since they reuse the exact same decomposition machinery for free.
`fetch`/`deliver`/`navigate_to`/`follow`/`return_to`/the generic-goal
fallback are explicitly **not** covered in this slice — an
unsupported goal raises `UnsupportedGoalError`, same as
`RuleBasedPlanner` would for a goal it has no template for.
`tier4_multi_step` is out of scope for this slice entirely (each
sub-goal is still just a `SingleTask`, so it *would* work mechanically
via the same per-subtask harness every other planner uses — but it
has not been run or validated here, and is being deliberately left for
a later slice, not assumed to work).

### Why a real task network, not "BehaviorTreePlanner with extra steps"

`BehaviorTreePlanner` reuses `RuleBasedPlanner`'s `GOAL_HANDLERS`
directly, wrapped in BT nodes purely for visualization — by design
(see that module's docstring), it produces byte-identical plans via a
different *representation* of the same imperative logic. `HTNPlanner`
is different on purpose: it has its own task network, its own method
library, and its own recursive decomposition engine — genuinely
independent of `rule_based.py`'s Python control flow, even though (for
this shared domain) it is expected to produce equivalent plans for the
same tasks. This is what makes "does it decompose at least as reliably
as `rule_based`" a real question with a real answer, not a foregone
conclusion.

### Task types

```python
@dataclass(frozen=True)
class PrimitiveTask:
    action: str                    # one of actions.LOCATE/NAVIGATE/PICKUP/PLACE/OPEN/CLOSE
    target: Optional[str]
    parameters: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class CompoundTask:
    name: str                      # e.g. "AcquireObject", "DepositObject"
    args: Dict[str, Any] = field(default_factory=dict)
```

A `PrimitiveTask` maps 1:1 onto an existing `actions.ACTION_REGISTRY`
entry — the HTN engine never invents a new primitive action or a new
precondition/effect; it reuses the exact same `ActionSpec`s
`RuleBasedPlanner`/`BehaviorTreePlanner`/`PlanValidator` already share
(see `actions.py`'s own "single source of truth" rationale). A
`CompoundTask` names something that still needs decomposing.

### Compound tasks and their methods

Each compound task has an ordered list of candidate `Method`s. A
method has a **precondition** (checked against the current
`WorldState` and the task's `args` — this is genuine HTN method
applicability, not a plan-time simulation) and a **decomposition**
function producing the task's ordered subtasks. The engine tries
methods in order and commits to the first whose precondition holds —
this project's whole domain (single-agent, fully-observed,
deterministic) never needs backtracking across method choices, so a
simple ordered-first-match selection (no search) is the right scope,
not a missing feature.

| Compound task | Methods (in try-order) | Mirrors |
|---|---|---|
| `LocateObject(obj)` | one method: `[Locate(obj), Navigate(obj)]` | `rule_based._goal_perceive` |
| `AcquireObject(obj)` | one method: `[LocateObject(obj), PickUp(obj)]` | `rule_based._acquire` |
| `DepositObject(obj, target, use_container)` | 3 methods, see below | `rule_based._deposit` |
| `StoreObject(obj, target)` | one method: `[AcquireObject(obj), DepositObject(obj, target, use_container=True)]` | `rule_based._goal_store` |
| `PlaceObject(obj, target)` | one method: `[AcquireObject(obj), DepositObject(obj, target, use_container=False)]` | `rule_based._goal_place` |
| `OpenObject(obj)` | one method: `[LocateObject(obj), Open(obj)]` | `rule_based._goal_open` |
| `CloseObject(obj)` | one method: `[LocateObject(obj), Close(obj)]` | `rule_based._goal_close` |

`DepositObject`'s three methods are the one place this domain
genuinely needs method *choice*, and they are a direct HTN translation
of `rule_based._deposit()`'s state-aware `needs_open` branching —
each method's precondition is one branch of that same boolean logic,
made explicit and independently inspectable instead of buried in one
`if`:

1. `deposit_not_openable_or_already_open` — precondition:
   `target.is_openable is False OR target.is_open is True` →
   `[LocateObject(target), Place(obj, target)]` (no `open`/`close`).
2. `deposit_needs_open` — precondition (method 1 already ruled out):
   `use_container OR target.is_open is False` →
   `[LocateObject(target), Open(target), Place(obj, target), Close(target)]`.
3. `deposit_default` — fallback, no precondition (e.g. a bare `place`
   onto a target with unknown open/closed state and `use_container=False`)
   → `[LocateObject(target), Place(obj, target)]`.

Top-level goal → compound task mapping (`HTN_GOAL_TASKS`) is the HTN
analogue of `rule_based.GOAL_HANDLERS`, scoped to this slice's goal
coverage.

### The decomposition engine

```python
def _decompose(task: Task, state: WorldState, builder: _StepBuilder) -> None:
    if isinstance(task, PrimitiveTask):
        builder.add(task.action, task.target, task.parameters)
        return
    for method in METHOD_LIBRARY[task.name]:
        if method.precondition(state, task.args):
            for subtask in method.decompose(task.args):
                _decompose(subtask, state, builder)
            return
    raise UnsupportedGoalError(
        f"No applicable method for compound task {task.name!r} given current state."
    )
```

Recursive task-network expansion: a compound task's chosen method may
itself produce more compound subtasks (`StoreObject` → `AcquireObject`
+ `DepositObject`, both still compound; `AcquireObject` → `LocateObject`
+ `PickUp`, one compound and one primitive) — decomposition continues
until only primitives remain, exactly like a real HTN planner's
task-network expansion, not a single flat lookup table.

Method preconditions read the **same** `WorldState` snapshot passed
into `_generate_steps()` throughout decomposition — never a
progressively-mutated copy. This matches `RuleBasedPlanner`'s existing
semantics exactly (it also only ever reads the initial state snapshot,
never simulates its own effects mid-generation — `PlanValidator` is
what replays effects forward, separately, after the fact), so a task
that is ambiguous for one planner (e.g. `target.is_open` unknown) is
ambiguous the same way for both, and the two planners' outputs stay
directly comparable.

### Memory hints: explicitly out of scope for this slice

`RuleBasedPlanner`'s memory-conditioned search hints (Phase 6.3,
`_apply_memory_hint`) are not implemented in `HTNPlanner` slice 1 —
`_generate_steps()` still accepts `memory_context` for interface
conformance (see `planner.py`'s docstring on why every strategy must
accept the parameter even unused) but does not consume it, exactly the
same documented non-consumption `BehaviorTreePlanner`/`ReActPlanner`
already have. A future slice could add a `LocateObject` method that
tries a memory hint before falling back to the direct `Locate`/`Navigate`
pair — the method-list structure already supports this as an
additive change (a new method tried before the existing one), without
touching the engine.

### Generalization check: `HTNPlanner` (unchanged) against `milo_benchmark v1.1`'s non-`tier4` tasks

The original slice-1 validation ran against `v1.0` (5 scenes, 25
tasks) and matched `rule_based`/`behavior_tree` exactly. That left
open whether the 5-scene result was representative or just narrow —
`v1.1` adds 4 more scenes/room types (`FloorPlan202`/`302`/`402`/`203`)
specifically to stress generalization. This pass ran the existing
`HTNPlanner` (no code changes) against all 45 `v1.1` tasks outside
`tier4_multi_step` (`tier1_locate`/`tier2_pickup`/`tier3_store` across
all 9 scenes) — `tier4_multi_step` was explicitly skipped, not
attempted: slice 1 has no multi-subtask decomposition, so those 9
tasks are out of scope for this planner until a future slice, not a
result to report here.

**Result: 43/45 (95.6%)** — `tier1_locate` 18/18, `tier2_pickup`
18/18, `tier3_store` 7/9. The two `tier3_store` failures
(`milo-v1-fp301-t3a`, `milo-v1.1-fp203-t3a`) both raise `"No valid
positions to place object found"` — the same real AI2-THOR
placement-geometry limit already documented for `rule_based`/
`behavior_tree` on this exact pair of tasks in the `v1.1` run (see
`experiments/reports/phase_e_milo_benchmark_report.md`'s "`tier3_store`:
2 new failures on the 4 new scenes, both real AI2-THOR geometry
limits" section), not a new planner defect and not specific to HTN's
decomposition. **Generalization holds**: the 5-scene `v1.0` result
(24/25, one geometry-limit failure) was not an artifact of a narrow
scene set — HTN's method library decomposes correctly across all 9
scenes/room types in `v1.1`, with failures tracking the same known
physical limit every other symbolic planner hits, not new
decomposition gaps. Raw per-episode output:
`backend/planning_evaluation/results/htn_v11_nontier4_*.json`.

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
