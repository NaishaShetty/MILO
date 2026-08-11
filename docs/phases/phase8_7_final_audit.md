# Phase 8.7 — Final Research Readiness Audit

> Moved here from the README during the Phase 8.7 README restructure
> (2026-08-11) to keep the root README concise. This is the full,
> unedited audit; the README's "Current Results" and "Known
> Limitations" sections summarize it.

### Research Question

Can a modular embodied agent -- with independently swappable
perception, language-understanding, planning, navigation, execution,
memory, and reflection stages -- perceive an AI2-THOR scene, understand
a natural-language instruction, retrieve and use relevant past
experience, generate and validate a multi-step plan, execute it with
step-by-step precondition/result checking against simulator ground
truth, detect its own execution failures, and replan in response --
producing a structured, traceable record of every decision along the
way? This is deliberately scoped to what the implemented system and
its experiments can actually evaluate: it is a question about
*architecture and integration*, not about generalization across many
environments (the platform runs against AI2-THOR's `FloorPlan1` by
default; see Limitations).

### Research Contributions

| Type | Contribution |
|---|---|
| **Research** | A modular agent architecture with an explicit, inspectable failure taxonomy and a reflection step that decides `continue`/`retry`/`replan`/`abort` from structured execution failures rather than a hardcoded retry count (`backend/agents/reflection_agent.py`, `backend/orchestration/orchestrator.py`) |
| **Research** | A memory system with distinct episodic, semantic, and failure memory types, ranked retrieval (similarity + confidence + recency + provenance + context, `backend/memory/retrieval.py`), and an honestly-labeled ablation harness comparing memory-on vs memory-off behavior (`experiments/results/benchmark_20260809T120511Z.json`, run against a documented `FakeSimulator`, not production AI2-THOR -- see Limitations) |
| **Research** | A provider-agnostic LLM abstraction (`backend/language/provider_factory.py`) letting the same planner/agent code run against OpenAI, Gemini, or a local OpenAI-compatible server (Qwen/vLLM/Ollama) purely through configuration |
| **Engineering** | Three interchangeable planner strategies behind one interface (`RuleBasedPlanner`, `ReActPlanner`, `BehaviorTreePlanner`, `backend/planner/factory.py`) with shared plan validation (`backend/planner/validator.py`) against a symbolic `WorldState` |
| **Engineering** | A real-time frontend (7 pages) driven entirely by backend polling with no fabricated/mocked state in production paths (verified route-by-route in the Phase 8.7 connectivity audit below) |
| **Product** | MILO Lab -- a research interface exposing perception benchmarks, planner evaluation, and a parse/plan sandbox as real, runnable operations rather than static mockups |
| **Product** | Voice interaction (ElevenLabs TTS, Whisper/ElevenLabs STT) with the API key resolved server-side only, never exposed to the frontend |

### Verified System Capabilities (as of this audit)

Confirmed by direct code inspection and a real, live run (backend
pytest, frontend vitest/build, and one real AI2-THOR mission driven
through the actual browser UI -- not a mocked test):

- **Data flow is real end to end**: `Orchestrator.run()`
  (`backend/orchestration/orchestrator.py`) genuinely executes
  Language → Memory retrieval → Planning → (Vision/Execute loop) →
  AI2-THOR → Reflection → Memory write, and every step publishes a
  real event consumed by the frontend's Activity Feed.
- **Planners**: `RULE_BASED`, `REACT` (real Gemini/OpenAI-backed LLM
  loop with fallback to rule-based on LLM failure), and
  `BEHAVIOR_TREE` are all implemented (`backend/planner/factory.py`).
  **HTN is not implemented** despite being one of this project's
  originally scoped planning strategies.
- **Memory**: episodic, semantic, and failure memory types exist and
  are wired into the orchestrator (not a standalone, unused module) --
  `_retrieve_memory`/`_remember_terminal` in `orchestrator.py`
  genuinely read and write memory on every real task.
- **Reflection and replanning are real**: confirmed live during the
  audit's E2E mission run below (`replans: 1`, driven by a real
  AI2-THOR execution error, not a scripted failure).
- **LLM provider abstraction is real**, not OpenAI-hardcoded:
  `LANGUAGE_LLM_PROVIDER=openai|gemini|qwen` all resolve to working
  client classes (`backend/language/provider_factory.py`); this
  deployment's default is Gemini.
- **Voice**: ElevenLabs TTS/STT and Whisper STT are both wired; the
  configured voice ID default (`ELEVENLABS_VOICE_ID`) is
  `ISnQja0Ank6t1FE2Wj07`, resolved from the environment server-side
  only (`backend/voice/config.py`, `backend/voice/elevenlabs_client.py`).
- **Frontend↔backend connectivity**: every dynamic value on every one
  of MILO's 7 pages (Home, Mission Control, Memory, Activity, About,
  MILO Lab, Settings) traces to a real backend route with no
  mock/fake/fabricated data in a production code path; polling
  (`frontend/src/hooks/usePolling.ts`) correctly cancels on unmount.
  The only non-live UI content is explicitly-static copy (example
  prompts, the About page, architecture diagrams) -- never presented
  as live state.

### Real End-to-End Mission (verified through the actual UI)

Run live during this audit: backend started with
`VISION_ENABLE_SIMULATOR=true` (real AI2-THOR, `FloorPlan1`), real
Gemini configured, frontend dev server driving the actual browser UI
via Playwright (typing into the real "Talk to MILO" box and clicking
the real send button -- backend internals were never called directly).
"Bring me the red mug" was **not used**: no fixture or scene metadata
in this repository shows a Mug object actually present in
`FloorPlan1` (only `Apple` and `Fridge` are runtime-verified present,
via `backend/simulator/test_execution_e2e.py`), so the audit used
**"Put the apple in the fridge"** instead and documents that
substitution here rather than presenting an unverified object as a
working example.

