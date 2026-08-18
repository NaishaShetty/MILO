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
| E | `milo_benchmark v1.0`: versioned 25-task/5-scene/3-tier dataset (`backend/planning_evaluation/dataset/v1.0/`), planner-comparison + memory-ablation runners, live post-execution goal-check scoring | ✅ Done (dataset + runner + real baselines) — original run: `rule_based` 23/25 (92%), `behavior_tree` 22/25 (88%); memory ablation re-confirmed across all 5 scenes. **These two numbers are historical** — both non-geometry failures were fixed by the "E follow-up" rows below, and a full re-run puts both planners at 24/25 (96%); see the "E follow-up" rows and Addendum 3 for current numbers. `ReActPlanner` baseline and Hugging Face Hub publish were tracked separately below at the time (no LLM key / no HF token in this environment then) — see the "E follow-up" ReAct rows for how that was resolved. See [`experiments/reports/phase_e_milo_benchmark_report.md`](../experiments/reports/phase_e_milo_benchmark_report.md). |
| E follow-up | `_deposit()` non-openable-target fix: added `ObjectState.is_openable` (`planner/state.py`), `_deposit()` now skips `open`/`close` when a `store`/`place` target is known-`False` openable, `_seed_initial_state_from_live_metadata` seeds it from AI2-THOR's own `openable` flag | ✅ Done — re-ran `milo-v1-fp401-t3a` (spray bottle → shelf) against real AI2-THOR: now succeeds (`goal_success=True`), was the one non-geometry `tier3_store` failure in the Phase E baseline. Regression tests: `test_store_goal_has_no_open_close_for_a_known_non_openable_target`, `test_store_goal_still_opens_a_target_with_unknown_openable_state` (`tests/test_planner_rule_based.py`). See the Phase D report's resolution addendum. |
| E follow-up | Misleading `ACTION_TIMEOUT` message root-caused and fixed: `ai2thor.fifo_server.FifoServer` has its own internal ~100s pipe-read timeout, unrelated to and invisible to this project's `step_timeout_s`; since Python 3.11 `concurrent.futures.TimeoutError is TimeoutError`, so AI2-THOR's own timeout was landing in `execution/controller.py`'s `except FutureTimeoutError:` clause and being misattributed to a `step_timeout_s` that was never configured (producing `"exceeded its Nones timeout"`) | ✅ Done (message fixed; the underlying ~100s Unity stall itself is an AI2-THOR/Unity characteristic, not a bug in this project, and is not "fixed" — see the addendum for why that distinction matters) — `_dispatch_with_retries` now reports which timeout actually fired, with AI2-THOR's own real number included. Regression test: `test_engine_level_timeout_with_no_step_timeout_configured_is_reported_accurately` (`tests/test_execution_controller.py`). See `experiments/reports/phase_e_milo_benchmark_report.md`'s resolution addendum. |
| B follow-up | Memory-hint `parentReceptacle` gap root-caused and fixed: real AI2-THOR 5.0.0 populates a separate, previously-unread `parentReceptacles` (plural, list) metadata field reliably for every loose object, even when the deprecated singular `parentReceptacle` this project's code exclusively read is always `None`; `TaskRunner._form_observation()` now prefers the plural field (falling back to singular for synthetic `FakeSimulator` scenarios, which only ever populate the singular one) | ✅ Done — re-ran the "find X twice" recall ablation across all 5 Phase D scenes: memory hint now engages on 5/5 `memory_on` recall episodes (was 0/5), confirmed via each episode's plan gaining the expected extra `locate`/`navigate` pair on the remembered location. See the Phase B report's resolution addendum. |
| E follow-up | Real `ReActPlanner`/Gemini baseline attempted on `milo_benchmark v1.0` (`LANGUAGE_LLM_PROVIDER=gemini`, `gemini-flash-latest`) | ⚠️ Attempted, not a clean baseline — Gemini's free tier hit its daily quota (20 requests/day for this model) partway through the run; only 2/25 episodes got a real plan produced+executed. See `experiments/reports/phase_e_milo_benchmark_report.md`'s Addendum 2. Superseded by a clean local baseline, next row. |
| E follow-up | Real `ReActPlanner` baseline via local Qwen/Ollama (`qwen2.5:7b`, Q4_K_M, served by Ollama on an RTX 4050 Laptop GPU, 6GB VRAM, 82%/18% GPU/CPU split) — no quota, no fallback planner | ✅ Done — clean 20/25 (80%) on the full `milo_benchmark v1.0` set: 10/10 `tier1_locate`, 10/10 `tier2_pickup`, 0/5 `tier3_store`. `goal_success`/`execution_success`/`plan_success` agree on every episode (no predicate-artifact this time). All 5 failures are genuine multi-step reasoning failures (precondition-order mistakes), not infrastructure — none needed the transient-error retry wrapper. `rule_based`/`behavior_tree` re-confirmed at 24/25 (96%) each in the same run. See `experiments/reports/phase_e_milo_benchmark_report.md`'s Addendum 3 for full setup/reproducibility detail and the per-task failure breakdown. |
| Test infra | `backend/tests/conftest.py` added — forces `VISION_ENABLE_SIMULATOR=false` for every test under `backend/tests/`, regardless of a local `backend/.env` setting it `true` for interactive dev (`api/app.py`'s `load_dotenv()` only fills gaps in `os.environ`, so the `.env` value otherwise leaked into every `TestClient`) | ✅ Done — fixed two things at once: (1) 3 tests asserting the "no simulator configured" `503` case were seeing a real simulator instead and failing; (2) nearly every `TestClient` construction across the suite was incidentally loading real Grounding DINO/SAM2 weights via the app's lifespan, which is why the full suite took 13–14 minutes — with the leak fixed it now runs in ~6 seconds. `test_api_app_lifecycle.py`'s own tests (which intentionally toggle this var via `monkeypatch`) are unaffected. **Independent of benchmark/dataset validity** — this is a pytest-only env-leak fix; the real `run_benchmark.py`/`run_floorplan_sweep.py`/etc. runs set their own env vars explicitly (`RUN_SIMULATOR_TESTS=true`) and were never affected by this. Documented in `docs/testing/running_tests.md`. |

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
| Full vision state fusion | Phase C's `ground_world_state()` grounds only existence (`is_located`), proximity (`is_near_robot`, depth-thresholded), and containment (`location`, from `RelationshipType.INSIDE` edges) — not `is_open`/`is_held`, which need an appearance model and grasp-state signal this project doesn't have yet. `execution.resolver.ObjectResolver`'s AI2-THOR metadata scan is intentionally unaffected — it resolves a plan step to a simulator `objectId` for dispatch, a different problem from what the planner believes about the world. See `backend/planner/grounding.py`'s module docstring. |
| HTN planner | Never implemented, despite being one of the originally scoped planning strategies. |
| True path-planning navigation | `Simulator.navigate_to()` teleports to an interactable pose (AI2-THOR's `GetInteractablePoses` + `TeleportFull`), not a walked path — a documented scope decision, not a bug. |
| Learned scene graph | Only a heuristic (`HeuristicSceneGraph`) exists; a model-based `BaseSceneGraph` implementation is future work. |
| Real-scene perception benchmark | `backend/vision_evaluation/` is synthetic/deterministic; a curated, labeled AI2-THOR dataset is future work. |
| Appearance-based re-identification | `IoUTracker` never re-matches a track after it's `LOST`. |
| Production hardening of the API | No authentication, rate limiting, or request quotas on any route yet — required before any public deployment. |
| Conversational clarification loop | The frontend surfaces `clarification_reason` but has no follow-up-question flow. |
| Broader scene/task diversity beyond the Phase D sample | Phase D validated 5 of ~120 iTHOR scenes (one per room type plus a second kitchen), 3 tasks each — real signal, not a statistically powered study. See [`experiments/reports/phase_d_floorplan_generalization_findings.md`](../experiments/reports/phase_d_floorplan_generalization_findings.md). |
| Publish `milo_benchmark v1.0` to the Hugging Face Hub | Dataset + card are built and versioned locally (`backend/planning_evaluation/dataset/v1.0/`); publishing needs an `HF_TOKEN` and a destination namespace, neither available in this environment. See the report's "Publishing" section for the exact push commands. |
