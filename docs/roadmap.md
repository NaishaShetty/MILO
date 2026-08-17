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
| 6.4 | Memory research evaluation (memory-vs-no-memory benchmark) | ✅ Done — originally `FakeSimulator`-only; re-run against real AI2-THOR + a real embedder in Phase B (see [`experiments/reports/phase_b_real_ablation_findings.md`](../experiments/reports/phase_b_real_ablation_findings.md)) |
| 7 | Multi-agent `Orchestrator`, Reflection, dynamic replanning, Speech (Whisper) | ✅ Done — corrects the pre-8.7 README, which listed Reflection and Speech as "Planned" |
| 8.1–8.6 | MILO frontend (7 pages), ElevenLabs voice, MILO Lab, Docker/CI, configuration hardening | ✅ Done |
| 8.7 | Final research-readiness audit, critical bug fix (target/target_location), README restructure | ✅ Done |
| C | Vision-grounded planning: `SpatialScene → WorldState` translation layer (`backend/planner/grounding.py`), existence/location grounding only | ✅ Done — `Orchestrator._observe()` now grounds `WorldState` from a live `Scene` before planning and before each replan, not just for Mission Control display. See "Future work" below for what full state fusion still leaves open. |
| D | Floor-plan generalization sweep: 5 real AI2-THOR scenes (all 4 iTHOR room types), 3 tasks each, unmodified pipeline | ✅ Done — 13/15 succeeded; both failures have concrete causes (one real AI2-THOR geometry limit, one genuine `_deposit()` planner bug this sweep newly found). See [`experiments/reports/phase_d_floorplan_generalization_findings.md`](../experiments/reports/phase_d_floorplan_generalization_findings.md). |
| E | `milo_benchmark v1.0`: versioned 25-task/5-scene/3-tier dataset (`backend/planning_evaluation/dataset/v1.0/`), planner-comparison + memory-ablation runners, live post-execution goal-check scoring | ✅ Done (dataset + runner + real baselines) — `rule_based` 23/25 (92%), `behavior_tree` 22/25 (88%); memory ablation re-confirmed across all 5 scenes. `ReActPlanner` baseline and Hugging Face Hub publish are tracked separately below (no LLM key / no HF token in this environment). See [`experiments/reports/phase_e_milo_benchmark_report.md`](../experiments/reports/phase_e_milo_benchmark_report.md). |

## Future work

