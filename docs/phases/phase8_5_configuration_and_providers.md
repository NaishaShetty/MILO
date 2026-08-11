# Phase 8.5 — Configuration, Local Qwen Provider, STT Switch, Reproducibility

Status: **Stage 1 and Stage 2 complete.** The full Phase 8.5 spec (44
sections, plus a follow-up completion prompt) is not attempted in one
pass — see "Explicit deferrals" below.
Plan: `/home/naishashetty/.claude/plans/crispy-tumbling-kahn.md`.

**Stage 2 additions** (interruption/race-condition fixes, new docs):
a generation-guard fix for a real stale-transcription race in
`SpeechContext.tsx`; `VoiceContext.stop()` + barge-in wiring in
`TalkToMilo.tsx`; a context-level re-entrancy guard on
`TaskContext.submitInstruction()`; a new
`frontend/src/state/MiloStateContext.test.tsx`; an HTTP API reference
addendum in `docs/architecture/api_contracts.md`; new
`docs/architecture/milo_state_system.md` and `docs/troubleshooting.md`;
and this section. See §7 below for the reproducibility/experiment
consolidation, and the Stage 2 completion report (delivered in-thread)
for full test/validation results.

---

## 0. Why this document exists, and what it corrects

The Phase 8.5 spec assumes a project earlier in its lifecycle than this
repository actually is. A grounding survey done before any code changed
found that the LLM provider abstraction, ElevenLabs TTS, and the MILO
state machine were **already built and wired to real application
state**, not stubs. This document records the actual state of the
system after Stage 1's additions, using the real implementation as the
source of truth — it does not restate spec sections that were already
true before this stage started.

---

## 1. Configuration architecture (as it actually exists)

There is no single, centralized `pydantic.Settings` object. Each
backend package owns its own configuration:

```
Environment (.env / shell / docker run -e)
    │
    ├── language/config.py   → LLMRuntimeConfig, PromptAssetPaths, RecoveryConfig
    ├── voice/config.py      → VoiceConfig (ElevenLabs)
    ├── speech/config.py     → SpeechConfig (Whisper + Phase 8.5's STT_PROVIDER)
    ├── memory/config.py     → MemoryConfig
    └── vision/…, api/app.py → simulator/CORS settings
            │
            ▼
    api/app.py's `_lifespan` (FastAPI startup)
      constructs each config's `.from_env()` once, stores both the
      config *and* the derived agent/client on `app.state`
            │
            ▼
    Safe, secret-free status routes
      GET /api/v1/language, GET /api/v1/speech, GET /api/v1/voice
            │
            ▼
    Frontend Settings page (LLM Provider / Speech & Voice cards)
```

This is a deliberate pattern (see each `config.py`'s own module
docstring): every config class is a frozen dataclass with a
`from_env()` classmethod, an API key is only ever stored as the *name*
of the environment variable holding it (never the value), and the key
itself is resolved from `os.environ` at call time, immediately before
a network request, inside the client that needs it. Stage 1 extends
this pattern (adding `stt_provider` to `SpeechConfig`, adding a `qwen`
branch to `LLMRuntimeConfig`) rather than replacing it with a
monolithic `Settings` class — replacing it would touch every consumer
of every existing config module for no behavioral gain.

---

## 2. LLM provider abstraction

```
                 LLMClient (Protocol)
                     │
        ┌────────────┼────────────────────┐
        ↓            ↓                    ↓
  OpenAICompatible  Gemini             OpenAICompatible
   LLMClient        LLMClient           LLMClient
  (provider="openai") (provider="gemini") (provider="qwen")
```

`backend/language/provider_factory.py::create_llm_client()` is the
only place that branches on `provider`. `LanguageAgent` and everything
above it depend only on the `LLMClient` protocol
(`backend/language/llm_client.py`) — switching providers is exactly a
`LANGUAGE_LLM_PROVIDER` environment variable change, never a planner
or orchestrator code change.

