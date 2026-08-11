# MILO — Project Overview

**MILO** (Memory Integrated Language Oriented robot) is an embodied AI
research platform: a natural-language instruction goes through real
language understanding, memory retrieval, planning, perception, and
execution against a real AI2-THOR simulated robot, with the outcome fed
back into memory for future tasks.

This document is a factual summary of what is actually implemented and
running in this repository as of Phase 8.6 — every claim below is backed
by real code and real tests, not aspirational design.

## What MILO actually does

Given a typed or spoken instruction ("find the mug"), MILO:

1. **Understands** the instruction via an LLM-backed language agent
   (OpenAI, Gemini, or a local Qwen-compatible endpoint — pluggable via
   provider configuration), producing a structured goal/object/target.
2. **Retrieves relevant memory** — prior episodes, known object
   locations, past failures — via a real SQLite + vector-embedding
   memory store.
3. **Plans** a sequence of steps using one of three interchangeable
   planner strategies (rule-based, ReAct-style, or behavior-tree).
4. **Perceives** the scene using a real vision pipeline (Grounding DINO
   for open-vocabulary detection, SAM2 for segmentation, depth
   estimation, and a temporal scene graph).
5. **Executes** the plan against a real AI2-THOR simulated environment —
   real movement, object pickup/put-down/open/close actions, with retry
   and precondition/postcondition checking.
6. **Reflects** on the outcome (continue / retry / replan / abort) and
   **writes new memory** (episodic success/failure records) for future
   tasks to draw on.
7. **Responds** — with a spoken reply via ElevenLabs TTS, if configured.

All of this is driven by a canonical MILO state machine
(`idle → listening → understanding → thinking → planning → executing →
reflecting → speaking → success/error`) with real character artwork per
state, and every backend stage is visible in the frontend dashboard —
Mission Control shows the live agent architecture, the live plan with
real per-step timing, the live memory retrieved/created for the task in
progress, and (when the simulator is connected) the robot's live
position/rotation/held object.

## What this is not

MILO is a **simulation-based research platform**, not a deployed
physical robot. See [`limitations.md`](limitations.md) for the specific,
honest boundaries of what's implemented — path planning, concurrency,
persistence, and a few other areas have documented, deliberate scope
limits rather than being silently missing.

## Where to look

- [`architecture.md`](architecture.md) — system and agent architecture,
  task lifecycle, with diagrams of the real (not aspirational) pipeline.
- [`tech_stack.md`](tech_stack.md) — the real technologies in use.
- [`limitations.md`](limitations.md) — honest, specific boundaries.
- [`docs/architecture/demo_and_visualization.md`](../architecture/demo_and_visualization.md)
  — how the Phase 8.6 demo/visualization layer sources its data.
- [`docs/screenshots/`](../screenshots/) — a screenshot set of every
  major page and visualization, including a real live-simulator run.
