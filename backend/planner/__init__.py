"""
planner (backend/planner)

Purpose
-------
Phase 4 — Task Planning. This package turns a validated `ParsedInstruction`
(`schemas/task.py`, produced by the Phase 3 Language Understanding runtime)
into a `PlanningResult` carrying a validated, simulator-independent `Plan`:
an ordered sequence of abstract `PlanStep`s such as
`PlanStep(action="navigate", target="apple")`.

This package never calls AI2-THOR and never imports `simulator/`. That
boundary is deliberate and load-bearing: Phase 5 (Execution) is the only
layer allowed to translate an abstract `PlanStep` into a concrete
simulator action (`MoveAhead`, `PickupObject`, ...). Keeping the Planner
simulator-independent is what makes it possible to unit-test every
planning strategy (rule-based, ReAct, behavior-tree) against a purely
symbolic `WorldState` (see `state.py`), with no Unity/AI2-THOR process
required, and what will let Phase 5 swap in a different simulator later
without touching this package at all.

Module map
----------
- `exceptions.py`   -- the closed `PlanningError` hierarchy every
                        planner-facing failure raises.
- `models.py`        -- typed data model: `PlanStep`, `Plan`, `PlanStatus`,
                         `StepStatus`, `PlanningResult`, `ValidationResult`.
- `actions.py`       -- the action model: one `ActionSpec` per abstract
                         action, each carrying its preconditions and its
                         effect on a `WorldState`.
- `state.py`         -- `WorldState`, the lightweight symbolic simulator
                         used to validate a plan without executing it.
- `validator.py`     -- `PlanValidator`, which replays a `Plan` against a
                         `WorldState` and reports structured issues.
- `planner.py`       -- the `Planner` abstract base class every strategy
                         implements, plus shared finalize/validate wiring.
- `rule_based.py`    -- `RuleBasedPlanner`, the deterministic baseline.
- `react.py`         -- `ReActPlanner`, an LLM-driven iterative planner
                         built on the same `Planner` interface.
- `behavior_tree.py` -- Behavior Tree node types and `BehaviorTreePlanner`.
- `factory.py`       -- `create_planner()` / `PlannerType`, the single
                         place callers select a planning strategy.
- `evaluation.py`    -- `PlannerEvaluator`, for comparing strategies on
                         success, validity, latency, and step count.

Consumers
---------
A future Phase 4 `agents/planner_agent.py` (or the API layer directly)
is expected to call `factory.create_planner(...).plan(task, state)` and
hand the resulting `PlanningResult.plan` to Phase 5. Nothing in this
package reads or writes `Task`/`SingleTask`/`MultiTask` fields beyond
what `schemas/task.py` already exposes -- see that module's own
docstring for the Language Interface contract this package consumes.
"""
