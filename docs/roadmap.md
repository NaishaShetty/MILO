# Roadmap

Two tables: a phase-completion history (audited against the Phase 8.7
findings — see below for what changed), and the genuinely future work
that remains. For the detailed per-phase implementation record, see
[`development_history.md`](development_history.md) and
[`phases/phase8_7_final_audit.md`](phases/phase8_7_final_audit.md).

## Phase completion history

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Simulator & Navigation | ✅ Done |
| 2 | Perception (detection, segmentation, scene graph, model management) | ✅ Done |
| 3.1–3.7 | Language Interface (spec, schema, parser assets, runtime, error recovery, benchmarking, API/frontend) | ✅ Done |
| 3.x | Spatial & Temporal Perception (depth, 2D→3D localization, tracking, temporal scene) | ✅ Done |
| 4 | Task Planning (rule-based, ReAct, and Behavior Tree planners, validator, symbolic `WorldState`, evaluation) | ✅ Done |
| 5 | Execution & Action Control (dispatcher, precondition/result validation, error taxonomy) | ✅ Done |
| 6.1–6.2 | Memory Foundation & Intelligence (episodic/semantic/failure memory, SQLite + vector retrieval) | ✅ Done |
| 6.3 | Memory ↔ Robot Integration (memory-conditioned planning, retrieve→plan→execute→remember loop) | ✅ Done |
| 6.4 | Memory research evaluation (memory-vs-no-memory benchmark) | ✅ Done — see [Known Limitations](../README.md#known-limitations) for the FakeSimulator caveat |
| 7 | Multi-agent `Orchestrator`, Reflection, dynamic replanning, Speech (Whisper) | ✅ Done — corrects the pre-8.7 README, which listed Reflection and Speech as "Planned" |
| 8.1–8.6 | MILO frontend (7 pages), ElevenLabs voice, MILO Lab, Docker/CI, configuration hardening | ✅ Done |
| 8.7 | Final research-readiness audit, critical bug fix (target/target_location), README restructure | ✅ Done |

## Future work

Audited against the Phase 8.7 implementation — items already built (Reflection,
dynamic replanning, memory-conditioned planning for the rule-based path, Speech)
are removed from this list; only what's genuinely still open remains.

| Item | Why it's not done |
|---|---|
| Vision-grounded `WorldState` | Planner/Execution still plan against a fresh symbolic `WorldState` or a live AI2-THOR metadata scan by name — not a real Vision `SpatialScene`. See `docs/architecture/spatial_perception.md`'s "Planner boundary" note. |
| Memory threaded into the ReAct/LLM planner prompt | `ReActPlanner.plan()` accepts `memory_context` but doesn't use it (`backend/planner/react.py`); only the rule-based fallback path benefits from memory today. |
| Rule-based planner's closed-receptacle gap | The "place" plan template doesn't insert an open-receptacle step before placing into a closed container — reproduced live during the Phase 8.7 audit. |
| HTN planner | Never implemented, despite being one of the originally scoped planning strategies. |
| Resolve the two orchestration entry points | `orchestration/orchestrator.py` (current) and the older `orchestration/task_runner.py` (single-attempt) coexist; the latter should likely be removed or clearly marked legacy. |
| True path-planning navigation | `Simulator.navigate_to()` teleports to an interactable pose (AI2-THOR's `GetInteractablePoses` + `TeleportFull`), not a walked path — a documented scope decision, not a bug. |
| Learned scene graph | Only a heuristic (`HeuristicSceneGraph`) exists; a model-based `BaseSceneGraph` implementation is future work. |
| Real-scene perception benchmark | `backend/vision_evaluation/` is synthetic/deterministic; a curated, labeled AI2-THOR dataset is future work. |
| Appearance-based re-identification | `IoUTracker` never re-matches a track after it's `LOST`. |
| Production hardening of the API | No authentication, rate limiting, or request quotas on any route yet — required before any public deployment. |
| Conversational clarification loop | The frontend surfaces `clarification_reason` but has no follow-up-question flow. |
| Broader scene/task diversity | The platform runs against AI2-THOR's `FloorPlan1` by default; generalization across scenes/tasks is unvalidated. |