**First run found a critical, reproducible bug**: the LLM parsed the
instruction correctly (`goal=pick_and_place`, `object=apple`,
`target_location=fridge`), but `Orchestrator.run()`
(`orchestration/orchestrator.py`, then line 177) only copied
`task.target` into `TaskState`, never `task.target_location`, so
`target` came out `null` and planning failed in ~2ms with no plan ever
generated. `planner/validator.py`'s `_goal_store()` had the same gap.
Net effect: **every "put/place X in/on Y" instruction with no
secondary object -- the platform's own suggested example prompts --
failed 100% of the time.** This was fixed (both call sites now fall
back to `target_location`, consistent with how
`planner/rule_based.py`'s own `_goal_place` already handled it) and
verified with a second live run:

- Task created, memory retrieval ran, planning succeeded with
  `target="fridge"` correctly resolved.
- A 6-step rule-based plan executed against real AI2-THOR: locate →
  navigate → pick up apple → locate → navigate → place apple in
  fridge.
- Real AI2-THOR rejected the final placement
  (`"Target openable Receptacle is CLOSED, can't place if target is
  not open!"`) -- reflection correctly classified this as a
  recoverable `ACTION_FAILURE` and triggered one real replan.
- The replanned attempt hit the same failure and the mission ended in
  `status: failed` after 2 attempts / 12 actions / 1 replan (~26s
  total).

This is an honest, traceable result, not a fabricated success: the
critical parsing bug is fixed and confirmed working end to end, but it
surfaced a **separate, pre-existing planner limitation** -- the
rule-based planner's "place" plan template never inserts an
open-receptacle step before placing into a closed container. That gap
was not fixed in this pass (it's a planner-logic change, not the
narrow bug this audit was scoped to correct) and is recorded under
Limitations below.

### Test Suite Results (this audit)

- Backend: `python -m pytest -q` → **893 passed, 8 skipped, 0 failed**
  (previous audited baseline: 857 passed, 8 skipped, 0 failed -- net
  new tests, no regressions).
- Frontend: `npm test` (vitest) → **181 passed, 0 failed** across 29
  test files.
- Frontend production build (`npm run build`, `tsc --noEmit && vite
  build`): succeeds cleanly.

### Limitations (honest, as of this audit)

- **AI2-THOR simulation gap**: nothing in this system has been
  validated on a physical robot; all execution results are simulator
  results.
- **Single default scene**: the platform runs against `FloorPlan1` by
  default; broader environment/task diversity is unvalidated.
- **Rule-based planner's "place" template can fail against closed
  receptacles** (see the mission run above) -- a real, reproduced gap,
  not yet fixed.
- **ReAct planner does not consume retrieved memory**: `memory_context`
  is accepted by `ReActPlanner.plan()` but not threaded into the LLM
  prompt (`backend/planner/react.py`); only the rule-based fallback
  path benefits from memory today, so "memory improves planning"
  claims apply to that path only, not the LLM planner.
- **Memory-vs-no-memory benchmark results run on a fake harness**:
  `experiments/results/benchmark_20260809T120511Z.json` is explicit
  that it uses `FakeSimulator` (a deterministic in-memory fake, not
  real AI2-THOR) and `HashingEmbedder` (a deterministic lexical
  embedder, not a learned model) -- good research hygiene (it's
  labeled, not hidden), but it means those specific numbers describe a
  simplified harness, not the full stack.
- **HTN planning was never implemented**, despite being part of this
  project's originally scoped planning strategies.
- **Two orchestration entry points coexist**:
  `backend/orchestration/orchestrator.py` (current, used by the API)
  and an older `backend/orchestration/task_runner.py` (single-attempt,
  kept for backward compatibility) -- unexplained duplication worth
  resolving in a future pass.
- **External-service dependence**: ElevenLabs and the LLM providers are
  paid third-party APIs; this audit's real-mission and real-parse
  tests depended on live credentials being present in the local,
  gitignored `backend/.env` and are not something CI can reproduce
  without its own credentials.
- **No statistical claims are made from a single run**: the one real
  E2E mission and the existing benchmark artifacts each represent
  their own documented run count -- see each result's own methodology
  section for sample size before treating any number as more than
  illustrative.

### Final Research Evaluation

**Does the system answer its research question?** Partially and
honestly: the full pipeline genuinely executes end to end against real
AI2-THOR with real memory, real reflection, and real replanning --
this was directly observed, not inferred from code reading alone. What
it does *not* yet demonstrate is memory measurably improving the
LLM-driven planning path (ReAct doesn't consume it), or robustness
across scenes/tasks beyond the one default environment.

**Strongest contribution**: the orchestration architecture itself --
a clean separation of concerns (planner / memory / execution /
reflection) wired together in a way that a single live mission could
be traced end to end through every layer with a real, inspectable
event log, memory read/write, and failure classification.

**What remains experimental**: memory's effect on the LLM planning
path, planner comparison beyond what `experiments/reports/` already
documents, and any claim of generalization beyond `FloorPlan1`.

**Release verdict**: **READY WITH DOCUMENTED LIMITATIONS.** The one
critical blocker found during this audit (the primary mission flow
failing 100% of the time) was fixed and re-verified live; the
remaining gaps above are real but do not block using the system as
what it is -- a working, traceable embodied-agent research platform,
not a finished product with universal task coverage.

