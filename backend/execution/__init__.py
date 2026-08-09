"""
execution (backend/execution)

Purpose
-------
Phase 5 -- Execution & Action Control. This package turns a validated,
simulator-independent `planner.models.Plan` (Phase 4's output) into
actual AI2-THOR calls, step by step, through `simulator.simulator.Simulator`
-- and nothing else in this project is allowed to do that translation.
Concretely, this package answers "how do I actually run this plan?",
exactly one layer below the question Phase 4 already answers ("what
should the robot do?") and one layer above the question `simulator/`
answers ("how do I talk to AI2-THOR?").

```
Planner (Phase 4)          -- WHAT to do      -> abstract PlanStep
Execution (this package)   -- HOW to do it    -> concrete Action + dispatch
Simulator (backend/simulator/) -- perform it  -> AI2-THOR call
```

Why this package never imports AI2-THOR directly
--------------------------------------------------
Every AI2-THOR call this package ever makes goes through
`simulator.simulator.Simulator` (constructed by the caller -- typically
`api/app.py`'s FastAPI lifespan, exactly like Vision already does --
and passed in). This package imports `simulator.simulator`, never
`ai2thor.controller` itself, and never `simulator.ai2thor_env` directly
either -- mirroring the same boundary `backend/planner/__init__.py`
already documents for keeping the Planner simulator-independent. This
is what makes `dispatcher.py`/`controller.py` unit-testable against a
fake/mock `Simulator` with no Unity process anywhere in this package's
default test suite (see `backend/tests/test_execution_*.py`), and what
would let a future Habitat/Isaac Sim/ROS2 backend replace
`simulator/simulator.py`'s implementation without this package or the
Planner ever changing.

Why this package never rewrites a `PlanStep`'s abstract action vocabulary
---------------------------------------------------------------------------
`planner.actions.ACTION_REGISTRY` and `planner.state.WorldState` are
Phase 4's action model and symbolic state -- the single source of truth
for what each abstract action (`locate`, `navigate`, `pickup`, `open`,
`close`, `place`, `put_down`) requires and guarantees. This package
reuses both directly (`preconditions.py`) rather than re-deriving a
second copy of "what does `open` require" -- the same "do not duplicate
existing architecture" rule the top-level Phase 5 spec calls out
explicitly. What this package adds on top is everything Phase 4
deliberately does NOT own: concrete AI2-THOR `objectId` resolution,
simulator dispatch, ground-truth result validation, retries, timeouts,
cancellation, and structured execution events.

Module map
----------
- `errors.py`        -- `ExecutionErrorCode` (closed error taxonomy) and
                         `ExecutionError` (structured, machine-readable
                         failure record).
- `models.py`         -- `ActionType`, `Action`, `ActionResult`,
                         `ExecutionEvent`, `ExecutionStatus`,
                         `ExecutionRecord` -- this package's own typed
                         data model, mirroring `planner/models.py`'s
                         "data model has no logic" convention.
- `exceptions.py`     -- the closed `ExecutionRuntimeError` hierarchy
                         for programmer/configuration errors this
                         package cannot recover from on its own (never
                         used for an ordinary step failure -- see that
                         module's docstring, matching
                         `planner/exceptions.py`'s own split).
- `resolver.py`       -- `ObjectResolver`, translating a `PlanStep`'s
                         human-readable `target`/`parameters["container"]`
                         name into a concrete AI2-THOR `objectId` by
                         reading `Simulator.get_metadata()` -- the one
                         place this package couples an abstract plan to
                         a concrete scene.
- `dispatcher.py`     -- `ActionDispatcher`, the single centralized
                         boundary translating one `Action` into exactly
                         one `Simulator` method call. No other module in
                         this package (or anywhere else) calls a
                         `Simulator` method directly.
- `preconditions.py`  -- `PreconditionChecker`, wrapping
                         `planner.actions.ACTION_REGISTRY` to check a
                         `PlanStep`'s preconditions against a
                         `planner.state.WorldState` immediately before
                         dispatch, plus the simulator-groundable checks
                         Phase 4's purely symbolic state cannot make
                         (e.g. "does this objectId actually exist right
                         now").
- `validator.py`      -- `ResultValidator`, turning a raw AI2-THOR event
                         into a structured `ActionResult` by checking
                         the simulator's own reported success flag AND,
                         where AI2-THOR exposes it, the expected
                         ground-truth state change (e.g. `isOpen`).
- `controller.py`     -- `ExecutionController`, the sequential executor:
                         loads a `Plan`, dispatches each `PlanStep`
                         through the pipeline above, updates
                         `Plan`/`PlanStep` status in place, records
                         `ExecutionEvent`s, and supports `cancel()`.

Consumers
---------
`api/routes/execution.py` is this package's only consumer today: it
constructs one `ExecutionController` per request (backed by
`app.state.simulator`) and exposes `load_plan`/`execute_plan`/`cancel`
over HTTP. `frontend/src/components/ExecutionPanel.tsx` renders the
resulting `ExecutionRecord`. A future Phase 6 Memory Agent is expected
to read `ExecutionRecord`s (via the API or, later, directly) as
episodic experience -- see `controller.py`'s docstring for exactly what
shape that record has and why it was kept storage-agnostic.
"""
