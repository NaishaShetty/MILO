# Observability, replay and the scene map (roadmap 2, Phase 7)

All three read the mission trace store from Phase 1 (`backend/tracelog/`), so nothing extra is recorded for them apart from MILO's pose on each step.

## Where the time goes (Lab page)

- `GET /api/v1/traces/stats` returns **p50 and p95 per stage** over recent missions: planning, looking (vision), doing (execution), reflecting, remembering, writing memories, and the whole mission. It also gives p50/p95 per action (navigate, pick up, ...). The Lab shows this as a table that refreshes every 3 s.
- `GET /api/v1/traces/{id}/waterfall` returns the latest mission as time bars: the plan, every step (failed steps in coral) and every reflection. The Lab draws it as a live waterfall.

Before and after numbers for the bottlenecks fixed earlier, measured where each fix was made:

| Bottleneck | Before | After | Where measured |
|---|---|---|---|
| Looking at the room on the planning path | Grounding DINO 547 ms/frame; 1.37 s observing per mission | fast detector 5.9 ms/frame (GPU); 0.068 s per mission (20x less) | real AI2-THOR, learned-models Phase C |
| Whole mission (same missions) | 2.63 s | 1.25 s | same |
| Memory search at 50,000 memories | (flat index over hashing vectors) | p50 8.5 ms / p95 15.4 ms | learned-models Phase D |
| Cost of recording a trace | none | about 2.4 ms per mission (18 records) | roadmap 2 Phase 1 |

The live table gives current p50/p95 on whatever runs; the numbers above aren't re-measured on the real simulator in this phase.

## Mission replay

`/replay` lists recorded missions. `/replay/{mission}` is a **shareable link** with a timeline scrubber: drag through every moment of a run to see:
- the camera frame MILO had at that point;
- the plan with the current step highlighted, and how long it took;
- what MILO was thinking;
- the reflection verdict.

**Download report** saves a one-page Markdown run report (`GET /api/v1/traces/{id}/report`) covering:
- the outcome, planner and total time;
- every step with its result, time and confidence;
- MILO's thoughts and reflection verdicts;
- the checks against the world.

Each mission on the Missions page links to its replay.

## Scene map (Missions page)

`GET /api/v1/scene/map` returns:
- MILO's position and **the path it has taken this mission** (from the poses recorded on each step);
- where objects really are, when the simulator reports positions (AI2-THOR does; the synthetic test simulator doesn't);
- **where MILO's memory believes things are**: object, place, decayed confidence, source, and when it was last seen.

The Missions page draws a top-down map and the belief list, refreshing every 2 s while a mission runs. Without positions it shows the beliefs only, and says so.

Tests: `backend/tests/test_observability.py` covers stage stats, waterfall order (including a failed step), recorded poses, the report, and the four endpoints. `frontend/src/pages/ReplayPage.test.tsx` covers the scrubber, frame and verdict at a moment, the report download, the mission list, the stage table, the waterfall, and the map with beliefs.