**Local Qwen (Stage 1 addition)**: a local/self-hosted server (vLLM,
Ollama, ...) exposing an OpenAI-compatible chat-completions endpoint
is reached through the exact same `OpenAICompatibleLLMClient` the
`openai` provider already uses — no new client class. Defaults:
`LANGUAGE_LLM_MODEL=qwen2.5-7b-instruct`,
`LANGUAGE_LLM_BASE_URL=http://localhost:8000/v1` (vLLM's default),
`QWEN_API_KEY` as the credential env var name (many local servers
don't check it — set any placeholder value if so). See the root
README's "Local Qwen / local LLM" section for setup commands.

**Provider status**: `GET /api/v1/language` reports
`{provider, model, configured, available}` — `configured` is `True`
only if the resolved API-key environment variable is currently
non-empty; the key's value is never included. `available` currently
mirrors `configured` (no live provider ping — that would be a
billable request just to render a status pill).

**Failure behavior** (already existed, unchanged by Stage 1): a
missing/invalid key surfaces as `ConfigurationError` → HTTP 503
`configuration_error` only when a parse is actually attempted, never
at process startup — see `backend/api/routes/language.py`'s error
mapping table. No automatic cross-provider fallback exists or is
implied by the status endpoint; if a deployment wants one, it must be
built and documented explicitly (not attempted in this stage).

---

## 3. Speech: Whisper and ElevenLabs, and the new STT switch

Two independent STT implementations already existed:

- `backend/speech/` — Whisper, local/offline, `POST /api/v1/speech/transcribe`.
- `backend/voice/` — ElevenLabs, `POST /api/v1/voice/transcribe` (STT)
  and `POST /api/v1/voice/speak` (TTS, already wired to the frontend's
  `VoiceContext`/MILO `speaking` state since Phase 8.2).

Before Stage 1, the frontend's live microphone pipeline
(`SpeechContext.tsx`) was hardcoded to Whisper. Stage 1 makes this
selectable without removing either backend, keeping the already-tested
Whisper path as the default:

```
Microphone → SpeechContext.tsx → GET /api/v1/speech (fetched once)
                                        │
                         provider == "whisper"?          provider == "elevenlabs"?
                                  │                                │
                    POST /api/v1/speech/transcribe      POST /api/v1/voice/transcribe
                                  │                                │
                                  └──────────────┬─────────────────┘
                                                  ▼
                                        transcript text → MiloStateContext
```

`STT_PROVIDER` (`backend/speech/config.py`, default `"whisper"`,
validated against `{"whisper", "elevenlabs"}` at config-read time) is
the single switch. `GET /api/v1/speech` reports
`{provider, enabled, available}` for whichever is currently selected,
delegating to that provider's own `is_available()`. If the fetch
fails or is slow, `SpeechContext` stays on the "whisper" default —
selecting a provider only ever changes which backend a *completed*
recording is sent to, never whether recording itself works.

ElevenLabs TTS (`speak`) is unaffected and unchanged by this switch —
there is no Whisper equivalent for speech output.

---

## 4. MILO state system

Unchanged by Stage 1 — already real, already documented in code.
`frontend/src/state/MiloStateContext.tsx` derives MILO's 15 logical
states from `VoiceContext` (speaking), `SpeechContext` (listening/
understanding), `TaskContext` (the real backend `TaskStatus` lifecycle
— `created → initializing`, `parsing → understanding`,
`planning → planning`, `executing → executing`, `succeeded → success`,
`failed → error`, ...), and `AgentsContext` (offline/idle fallback),
in that precedence order. See that file's own module docstring for
the full precedence chain and the success/error hold-timer behavior.

---

## 5. CPU/CUDA Docker fix

`backend/requirements.txt` pins `torch`/`torchvision` with no index
constraint. `docker/Dockerfile` now installs the CPU-only build from
PyTorch's own package index (`--index-url
https://download.pytorch.org/whl/cpu`) before the general
`requirements.txt` install, so the latter is a no-op for those two
packages. This only changes what the Docker image installs — local/GPU
development (`backend/requirements.txt`,
`backend/scripts/download_torch.py`) is unaffected.

---

## 6. Security audit result

A repository-wide grep for hardcoded secrets (`AIza`, `sk-`, `api_key=`,
and similar patterns) across all tracked source, Dockerfiles,
`docker-compose.yml`, CI workflows, and docs found **no matches** — the
only real key material found anywhere in the working tree was in
`backend/.env`, which is gitignored and untracked (confirmed via
`git ls-files`). The project owner confirmed these are current, usable
keys, not exposed credentials requiring rotation. `.gitignore` covers
`.env`, `frontend/.env`, and `frontend/.env.local`; `backend/.env.example`
contains no real values.

**Real finding, fixed in this stage**: `docker/Dockerfile` builds with
the repository root as its context (`docker build -f docker/Dockerfile
.`), and the root `.dockerignore`'s `.env` pattern (with no directory
prefix) did **not** actually exclude `backend/.env` from that build
context — verified empirically by building the image and finding
`/app/.env`, containing the real keys, present inside it. This meant
every backend image build baked live OpenAI/Gemini/ElevenLabs
credentials into an image layer, exactly the failure mode this Phase's
security requirements exist to prevent. Fixed by adding explicit
`backend/.env` and `**/.env` entries to `.dockerignore` alongside the
existing bare `.env` pattern; rebuilt with `--no-cache` and confirmed
`/app/.env` is no longer present in the image, and that
`GET /api/v1/language` on a fresh, no-`-e`-flags container now
correctly reports `configured: false` instead of leaking the baked-in
key's presence. Anyone who has already built and distributed/pushed an
image from this Dockerfile before this fix should treat those keys as
exposed and rotate them — this stage only fixes the build going
forward, it cannot retroactively scrub an image already built or
pushed elsewhere.

No secret is passed as a Docker build argument in either image
(`docker/Dockerfile`, `frontend/Dockerfile`); both only ever receive
credentials via `docker run -e` / `env_file:` at container *run* time.

---

## 7. Reproducibility & experiments (Stage 2 addition)

The full reproduction path (`git clone` → configure → `docker compose
up --build` → tests → experiments) is documented in the root
`README.md`'s "Quick Start" and "Docker" sections — this section only
consolidates the **experiment/benchmark** commands so they're findable
in one place, and is explicit about what's real vs. placeholder.

**Three real, runnable evaluation suites exist, all under `backend/`:**

```bash
cd backend

# Language (Phase 3.6) -- scores a real LLM provider against
# datasets/language/evaluation/. Opt-in (RUN_LLM_BENCHMARK=true,
# real API key required) -- costs money and makes real network calls.
export RUN_LLM_BENCHMARK=true
export OPENAI_API_KEY="sk-..."   # or GEMINI_API_KEY with --provider gemini
python -m evaluation.run_benchmark --dataset all --limit 5
# -> results/language/benchmark_runs/<run_id>/

# Vision/Perception (Phase 3.x) -- fully synthetic/deterministic, no
# network/GPU/cost, no opt-in gate needed.
python -m vision_evaluation.run_benchmark
# -> results/perception/benchmark_runs/<run_id>/

# Memory (Phase 6.2/6.4) -- deterministic, offline (SQLite + a
# deterministic hashing embedder), no network/LLM required.
python -m memory_evaluation.run_evaluation   # retrieval-quality report
python -m memory_evaluation.run_benchmark    # memory-on vs memory-off, size/pollution/ablation
# -> experiments/results/ (JSON + CSV)
```

**`experiments/` and `benchmarks/` at the repository root are
explicitly unimplemented placeholders** — their own `README.md` files
say so directly ("Nothing is implemented here yet" /
"Planned contents"). `experiments/results/` and
`experiments/reports/phase6_4_report.md` are real *output* of the
`memory_evaluation` suite above, not a separate experiment system. Do
not run anything under those two top-level directories expecting a
different or additional experiment to execute — there isn't one yet.

## 7a. Browser E2E automation (Stage 4)

Earlier stages correctly reported real browser + microphone
interaction as "NOT VERIFIED — environment limitation" (Chromium's
runtime libraries were genuinely not installed at the time, confirmed
directly, not assumed). That blocker is now permanently closed:
Playwright (`@playwright/test`) is a committed part of the frontend
project (`frontend/playwright.config.ts`, `frontend/tests/e2e/`), and
`npx playwright install --with-deps chromium` makes the previously
manual OS-dependency installation (`libnspr4`, `libnss3`, etc.)
reproducible in one command for any developer machine or CI runner —
`.github/workflows/ci.yml`'s `e2e` job runs it on every push. See the
root README's "Browser E2E testing" section and
`docs/troubleshooting.md`'s "Browser E2E (Playwright)" section for
setup/commands, and this document's completion report addendum
(delivered in-thread) for the actual, real test run results.

## 8. Explicit deferrals (not attempted in Stage 1)

- Rebuilding configuration as a single centralized `pydantic.Settings`
  class — the existing per-package `from_env()` pattern is deliberate
  and documented; Stage 1 extends it instead.
- Migrating the frontend mic pipeline's *default* away from Whisper —
  it remains the default; ElevenLabs STT is now reachable via
  `STT_PROVIDER=elevenlabs` but is opt-in.
- Deeper interruption/cancellation handling beyond what already
  existed in `SpeechContext`/`VoiceContext`/`MiloStateContext`.
- Any Phase 8.6 (demo experience, screenshots) or Phase 8.7 (final
  research readiness/audit) work.
- A live/billable provider health check for `available` on either
  `GET /api/v1/language` or `GET /api/v1/speech` — both currently
  report configuration state, not a real-time reachability probe.