Audited against the Phase 8.7 implementation — items already built (Reflection,
dynamic replanning, memory-conditioned planning for the rule-based path, Speech)
are removed from this list; only what's genuinely still open remains. Three
more items (memory threaded into the ReAct prompt, the rule-based
closed-receptacle gap, the two orchestration entry points) were closed out in
a follow-up pass — see `backend/planner/react.py`, `backend/planner/
rule_based.py`'s `_deposit()`, and `backend/orchestration/task_runner.py`'s
"Status: legacy single-attempt entry point" docstring section. A further
follow-up (Phase B) re-ran the Phase 6.4 memory ablation against real
AI2-THOR + a real embedder rather than `FakeSimulator`/a lexical embedder —
see [`experiments/reports/phase_b_real_ablation_findings.md`](../experiments/reports/phase_b_real_ablation_findings.md)
for the result (the 90%→80% finding didn't reproduce, and why) and the new
item below it identified as the concrete next step.

| Item | Why it's not done |
|---|---|
| Broaden memory's location signal beyond `parentReceptacle` | `orchestration.task_runner.TaskRunner._form_observation()` only forms a location-hint-eligible `SEMANTIC` memory when an object's AI2-THOR `parentReceptacle` metadata is set, which real AI2-THOR leaves `None` for ordinary loose/pickupable objects — so `rule_based.py`'s memory-hint mechanism, while correct, never actually engages against a real scene today. See the Phase B findings doc above. |
| Full vision state fusion | Phase C's `ground_world_state()` grounds only existence (`is_located`), proximity (`is_near_robot`, depth-thresholded), and containment (`location`, from `RelationshipType.INSIDE` edges) — not `is_open`/`is_held`, which need an appearance model and grasp-state signal this project doesn't have yet. `execution.resolver.ObjectResolver`'s AI2-THOR metadata scan is intentionally unaffected — it resolves a plan step to a simulator `objectId` for dispatch, a different problem from what the planner believes about the world. See `backend/planner/grounding.py`'s module docstring. |
| HTN planner | Never implemented, despite being one of the originally scoped planning strategies. |
| True path-planning navigation | `Simulator.navigate_to()` teleports to an interactable pose (AI2-THOR's `GetInteractablePoses` + `TeleportFull`), not a walked path — a documented scope decision, not a bug. |
| Learned scene graph | Only a heuristic (`HeuristicSceneGraph`) exists; a model-based `BaseSceneGraph` implementation is future work. |
| Real-scene perception benchmark | `backend/vision_evaluation/` is synthetic/deterministic; a curated, labeled AI2-THOR dataset is future work. |
| Appearance-based re-identification | `IoUTracker` never re-matches a track after it's `LOST`. |
| Production hardening of the API | No authentication, rate limiting, or request quotas on any route yet — required before any public deployment. |
| Conversational clarification loop | The frontend surfaces `clarification_reason` but has no follow-up-question flow. |
| `_deposit()` assumes every `store` destination is openable | Phase D's floor-plan sweep found `rule_based.py`'s `_deposit()` inserts an `open`/`close` pair for any `store` target whose `is_open` isn't known `True` — including non-openable receptacles like a bathroom shelf, which real AI2-THOR then rejects ("... is not an Openable object"). Needs an `is_openable` signal (live metadata has `openable`; vision doesn't yet) `_deposit()` can check before deciding to open. See the Phase D findings doc below. |
| Misleading `ACTION_TIMEOUT` message when no step timeout is configured | Phase E's benchmark hit a real ~100s AI2-THOR `navigate` stall (`execution.controller.ExecutionController._dispatch_with_retries`, `controller.py:418-429`) that raised `concurrent.futures.TimeoutError` from *inside* `self._dispatcher.dispatch(action)` itself — not from the `ThreadPoolExecutor`-wrapped path, which is only entered when `step_timeout_s` is set (`controller.py:488-495`; `TaskRunner`/`ExecutionAgentWrapper` both construct `ExecutionController` with the default `step_timeout_s=None`). The `except FutureTimeoutError:` handler (`controller.py:418-429`) still catches it and reports `"exceeded its Nones timeout"`, blaming a step timeout that was never configured. Two separate issues: (1) the message is wrong/confusing whenever this path fires with no configured timeout, (2) there is currently no way to bound how long a single real AI2-THOR action can hang when no `step_timeout_s` is set — a stall like this one blocks the whole execution loop for its full duration. Observed once, on one `behavior_tree` episode, not reproduced on the identical task under `rule_based` moments earlier — likely AI2-THOR/Unity-side flakiness rather than a planner-caused defect, but worth a real fix regardless. See `experiments/reports/phase_e_milo_benchmark_report.md`. |
| Broader scene/task diversity beyond the Phase D sample | Phase D validated 5 of ~120 iTHOR scenes (one per room type plus a second kitchen), 3 tasks each — real signal, not a statistically powered study. See [`experiments/reports/phase_d_floorplan_generalization_findings.md`](../experiments/reports/phase_d_floorplan_generalization_findings.md). |
| Real `ReActPlanner` baseline on `milo_benchmark` | This environment has no LLM API key (`OPENAI_API_KEY`/`GEMINI_API_KEY`/etc unset); `run_benchmark.py`'s `PLANNERS` dict needs one line added once a key is available. See `experiments/reports/phase_e_milo_benchmark_report.md` section 3. |
| Publish `milo_benchmark v1.0` to the Hugging Face Hub | Dataset + card are built and versioned locally (`backend/planning_evaluation/dataset/v1.0/`); publishing needs an `HF_TOKEN` and a destination namespace, neither available in this environment. See the report's "Publishing" section for the exact push commands. |
