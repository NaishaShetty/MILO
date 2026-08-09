# Phase 8.1 — System Audit, Cleanup & Architecture Freeze

Status: **Complete. Cleanup items 1–6 executed and verified (§16/§17); item 7 deferred as unnecessary, item 8 deferred to Phase 8.5 as planned.**
Date: 2026-08-09
Scope: full repository at time of audit (270 backend `.py` files / ~43K lines, 88 backend test files, frontend React/TS app, `models/`, `datasets/`, `experiments/`, `docs/`).

---

## 0. Headline finding

This is **not** a neglected, redundancy-riddled Phase 1–7 codebase. Nearly every module carries a "Purpose / Why" docstring explaining its role and the alternatives it rejected; the test suite is comprehensive (857 tests, currently **all green**, 8 intentionally skipped); dependencies are minimal and each is commented with why it's there; `.gitignore` correctly excludes `node_modules/`, `dist/`, and 1.1GB of model weights. The audit's job here was mostly to **verify** this is true and catch the handful of real hygiene issues, not to perform a large-scale rewrite. That reframes the rest of Phase 8.1: light-touch cleanup, not reconstruction.

One real problem: **there was no git repository** prior to this audit, so nothing was reversible. A local git repo was initialized and the pre-audit state committed as a baseline (`git log` → `Baseline commit: MILO repo state before Phase 8.1 audit`) before any further action, per your instruction. No files have been deleted or modified since.

---

## 1–2. Repository discovery & architecture audit

### Actual request pipeline (verified against code, not assumed)

```
User (frontend, relative /api/v1/* calls)
  → api/app.py (FastAPI, singletons built once in lifespan())
  → api/routes/tasks.py  POST /tasks
      1. LanguageAgent.parse(instruction)              [language/]
      2. Orchestrator.run(task)  spawned in a background thread
         a. _retrieve_memory()      → MemoryAgentWrapper → memory.agent.MemoryAgent   [memory/]
         b. WorldState.initial()    → PlannerAgentWrapper.plan()                       [planner/]
         c. loop:
              _observe()            → VisionAgentWrapper.perceive()  (optional)        [vision/]
              ExecutionAgentWrapper.execute_plan()                                      [execution/]
                → resolve → precondition-check → dispatch → validate → update WorldState
                → dispatch talks to Simulator → ai2thor_env.py → real AI2-THOR/Unity     [simulator/]
              _diagnose()            → navigation_agent.py refines failures             [agents/]
              ReflectionAgent.reflect() → continue / retry / replan / abort             [agents/]
         d. on terminal outcome: _remember_terminal() writes exactly one Memory         [memory/]
  → response → frontend polls /tasks/{id}
```

- **Simulator abstraction**: `simulator/simulator.py`'s `Simulator` class is the sole documented AI2-THOR boundary — "future planner, vision, memory, navigation, and LLM modules should ONLY interact with this class." Verified: no other module imports `ai2thor` directly.
- **Vision is informational, not a precondition gate**: execution resolves objects via simulator ground truth; `_observe()` is skipped entirely if no vision agent is configured (i.e., `VISION_ENABLE_SIMULATOR=false`, the default). This is a real architectural nuance worth stating explicitly in the frozen architecture (§15) since it's easy to assume vision gates execution when it doesn't today.
- **Two orchestration loops coexist by design, not by accident**: `orchestration/task_runner.py`'s `TaskRunner` (single-attempt, no reflection) predates `orchestration/orchestrator.py`'s `Orchestrator` (multi-attempt, reflection-driven). The API (`api/routes/tasks.py`) uses only `Orchestrator`. `TaskRunner` is not dead — it's still the runner used by `memory_evaluation/`'s experiment harnesses (`memory_size.py`, `experiment.py`, `pollution.py`, `scenarios.py`), and both classes' own docstrings cross-reference each other as intentionally parallel. **Verdict: keep both — this is a documented, tested design choice, not redundancy to consolidate.**
- **Planner has three registered strategies** (`RULE_BASED`, `REACT`, `BEHAVIOR_TREE`) via `planner/factory.py`, all reachable through the standalone `/api/v1/planner/*` endpoints. But the live task-execution path (`api/routes/tasks.py::build_orchestrator`) **hardcodes `PlannerType.RULE_BASED`**. This isn't dead code (ReAct/BehaviorTree are tested and API-reachable for experimentation/evaluation), but it means "the planner MILO actually uses end-to-end today" and "the planners you can query via the API" are different sets — worth being explicit about in the architecture freeze so Phase 8.2+ doesn't assume ReAct is live in the main loop.
- **Memory is layered correctly**: `agent.py` (public interface) → `retrieval.py` (ranking engine) → `manager.py`/`store.py` (CRUD/persistence) → `semantics.py` (typed per-type content). No overlapping responsibility found.
- **Vision has exactly one implementation per capability** (one detector: Grounding DINO; one segmenter: SAM2; one scene-graph builder: heuristic; one tracker: IOU/Hungarian) behind abstract base classes — no competing pipelines.

