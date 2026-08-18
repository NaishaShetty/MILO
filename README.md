# MILO

**Memory Integrated Language-Oriented Robot**

MILO is a research platform for embodied AI: a natural-language
instruction is understood, planned, and executed by a simulated robot
in [AI2-THOR](https://ai2thor.allenai.org/), with every stage — vision,
language, memory, planning, execution, and reflection — implemented as
an independently testable, swappable module rather than a monolithic
pipeline.

## Overview

Most "vision-language robotics" demos wire a single detector directly
into a single policy, which makes it hard to answer basic research
questions in isolation — does memory actually help planning? does a
different planning strategy change task success? MILO is built the
other way: perception, language understanding, memory, planning,
execution, and reflection are separate modules behind small, consistent
interfaces, so each can be evaluated and swapped independently.

**Research question:** Can a modular embodied agent — with
independently swappable perception, language-understanding, planning,
execution, memory, and reflection stages — perceive an AI2-THOR scene,
understand a natural-language instruction, retrieve and use relevant
past experience, generate and validate a multi-step plan, execute it
with step-by-step precondition/result checking against simulator
ground truth, detect its own execution failures, and replan in
response — producing a structured, traceable record of every decision
along the way?

This is scoped to what the implemented system can actually
demonstrate: it's a question about *architecture and integration*, not
about generalization across many environments (see
[Known Limitations](#known-limitations)).

## What MILO Can Do

* **Perception** — open-vocabulary object detection (Grounding DINO),
segmentation (SAM2), depth estimation, and a heuristic spatial scene
graph over live AI2-THOR frames.
* **Spatial/temporal understanding** — 2D→3D object localization,
cross-frame object tracking, and scene-change detection (new/moved/
removed/occluded objects).
* **Language understanding** — natural-language instructions parsed
into structured goals via a real LLM call (not rule-based NLU).
* **Planning** — three interchangeable strategies behind one interface:
a deterministic rule-based planner, an LLM-driven ReAct planner, and
a Behavior Tree planner, each validated against a symbolic world
model.
* **Execution** — plans are driven step by step through real AI2-THOR,
with preconditions checked before every action and results validated
against simulator ground truth, never assumed.
* **Memory** — episodic, semantic, and failure memory, persisted in
SQLite with ranked vector retrieval, read and written on every real
task.
* **Reflection \& replanning** — execution failures are classified and
drive a real `continue`/`retry`/`replan`/`abort` decision, bounded to
avoid infinite loops.
* **Speech** — Whisper (local) and ElevenLabs (cloud) speech-to-text,
and ElevenLabs text-to-speech for MILO's spoken responses.
* **Frontend dashboard** — a 7-page real-time UI (Home, Mission
Control, Memory, Activity, About, MILO Lab, Settings) showing live
backend state, not mocked data.
* **LLM provider abstraction** — OpenAI, Google Gemini, or a local
Qwen-compatible server, selected purely through configuration.

Only capabilities that are actually implemented and verified are
listed here — see [Known Limitations](#known-limitations) for what
isn't.

## Tech Stack

**Backend** — Python, FastAPI + Uvicorn (API layer), Pydantic (data
models), AI2-THOR (simulated environment), Grounding DINO (open-vocab
detection), SAM2 (segmentation), SQLite + a vector store (memory
persistence), OpenAI / Google Gemini / local Qwen-compatible server
(pluggable LLM providers), OpenAI Whisper (local STT), ElevenLabs
(cloud STT + TTS), pytest (test suite).

**Frontend** — React + TypeScript, built with Vite, react-router-dom
(routing across 7 pages), Vitest + Testing Library (unit/component
tests), Playwright (real-browser E2E tests). No CSS or UI component
framework — a single hand-authored design system. No state-management
library beyond React Context (six purpose-built polling contexts).

**Infrastructure** — Docker + docker-compose (containerized
backend/frontend), nginx (frontend production serving), GitHub Actions
(CI: format/lint/type-check/test on every push and PR).

**Explicitly not used** — no WebSocket/SSE (all real-time UI updates
are polling-based), no message queue/event bus between agents (direct
method calls through a single `Orchestrator`), no ORM.

Full stack detail: [`docs/application/tech\\\_stack.md`](docs/application/tech_stack.md).

## Architecture

```mermaid
flowchart LR
    User(\\\["User<br/>text or speech"]) --> Lang\\\["Language<br/>Understanding"]
    Lang --> Memory\\\["Memory"]
    Lang --> Planner\\\["Planner"]
    Memory <--> Planner
    Planner --> Vision\\\["Vision"]
    Planner --> Nav\\\["Navigation"]
    Planner --> Exec\\\["Execution"]
    Vision --> Exec
    Nav --> Exec
    Exec --> Sim\\\["AI2-THOR"]
    Sim --> Reflect\\\["Reflection"]
    Reflect -->|replan| Planner
    Reflect --> Memory
    Memory --> User
```

A single `Orchestrator` runs this loop for every task: parse → retrieve
memory → plan → observe/execute → reflect → replan (bounded) or finish
→ write memory. Every step publishes a real event the frontend polls
and renders live.

For the full agent/frontend architecture (with diagrams of the real,
verified implementation) see
[`docs/application/architecture.md`](docs/application/architecture.md).
For the historical Phase 2–5 pipeline design (perception, language,
planning, execution in implementation detail) see
[`docs/architecture/pre\\\_orchestrator\\\_pipeline\\\_snapshot.md`](docs/architecture/pre_orchestrator_pipeline_snapshot.md).

## Research Contributions

|Type|Contribution|
|-|-|
|Research|A modular agent architecture with an explicit failure taxonomy and a reflection step that decides `continue`/`retry`/`replan`/`abort` from structured execution failures, not a hardcoded retry count|
|Research|A memory system with distinct episodic, semantic, and failure memory types, ranked retrieval (similarity + confidence + recency + provenance + context), and an honestly-labeled memory-vs-no-memory ablation|
|Research|A provider-agnostic LLM abstraction letting the same planner/agent code run against OpenAI, Gemini, or a local OpenAI-compatible server purely through configuration|
|Engineering|Three interchangeable planner strategies behind one interface, with shared plan validation against a symbolic world model|
|Engineering|A real-time frontend driven entirely by backend polling, with no fabricated/mocked state in production paths|
|Product|MILO Lab — a research interface exposing perception benchmarks, planner evaluation, and a parse/plan sandbox as real, runnable operations|

See [`docs/phases/phase8\\\_7\\\_final\\\_audit.md`](docs/phases/phase8_7_final_audit.md)
for the full research-contribution breakdown and final evaluation.

## Current Results

* **Tests**: backend `917 passed, 2 skipped, 0 failed` (~6 seconds);
frontend `186 passed, 0 failed` (29 files); production build clean.
`backend/tests/conftest.py` forces `VISION_ENABLE_SIMULATOR=false` for
the whole suite regardless of a local `.env`'s interactive-dev setting
— no manual env-var step needed to get a clean, fast run.
* **Real AI2-THOR mission, driven through the actual UI** (not a mocked
test): found and fixed a critical bug where the orchestrator/plan
validator ignored the LLM's parsed `target\\\_location`, causing every
"put/place X in/on Y" instruction to fail 100% of the time. Fixed and
re-verified live — a second run correctly resolved the target,
planned, and executed against real AI2-THOR, but still ended in
`failed` after one real replan: AI2-THOR correctly rejected placing
into a closed receptacle, exposing a separate, pre-existing gap in
the rule-based planner's "place" template. Since fixed: `\\\_deposit()`
now inserts an `open` step whenever the destination's current
`WorldState.is\\\_open` is known `False` (and skips a redundant `open`/
`close` when it's already known `True`) — see
`backend/planner/rule\\\_based.py`.
* **Frontend↔backend connectivity**: every dynamic value on every page
traces to a real backend route; no fabricated data found in any
production path; polling correctly cancels on unmount.
* **Memory benchmark finding**: on a controlled `FakeSimulator`
ablation, memory reduced task success 90% → 80% and increased mean
actions, because the rule-based planner's memory hint adds a step
rather than replacing one, and because stale memory isn't overridden
by live perception end-to-end.
* **Same ablation, re-run for real** (real AI2-THOR + a real learned
sentence-embedding model, not `FakeSimulator`/a lexical embedder):
the 90%→80% drop did **not** reproduce — 16/16 episode pairs showed
zero success/action delta between memory on and off. Traced to a
real, more interesting root cause: the memory-conditioned
location-hint mechanism the FakeSimulator finding depends on never
actually engages under real AI2-THOR, because forming a qualifying
memory requires AI2-THOR's `parentReceptacle` metadata, which is
`None` for every loose, pickupable object in this scene's default
layout (confirmed directly, not inferred). The mechanism itself
works — proven under `FakeSimulator` and mechanically triggered in
this real run's closed-receptacle scenarios — it's just structurally
inert for this specific object-placement case today. Full writeup:
[`experiments/reports/phase\\\_b\\\_real\\\_ablation\\\_findings.md`](experiments/reports/phase_b_real_ablation_findings.md).
* **Planner/replanning**: reflection and dynamic replanning are real
and were observed live (see the mission result above), not merely
implemented-but-untested.
* **`milo_benchmark v1.0`** — a versioned, 25-task, 5-scene (all 4
iTHOR room types), 3-tier dataset with a reproducible runner, scored
against **live** post-execution AI2-THOR state (not just "did nothing
error"). Real planner-comparison baseline:

  | Planner | Goal success | tier1 (locate) | tier2 (pickup) | tier3 (store) |
  |---|---|---|---|---|
  | `rule_based` | 24/25 (96%) | 10/10 | 10/10 | 4/5 |
  | `behavior_tree` | 24/25 (96%) | 10/10 | 10/10 | 4/5 |
  | `react` (`qwen2.5:7b`, local, via Ollama) | 20/25 (80%) | 10/10 | 10/10 | 0/5 |

  Both symbolic planners' one remaining failure is a real AI2-THOR
  placement/geometry limit, not a planner bug (two other failures —
  a `_deposit()` bug and a misleading timeout message — were found by
  this benchmark and fixed; see roadmap below). `react`'s baseline is
  real and clean (`goal_success`/`execution_success`/`plan_success`
  agree on every episode, zero rate-limit retries needed) — run
  locally against `qwen2.5:7b` (Q4_K_M) served by Ollama on an RTX
  4050 Laptop GPU, after an earlier attempt against Gemini's free tier
  hit that tier's daily quota (20 requests/day) after 2 of 25
  episodes and produced no usable number. All 5 `react` failures are
  genuine multi-step reasoning mistakes (proposing an action before
  its precondition chain is satisfied), not infrastructure. Full
  methodology, the memory-hint fix (now confirmed engaging on 5/5
  real-AI2-THOR recall episodes, was 0/5), and both the failed-Gemini
  and successful-local-Qwen ReAct attempts in full detail:
  [`experiments/reports/phase_e_milo_benchmark_report.md`](experiments/reports/phase_e_milo_benchmark_report.md).
  Dataset card:
  [`backend/planning_evaluation/dataset/v1.0/README.md`](backend/planning_evaluation/dataset/v1.0/README.md).

Full detail, methodology, and provenance:
[`docs/phases/phase8\\\_7\\\_final\\\_audit.md`](docs/phases/phase8_7_final_audit.md).

## Known Limitations

* **AI2-THOR only** — no physical robot validation; all execution
results are simulator results.
* **Scene diversity validated but shallow** — a `milo_benchmark v1.0`
5-scene sweep (all 4 iTHOR room types, 3 tasks each) found object
resolution, navigation, and pickup generalize cleanly (24/25 on both
symbolic planners); 5 of ~120 iTHOR scenes is a first real number, not
a statistically powered study. See the Current Results table above.
* **Vision grounding covers existence/location only, not full state
fusion** — `Orchestrator` now grounds the planner's `WorldState`
from a live Vision `Scene` before planning (`backend/planner/ grounding.py`), but only existence (`is\\\_located`), proximity
(`is\\\_near\\\_robot`), and containment (`location`, from scene-graph
`INSIDE` edges); `is\\\_open`/`is\\\_held` are still symbolic-only, since
vision doesn't yet observe grasp or appearance state.
* **Memory's location-hint mechanism** now engages under real AI2-THOR
(fixed: it reads AI2-THOR's `parentReceptacles` metadata field instead
of the always-empty deprecated singular one) — confirmed on 5/5 real
recall episodes across all 5 benchmark scenes; see the Phase B
findings doc above for the original finding and its resolution
addendum.
* **HTN planning was never implemented**, despite being one of the
originally scoped planning strategies.
* **External API dependence** — LLM providers and ElevenLabs are paid
third-party services; nothing here works fully offline.
* **No production authentication, rate limiting, or request quotas**
on any API route.

Full, honest detail:
[`docs/application/limitations.md`](docs/application/limitations.md) and
[`docs/phases/phase8\\\_7\\\_final\\\_audit.md`](docs/phases/phase8_7_final_audit.md).

## Quick Start

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in an LLM provider key -- see Configuration below
uvicorn api.app:app --reload
# -> http://localhost:8000 (docs at /docs, health at /health)

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
# -> http://localhost:5173

# Tests
cd backend \\\&\\\& python -m pytest tests/ -v
cd frontend \\\&\\\& npm test \\\&\\\& npm run build
```

For the full per-phase test/benchmark command reference and the
Playwright browser E2E suite, see
[`docs/testing/running\\\_tests.md`](docs/testing/running_tests.md).

## Configuration

The backend reads its configuration from the environment
(`backend/language/config.py`, `backend/voice/config.py`); every
setting has a sensible default except the API key itself.

```bash
# LLM provider -- "openai" (default), "gemini", or "qwen" (local)
export LANGUAGE\\\_LLM\\\_PROVIDER="gemini"
export GEMINI\\\_API\\\_KEY="..."          # or OPENAI\\\_API\\\_KEY for openai,
                                       # or QWEN\\\_API\\\_KEY for a local server

# AI2-THOR simulator -- off by default (most of the API 503s without it)
export VISION\\\_ENABLE\\\_SIMULATOR="true"

# Speech -- Whisper (local, default) or ElevenLabs (cloud)
export SPEECH\\\_ENABLE\\\_WHISPER="true"
export VOICE\\\_ENABLE\\\_ELEVENLABS="true"
export ELEVENLABS\\\_API\\\_KEY="..."
```

Switching LLM providers is a one-variable change — no planner or
orchestrator code depends on which provider is selected. Local Qwen
(or any OpenAI-API-compatible server, e.g. vLLM/Ollama) reuses the same
client the OpenAI provider uses.

Full configuration reference (every variable, every default, provider
setup walkthroughs, and the security model):
[`docs/phases/phase8\\\_5\\\_configuration\\\_and\\\_providers.md`](docs/phases/phase8_5_configuration_and_providers.md).
Deployment/Docker: [`docker/README.md`](docker/README.md) and
[`deployment/README.md`](deployment/README.md).

## Deployment

**MILO is not currently deployed publicly.** Running it against a real
GPU host turned out to require infrastructure (a dedicated CUDA-capable
machine, always-on hosting) that isn't feasible to maintain at this
stage, so the project's priority right now is local reproducibility --
anyone cloning this repo can run the full stack on their own machine
via [Quick Start](#quick-start).

The deployment configuration below is real and was build/run-verified
against a real backend, but is not currently running anywhere public:

* **Frontend**: a static Vite build, deployable to Vercel --
[`frontend/README.md`](frontend/README.md#deployment-vercel) and
`frontend/vercel.json`.
* **Backend**: a GPU-enabled Docker image (`docker/Dockerfile.gpu`,
CUDA 12.1 + headless AI2-THOR `CloudRendering`) and
`docker-compose.prod.yml`, which fronts it with a Cloudflare Quick
Tunnel (no purchased domain required) rather than a public port. It
is **not** deployable to Vercel: task execution runs in a background
thread inside the FastAPI process (`backend/api/routes/tasks.py`)
that outlives the triggering request, `MemoryConfig`/
`SQLiteMemoryStore` persist to a local file
(`backend/outputs/memory/memory.db`), and
`VISION\\\_ENABLE\\\_SIMULATOR=true` launches a real AI2-THOR/Unity
subprocess (`backend/api/app.py`'s lifespan) -- none of which
survive Vercel's stateless, short-lived-per-request serverless
execution model.

Wherever the backend runs, point the frontend at it via
`frontend/vercel.json`'s rewrites and add the frontend's deployed
origin to that backend's `API\\\_ALLOWED\\\_ORIGINS`.

## Project Structure

```
backend/        FastAPI app, agents, orchestration, planner, memory,
                 vision, execution, simulator wrapper, tests
frontend/        React + TypeScript dashboard (Vite)
docs/            Architecture, phase history, testing, application docs
datasets/        Language understanding evaluation datasets
models/          Downloaded model weights (gitignored)
experiments/     Research experiment runners and results
benchmarks/      Reproducible evaluation suite entry points
deployment/      Environment/target-specific deployment config
docker/          Container definitions (backend + frontend)
```

## Roadmap

|Item|Status|
|-|-|
|Core pipeline (perception → language → planning → execution → memory → reflection)|✅ Done|
|MILO frontend, voice, MILO Lab|✅ Done|
|Memory threaded into the ReAct/LLM planner|✅ Done|
|Rule-based planner closed-receptacle fix|✅ Done|
|Memory ablation re-run on real AI2-THOR + real embedder|✅ Done|
|Vision-grounded planner world model (existence/location grounding)|✅ Done|
|Floor-plan generalization sweep (5 scenes, all 4 iTHOR room types)|✅ Done|
|`milo_benchmark v1.0` dataset + runner (planner comparison, memory ablation, live goal-check scoring)|✅ Done|
|`_deposit()` non-openable store-target bug|✅ Fixed|
|Misleading `ACTION_TIMEOUT` message|✅ Fixed|
|Memory-hint `parentReceptacle` gap|✅ Fixed|
|Real `ReActPlanner` baseline on `milo_benchmark`|✅ Done — 20/25 (80%) via local `qwen2.5:7b`/Ollama, after Gemini's free tier proved unworkable|
|Test-suite `VISION_ENABLE_SIMULATOR` env-leak fix (`conftest.py`)|✅ Fixed — also cut the full suite from ~13min to ~6s|
|Full vision state fusion (open/held state)|🔜 Future|
|Publish `milo_benchmark` to the Hugging Face Hub|🔜 Future|
|HTN planner|🔜 Future|
|Production auth/rate limiting|🔜 Future|

Full roadmap with rationale for every open item:
[`docs/roadmap.md`](docs/roadmap.md).

## Documentation

* [`docs/application/architecture.md`](docs/application/architecture.md) — current system \& agent architecture
* [`docs/application/overview.md`](docs/application/overview.md) — what MILO does, in detail
* [`docs/application/tech\\\_stack.md`](docs/application/tech_stack.md) — full technology stack
* [`docs/application/limitations.md`](docs/application/limitations.md) — honest, detailed limitations
* [`docs/architecture/perception\\\_pipeline.md`](docs/architecture/perception_pipeline.md) — perception design
* [`docs/architecture/spatial\\\_perception.md`](docs/architecture/spatial_perception.md) — depth/tracking/temporal scene
* [`backend/docs/language\\\_interface\\\_spec.md`](backend/docs/language_interface_spec.md) — language interface spec
* [`docs/architecture/planning.md`](docs/architecture/planning.md) — planner architecture
* [`docs/phases/phase5\\\_execution.md`](docs/phases/phase5_execution.md) — execution architecture
* [`docs/phases/phase6\\\_memory.md`](docs/phases/phase6_memory.md) — memory system design
* [`docs/architecture/reflection.md`](docs/architecture/reflection.md) — reflection/replanning design
* [`docs/architecture/api\\\_contracts.md`](docs/architecture/api_contracts.md) — full API endpoint reference
* [`docs/phases/phase8\\\_7\\\_final\\\_audit.md`](docs/phases/phase8_7_final_audit.md) — final research-readiness audit
* [`docs/testing/running\\\_tests.md`](docs/testing/running_tests.md) — full test/benchmark command reference
* [`docs/development\\\_history.md`](docs/development_history.md) — phase-by-phase development narrative
* [`docs/repository\\\_structure.md`](docs/repository_structure.md) — full module-by-module repository map
* [`docker/README.md`](docker/README.md) / [`deployment/README.md`](deployment/README.md) — deployment

## Screenshots

All screenshots below are real renders of the actual frontend/backend
code -- see [`docs/screenshots/README.md`](docs/screenshots/README.md)
for exactly which are captured against a live backend + real AI2-THOR
run versus a mocked API response used to reliably reproduce a specific
UI state (e.g. "plan mid-execution"). Neither category fabricates data
values; the mocked set only fixes *which* real UI state renders.

**A real mission, driven through the actual UI** (live AI2-THOR, real LLM parse, real plan/execution):

|Instruction typed|Executing|Complete|
|-|-|-|
|!\[Instruction typed](docs/screenshots/demo/live-01-instruction-typed.png)|!\[Task in progress](docs/screenshots/demo/live-02-task-in-progress.png)|!\[Task complete](docs/screenshots/demo/live-03-task-complete.png)|

**Mission Control** (agent status, live plan, activity feed):

!\[Mission Control](docs/screenshots/ui/mission-control.png)

**Memory** (episodic/semantic/failure memory, real retrieval):

!\[Memory](docs/screenshots/ui/memory.png)

**Home**, **Activity**, **MILO Lab**, **About MILO**, **Settings**:

|Home|Activity|
|-|-|
|!\[Home](docs/screenshots/ui/home.png)|!\[Activity](docs/screenshots/ui/activity.png)|

|MILO Lab|Settings|
|-|-|
|!\[MILO Lab](docs/screenshots/ui/lab.png)|!\[Settings](docs/screenshots/ui/settings.png)|

## License

No license file is currently included in this repository.

