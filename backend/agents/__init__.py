"""
agents (backend/agents)

Purpose
-------
Phase 7's Common Agent Architecture. Every module in this package is a
thin, composable wrapper around an already-existing, already-tested
Phase 1-6 subsystem (`vision.vision_agent.VisionAgent`,
`memory.agent.MemoryAgent`, `planner.factory.create_planner`,
`execution.controller.ExecutionController`) plus two genuinely new
capabilities this phase introduces (`NavigationAgent`,
`ReflectionAgent`). Nothing here reimplements perception, memory,
planning, or execution logic -- see each module's own docstring for
exactly what it wraps and why.

Layering (no circular imports)
-------------------------------
`contracts.py` / `base.py` / `failures.py` / `task_state.py` /
`events.py` are pure data/interface modules with zero dependencies on
any concrete agent. Each concrete `*_agent.py` module depends only on
those plus the one Phase 1-6 package it wraps -- never on another
`*_agent.py` module. `registry.py` depends on the concrete agent
modules (to type-hint/construct them) but no concrete agent ever
imports `registry.py` back. `backend/orchestration/orchestrator.py` is
the only module that depends on all of the above at once.
"""