---

## 3–4. Redundant files, dead code, and duplicate implementations

Systematic grep for `_old`, `_v2`, `_backup`, `_final`, `_new`, `deprecated`, `TODO: remove` across all `.py` files: **zero dead-code markers found** (two incidental prose hits about "deprecated Gemini models," unrelated to code cleanliness).

Concrete findings:

| Item | Status | Recommendation |
|---|---|---|
| `backend/scripts/download_model.py` | **0 bytes — empty file, never implemented** | Either implement it (mirrors `download_torch.py`'s pattern, presumably for HF model downloads) or delete it. Currently dead weight either way. |
| `backend/scripts/torch-2.5.1+cu124-cp39-cp39-linux_x86_64.whl` | 213MB binary wheel committed to git | **Remove from git tracking**, add `*.whl` to `.gitignore`. `download_torch.py` already exists to (re)produce it locally. This alone is most of the repo's tracked size. |
| `backend/outputs/memory/memory.db`, `backend/outputs/memory/vector_store/vectors.db` | Runtime-generated SQLite DBs, tracked in git | **Untrack**, extend `.gitignore`'s `outputs/*.png/jpg` pattern to also cover `outputs/**/*.db`. These regenerate from `MEMORY_DATABASE_PATH`/`MEMORY_VECTOR_STORE_PATH` on first use. |
| `experiments/results/benchmark_20260809T120511Z.json` + `_episodes.csv`, `experiments/reports/phase6_4_report.md` | Tracked in git, but `experiments/` has no `.gitignore` entry (unlike `results/`, which handles the same kind of output and *is* gitignored) | Inconsistent policy. Recommend treating `experiments/results/` the same as `results/` (gitignore raw run output), and keeping `experiments/reports/*.md` tracked only if it's meant as a curated, versioned research report (not an automatically regenerated artifact) — needs a one-line decision from you (see §16). |
| `backend/vision/test_vision.py`, `test_detector.py`, `scene/test_scene.py`, `simulator/test_navigation.py`, `test_execution_e2e.py`, `test_simulator_lifecycle.py`, `vision/visualization/test_visualizer.py`, `vision/segmenters/test_sam2.py`, `test_segmentation.py`, `vision/scene_graph/test_scene_graph.py` | Standalone **manual smoke-test scripts** (require live simulator/GPU/real models), living outside `backend/tests/` and outside CI (which scopes to `backend/tests/` only) | Not dead code — legitimate integration checks. But the `test_*.py` naming next to a pytest-based `backend/tests/` suite is confusing (a `pytest` run from repo root could try to collect them and fail without a simulator/GPU). Recommend renaming to a `manual_*.py` or `smoke_*.py` convention, or moving under a `backend/manual_tests/` directory — cosmetic/organizational, not urgent. |
| `docker/README.md` vs `docker/Dockerfile` | README says "no FastAPI service yet (Phase 3.7+)"; Dockerfile's own header comment and `CMD` say it runs the Phase 3.7 FastAPI service | README is stale relative to the Dockerfile it documents. Needs a doc fix (§10/§16), not a code fix. |
| `docs/phases/` | Has `phase1_navigation.md`, `phase2_vision.md`, `phase5_execution.md`, `phase6_memory.md` — **missing Phase 3 (Language/API), Phase 4, and Phase 7 (Agents/Orchestrator)** despite these being fully implemented, tested, and actively used by the frontend | Documentation gap, not a code issue. Phase 3 detail exists but lives under `backend/docs/language_interface_spec.md` instead of `docs/phases/`, fragmenting where "the docs" live. |

**No consolidation of competing implementations was needed** — the "duplicate implementation" audit (planner variants, memory modules, vision pipeline stages) found intentional, non-overlapping designs in every case checked (§2 above), not accidental duplication.

---

## 5. Dependency audit

**Backend (`backend/requirements.txt`, 103 lines)** — every dependency has an inline comment explaining why it's needed and who uses it. No unused, duplicate, or clearly deprecated packages found. Notable deliberate choices already documented in-repo:
- `types-PyYAML`/`types-requests` intentionally **not** added (would trigger a 15+ minute pip backtrack through `ai2thor`'s transitive `aws-requests-auth`/`botocore` chain) — mypy's `import-untyped` error is suppressed per-module in `pyproject.toml` instead. This is a documented tradeoff, not an oversight.
- `openai-whisper` is lazy-imported (opt-in via `SPEECH_ENABLE_WHISPER=false` default) so it doesn't block the rest of the app if absent.
- `scipy` is declared directly (not left as an implicit transitive dep) specifically because `vision/tracking/iou_tracker.py` uses it directly.

**Frontend (`frontend/package.json`)** — minimal: 3 runtime deps (`react`, `react-dom`, `react-router-dom`), sensible dev tooling (vite, vitest, testing-library, eslint, typescript). No bloat, no unused packages found.

**Baseline dependency set for Phase 8 is effectively already the current `backend/requirements.txt` + `frontend/package.json`** — no removals recommended. One note: `pyproject.toml`/CI target Python 3.9, but this sandbox's interpreter is 3.14 and the full test suite still passes — worth confirming the actual target runtime for Phase 8 deployment (Docker image already pins `python:3.9-slim`, so that's the real target; local dev happening on 3.14 is fine as long as CI stays authoritative).

---

## 6. Model & dataset audit

| Resource | Location | Size | Classification | How obtained |
|---|---|---|---|---|
| Grounding DINO weights | `models/grounding_dino/` | 892MB | **Runtime** (object detection) | Auto-downloaded by `config/model_manager.py`'s `ModelManager` from HF Hub into `models/<name>/` on first use — not committed (`.gitignore`: `models/*` except `.gitkeep`) |
| SAM2 weights | `models/sam2/` | 149MB | **Runtime** (segmentation) | Same `ModelManager` mechanism |
| `models/clips`, `depth_anything`, `florence2`, `whisper` | empty placeholder dirs | 0 | **Reserved for future runtime use** — `config/model_config.py` has registry entries but no weights fetched yet (Depth Anything, Whisper, Florence-2 not yet exercised in this environment) | Same `ModelManager` mechanism, on-demand |
| `datasets/language/{evaluation,prompts}/*.json` | 116K, hand-authored | Small | **Required for experiments/evaluation** (language benchmark harness, few-shot prompt examples) | Source-controlled, not generated — correctly tracked |
| `experiments/results/*.json,*.csv`, `experiments/reports/phase6_4_report.md` | tracked | ~60K | **Historical / experiment artifact** — a specific benchmark run's output, currently tracked (inconsistently vs. `results/`, see §3) | Generated by `backend/evaluation`/`backend/memory_evaluation` benchmark runners |
| `results/` | gitignored except README | 0 tracked | **Reproducible runtime output**, correctly excluded | Written by `evaluation/result_store.py` and `vision_evaluation/result_store.py` |

`ModelManager` (`backend/config/model_manager.py`) is the single, well-documented mechanism for all model provenance — this satisfies the audit's "document where required models come from" requirement without further action needed.

---

## 7. Configuration & environment audit

- `backend/.env` is real (47 lines, gitignored, **not committed** — verified) and `backend/.env.example` (114 lines) is a safe, secrets-free template. No API keys, tokens, or credentials found anywhere in tracked files (`git grep` for key/secret/token/password patterns returned nothing outside comments and placeholders like `OPENAI_API_KEY=sk-...`).
- No hardcoded absolute paths, machine-specific URLs, or IPs found in backend config; frontend talks to the backend exclusively via relative URLs (`/api/v1/...`), proxied in dev via `vite.config.ts`'s `VITE_BACKEND_URL` (default `http://localhost:8000`) — this is already machine-independent and container-friendly.
- **ElevenLabs prep (as requested, not implemented)**: `backend/.env.example` currently has no voice/TTS section at all. Recommend adding a clearly-marked, disabled-by-default block mirroring the existing `SPEECH_ENABLE_WHISPER` pattern:

```
# ---- Voice output (ElevenLabs, planned — not yet implemented) ----
# Off by default; no code currently reads these. Reserved structure
# for future Phase 8 voice integration.
# VOICE_ENABLE_ELEVENLABS=false
# ELEVENLABS_VOICE_ID=ISnQja0Ank6t1FE2Wj07
# ELEVENLABS_API_KEY=            # never commit a real value; set in backend/.env only
```
  This stages the voice ID (which is not a secret) without hardcoding the API key anywhere, and without adding any voice code yet, per your constraint. I have **not** written this yet — it's a proposed edit pending your go-ahead (§16), since it touches a tracked file.

---

## 8. Logging & debugging cleanup

- `print()` usage in non-test/non-script backend code is essentially zero; the ~116 `print()` hits found are concentrated in (a) the standalone manual smoke-test scripts noted in §3 (appropriate — they're meant to be run and read by a human at the terminal) and (b) CLI benchmark runners (`evaluation/run_benchmark.py`, `vision_evaluation/run_benchmark.py`, `memory_evaluation/run_benchmark.py`) printing final summary metrics — also appropriate for a CLI tool.
- Structured `logging` (not `print`) is used in 17 files across the actual service code. No excessive/duplicate logging patterns found.
- No changes recommended here — logging hygiene is already good. If you want per-subsystem log namespacing (vision/planning/memory/nav/execution/reflection/API/simulator as distinct loggers) confirmed explicitly, that's a quick follow-up but wasn't found to be a problem in practice (module-qualified logger names already provide this via Python's standard `getLogger(__name__)` convention where used).

---

## 9. Testing audit

- 88 test files in `backend/tests/`, mirroring the module structure 1:1 (e.g. `test_planner_rule_based.py`, `test_memory_retrieval.py`, `test_agents_navigation_agent.py`).
- **Current status: 857 passed, 8 skipped, 0 failed** (ran live during this audit).
- No `conftest.py` exists — fixtures appear to be defined per-file rather than shared; not broken, just worth knowing if Phase 8.3 wants to reduce duplication across test files.
- CI (`​.github/workflows/ci.yml`) runs `black --check`, `ruff check`, `mypy`, and `pytest backend/tests/` for the backend, and `tsc --noEmit` + `vitest` for the frontend — a real, working baseline, not a stub.
- Coverage gaps: `evaluation/`, `memory_evaluation/`, `vision_evaluation/` (the standalone experiment harnesses) and the manual smoke-test scripts (§3) are **not** part of the automated/CI-covered suite by design (they need GPU/simulator/real models) — this is a legitimate, documented exclusion, not an oversight, but Phase 8.3 should decide whether any subset becomes a marked/opt-in CI job (e.g. `pytest -m gpu`).
- No tests found to be broken, obsolete, or duplicated.

**Baseline for Phase 8.3**: current suite is a solid foundation; nothing here needs fixing before moving on.

---

## 10. Documentation audit

- `docs/architecture/` (api_contracts.md — "Phase 2, frozen", perception_pipeline.md, spatial_perception.md) and `docs/testing/manual_e2e_checklist.md` are present and topically accurate to what exists in code.
- `docs/phases/` covers Phases 1, 2, 5, 6 but is **missing Phase 3 (Language/API), Phase 4, and Phase 7 (Agents/Orchestrator)** — a real gap, since Phase 3 and 7 are both large, implemented, and load-bearing (the entire live task pipeline goes through Phase 7's `agents/`+`orchestration/`).
- `backend/docs/language_interface_spec.md` (96K — the largest single doc in the repo) contains the real Phase 3 design detail but lives outside `docs/`, which fragments "where do I look for architecture docs."
- `docker/README.md` is stale relative to `docker/Dockerfile` (§3).
- No broken links, no old screenshots, no duplicate documentation found otherwise.

**Recommendation for Phase 8.5** (not done now, per your "audit only" scope): write `docs/phases/phase3_language.md` and `docs/phases/phase7_agents_orchestration.md`, fix the `docker/README.md` inconsistency, and decide whether `backend/docs/language_interface_spec.md` moves under `docs/` or `docs/` gets a pointer to it.

---

## 11. Repository hygiene

- **No git repo existed before this audit** — now initialized, baseline committed locally (§0).
- No `__pycache__`, `.pyc`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `node_modules`, or `dist/` are tracked (verified via `git ls-files` — zero hits).
- No secrets/API keys found in any tracked file.
- Two real hygiene issues, both listed with recommended fixes in §3/§16: the 213MB `.whl` binary, and the two tracked SQLite DB files under `backend/outputs/`.
- `.gitignore` is otherwise well-maintained and already anticipates most of what a Python + Node + ML project needs.

---

## 12. Issues encountered during Phases 1–7 (from in-repo evidence)

| Problem | Cause | Solution | Impact | Status |
|---|---|---|---|---|
| Unity/AI2-THOR windows accumulated under WSLg until it ran out of resources | Uvicorn's `--reload` re-ran the FastAPI lifespan on every code change, calling `Controller.start()` again without the previous instance ever being stopped | `ai2thor_env.py`'s `start()` made idempotent — returns immediately if `self.controller is not None` — plus explicit lifecycle ownership documented in `simulator.py`/`api/app.py` | Simulator / local WSL dev environment | **Resolved** |
| `pip install torch==2.5.1+cu124` failed with SSL "record layer" errors in this environment | Environment-specific SSL/proxy interaction with pip's downloader | `backend/scripts/download_torch.py` downloads the wheel via `requests` instead, then installs the local `.whl` | Dev environment setup | **Resolved (workaround)** — see §3 for the follow-on hygiene issue of the wheel being committed |
| Installing `types-PyYAML`/`types-requests` for mypy triggered a 15+ minute pip dependency-resolution backtrack through 100+ historical `botocore` versions | Transitive dependency chain: `ai2thor` → `aws-requests-auth` → wide `botocore` version range, incompatible with stub packages' constraints | Reverted; instead suppress mypy's `import-untyped` error per-module in `pyproject.toml` for `yaml`/`requests` only | Dev tooling / CI type-checking | **Resolved (documented tradeoff)** |
| Vision is not wired as a precondition to execution | Architectural decision (or an in-progress state) — execution resolves objects via simulator ground truth, not vision perception | N/A — documented as current behavior in `orchestrator.py` | Vision/Execution coupling | **By design / open question for Phase 8+** — flagging since it affects how "real-world" (non-simulator ground-truth) deployment would need vision to actually gate execution |
| Two orchestration loops (`TaskRunner`, `Orchestrator`) coexist | `TaskRunner` (single-attempt) predates `Orchestrator` (multi-attempt, reflection-driven); rather than migrate every caller, `TaskRunner` was kept for `memory_evaluation/`'s experiment harnesses which depend on its simpler, single-attempt contract | Both maintained deliberately, cross-documented | Orchestration / experiment reproducibility | **Resolved (intentional, not tech debt)** |

This list is necessarily partial — it reflects issues visible in code comments/docstrings, not a full history (no git log exists to mine commit messages from). If you have other Phase 1–7 incidents in mind that aren't visible in the code, tell me and I'll fold them in.

---

## 13–15. Final repository structure & architecture freeze

The existing structure is already correct and requires **no reorganization** — recommending against moving files purely for aesthetics, per your constraints. The frozen structure is:

```
backend/
  agents/            Phase 7 — thin uniform wrappers around each subsystem, driven by orchestration/
  api/                FastAPI HTTP boundary (routes/, models/) — translate-and-delegate only
  config/             Model registry + device selection (ModelConfig, ModelManager)
  execution/          Executes a validated Plan step-by-step against the simulator
  language/           NL -> ParsedInstruction (LLM call, parse, validate, repair)
  memory/             Structured + vector memory (agent -> retrieval -> manager/store -> semantics)
  orchestration/       Orchestrator (live, multi-attempt, reflection-driven) + TaskRunner (single-attempt, used by memory_evaluation/)
  planner/            RULE_BASED (live default) / REACT / BEHAVIOR_TREE strategies behind factory.py
  scene/              Shared vision data model (Scene, Detection, Mask, Relationship)
  schemas/            Task/instruction schemas shared across language, orchestration, api
  simulator/          Sole AI2-THOR integration boundary
  speech/             Whisper speech-to-text (opt-in)
  vision/             Detection (Grounding DINO) / segmentation (SAM2) / depth / tracking / scene graph
  evaluation/, memory_evaluation/, vision_evaluation/   Standalone offline benchmark harnesses (not runtime-imported)
  scripts/            One-off setup utilities (not imported at runtime)
  tests/              pytest suite (857 tests, CI-gated)
  prompts/            LLM prompt text + config (data, not code)
frontend/
  src/api/            One module per backend domain (tasks, agents, speech, language, vision, planner, execution)
  src/state/          React Context providers (Task, Agents, Speech, Settings)
  src/pages/, src/components/, src/hooks/, src/utils/
models/               Gitignored; populated on demand by ModelManager from HF Hub
datasets/             Tracked, hand-authored evaluation/prompt fixtures
experiments/, results/, benchmarks/   Benchmark run outputs + READMEs describing where the real runners live
docs/                 architecture/, phases/, testing/  (gaps noted in §10)
docker/, deployment/, .github/workflows/
```

**Data flow diagram**: see §2's pipeline listing — this is the frozen architecture for Phase 8.2 onward.

**Agent responsibility map**: `PlannerAgent` (plan), `VisionAgent` (perceive, optional), `MemoryAgent` (retrieve/remember), `ExecutionAgent` (execute + surface failures), `NavigationAgent` (refine execution failures into navigation-specific diagnoses), `ReflectionAgent` (decide continue/retry/replan/abort), `SpeechAgent` (opt-in transcription) — all driven by `Orchestrator`, none calling each other directly except through it.

**Memory architecture**: `MemoryAgent` (interface) → `RetrievalEngine` (embed → vector search → filter → score → rank) → `MemoryManager`+`store.py` (CRUD/persistence, SQLite) → `semantics.py` (typed content per `MemoryType`). One memory is written per task (not per attempt), only on a terminal outcome.

**Planner architecture**: `factory.create_planner(PlannerType)` selects among `RULE_BASED` (live default in the orchestrated pipeline), `REACT` (LLM-driven, falls back to rule-based), `BEHAVIOR_TREE` — all three reachable via `/api/v1/planner/*` for experimentation/evaluation, only `RULE_BASED` wired into `/api/v1/tasks`.

**Simulator abstraction**: `Simulator` (stable public wrapper) → `ai2thor_env.py` (actual `ai2thor.controller.Controller`, idempotent lifecycle) → `actions.py` (action vocabulary). Everything else in the codebase talks only to `Simulator`, enabling a future swap (Habitat/Isaac Sim/ROS2) without touching planner/vision/memory/execution.

**Frontend/backend interaction**: relative-URL REST calls only (`src/api/*.ts` → `/api/v1/...`), polling-based task status updates (`usePolling`/`useTaskHistory` hooks), no absolute URLs baked into the production bundle.

---

## 16. Cleanup actions executed

Executed on top of the baseline commit (`5c5257e`) plus the audit-report commit (`8f2e4da`), each change verified individually before moving to the next (§17). Nothing outside this list was touched.

1. **Untracked the 213MB `.whl`** (`git rm --cached backend/scripts/torch-2.5.1+cu124-cp39-cp39-linux_x86_64.whl`) — file kept on disk (still reproducible via `backend/scripts/download_torch.py`). Added `*.whl` to `.gitignore`.
2. **Untracked** `backend/outputs/memory/memory.db` and `backend/outputs/memory/vector_store/vectors.db` (`git rm --cached`) — both kept on disk (they're the live local memory store; deleting them would have wiped local runtime state, not just a git artifact). Extended `.gitignore` with `backend/outputs/**/*.db`.
   - **Bonus fix while verifying**: the pre-existing `outputs/*.png`/`*.jpg`/`*.jpeg`/`!outputs/.gitkeep` rules were themselves broken — a gitignore pattern containing a non-trailing slash is rooted at the `.gitignore`'s own directory (repo root here), so `outputs/*.png` only ever matched a top-level `outputs/` directory, never the actual `backend/outputs/`. Confirmed via `git check-ignore` returning no match even on a fresh throwaway file before the fix. Rewrote all four rules as `backend/outputs/*.png` etc. and reconfirmed with `git check-ignore -v` that they now match.
3. **Deleted** `backend/scripts/download_model.py` — confirmed 0 bytes and zero references anywhere in the repo (`grep -rn "download_model"` across `.py`/`.md`/`.yml`/`.toml`/`.json` returns nothing outside this report) before removal, per your "only if confirmed empty/unused" condition.
4. **`experiments/results/` policy** — inspected contents: `benchmark_20260809T120511Z.json` and `_episodes.csv` are directly cited by `experiments/reports/phase6_4_report.md` ("Generated from a real, reproducible run of [`experiments/results/benchmark_20260809T120511Z.json`]...") as that report's reproducibility source. **Decision: keep these two specific files tracked** (deleting/untracking them would break the report's citation and reproducibility), but ignore all *future* run output in that directory so it doesn't silently accumulate. Implemented as `experiments/results/*` + explicit `!` exceptions for the two cited files (same pattern already used for `results/`). Verified: the two cited files remain un-ignored; a throwaway new file in the same directory is correctly ignored.
5. **Updated `docker/README.md`** — replaced the stale "Phases 1-3.5 ... no FastAPI service (Phase 3.7+)" claim (which contradicted the Dockerfile's own header comment and `CMD`) with an accurate description read directly from `docker/Dockerfile`: build/run commands, that `COPY backend/ ./` packages the whole current backend tree (not a phase snapshot) so Phase 6/7 additions needed no Dockerfile change since they added no new dependency, the default `uvicorn` FastAPI entrypoint on port 8000, the `503 configuration_error` degrade-gracefully behavior for missing LLM keys, and the non-root `appuser`/frontend-excluded facts already true in the Dockerfile. Nothing invented — every claim added was cross-checked against `docker/Dockerfile`'s actual content.
6. **Added the ElevenLabs placeholder block** to `backend/.env.example`, disabled/commented by default, no code reading it yet:
   ```
   # ---- Voice output (ElevenLabs -- planned, not yet implemented) ----
   # Off by default; no code currently reads these. Reserved config
   # structure staged ahead of the Phase 8 voice integration -- the
   # voice ID is not a secret and is fixed for MILO, but never commit a
   # real ELEVENLABS_API_KEY value here or anywhere else.
   # ELEVENLABS_API_KEY=
   # ELEVENLABS_VOICE_ID=ISnQja0Ank6t1FE2Wj07
   ```
7. **Not done (correctly deferred)**: renaming the manual smoke-test scripts — judged unnecessary; they don't collide with CI (which scopes to `backend/tests/` only) and renaming ~10 files for a cosmetic ambiguity risk wasn't worth the diff noise right now.
8. **Not started (correctly deferred to Phase 8.5)**: the missing `docs/phases/phase3_language.md` / `phase7_agents_orchestration.md`.

## 17. Post-cleanup verification

All run after items 1–6, before committing:

- **`git status`**: exactly the 6 intended files changed (`​.gitignore`, `backend/.env.example`, `docker/README.md`, plus 4 untracked/removed: `memory.db`, `vectors.db`, `download_model.py`, the `.whl`) — `git diff --stat HEAD` confirms no other file was swept in. (One unrelated pre-existing local change, `.claude/settings.local.json`, is session tooling config, not part of this audit, and was left untouched.)
- **No files accidentally removed**: `ls -la` confirms the `.whl` and both `.db` files still exist on disk at their original sizes — only their git tracking changed, per your explicit "do not delete if still required locally" instruction.
- **`.gitignore` rules verified working**: `git check-ignore -v` confirms the `.whl`, both `.db` files, and a fresh throwaway `backend/outputs/*.png` test file are now correctly ignored; the two cited `experiments/results/*` files remain un-ignored while a fresh throwaway file in the same directory is correctly ignored.
- **Application startup**: `from api.app import app; TestClient(app).get("/health")` → `200 {"status": "ok", "llm_provider_configured": true}`.
- **Test suite**: `857 passed, 8 skipped, 0 failed` — identical to the pre-cleanup baseline (§9). No regressions.
- **Reference check**: `grep -rn "download_model"` across the repo returns no hits outside this report — nothing imports or calls the deleted script.
- **Secret scan**: diff of the three edited files checked for key/secret/token patterns — clean; `ELEVENLABS_API_KEY=` was added with no value, only the voice ID (not a secret) was filled in.

Everything else audited in §1–15 (dependencies, architecture, memory/planner/vision layering, logging, tests, model/dataset provenance) needed **no changes** — already at the baseline quality Phase 8.1 is meant to establish.
