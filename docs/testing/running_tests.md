# Running Tests, Benchmarks, and E2E Suites (Detailed)

> The complete, exhaustive per-phase test/benchmark command
> reference, moved here from the README's old "Quick Start" section
> during the Phase 8.7 README restructure (2026-08-11). The README
> keeps only the minimal commands needed to get started; this is the
> full reference for running any specific subset, plus the Playwright
> E2E suite, provider smoke tests, and the language/perception
> benchmarks.

```bash
# From the repository root
cd backend
pip install -r requirements.txt

# Run the full perception pipeline end to end and save an annotated frame
python -m vision.visualization.test_visualizer

# Run detection + segmentation + scene graph and print the relationships
python -m vision.scene_graph.test_scene_graph

# Run the Language Interface unit tests
python -m pytest tests/test_task.py -v

# Run the Language Parsing Runtime unit + integration tests (LLM mocked,
# no API key or network access required)
python -m pytest tests/test_language_*.py -v

# Run the Phase 3.6 evaluation framework's own tests (LLM always faked,
# no API key or network access required)
python -m pytest tests/test_evaluation_*.py -v

# Run the Phase 3.7 API tests (LanguageAgent mocked, no LLM call)
python -m pytest tests/test_api_language.py tests/test_api_health.py -v

# Run the Phase 3.x Spatial & Temporal Perception unit tests (synthetic
# inputs only -- no AI2-THOR, GPU, or model download required)
python -m pytest tests/test_vision_depth.py tests/test_vision_localization.py \
    tests/test_vision_tracking.py tests/test_vision_temporal_scene.py \
    tests/test_vision_scene_graph_spatial.py tests/test_vision_visualization.py \
    tests/test_vision_factory.py tests/test_vision_evaluation.py \
    tests/test_api_vision.py -v

# Run the Phase 4 Task Planning unit + integration tests (no AI2-THOR,
# no LLM required -- ReActPlanner's tests mock/omit the LLM client)
python -m pytest tests/test_planner_*.py tests/test_api_planner.py -v

# Run the Phase 5 Execution unit + integration tests (FakeSimulator --
# no AI2-THOR/Unity process required)
python -m pytest tests/test_execution_*.py tests/test_api_execution.py -v

# Run the Phase 6.1/6.2 Memory unit + integration tests (pure SQLite +
# a deterministic offline embedder against pytest's tmp_path -- no
# AI2-THOR/LLM/network required)
python -m pytest tests/test_memory_*.py -v

# Run the Phase 6.2 retrieval-quality evaluation report (Recall@K,
# Precision@K, MRR, latency across four ranking ablations)
python -m memory_evaluation.run_evaluation

# Run the Phase 6.3 Memory <-> Robot Integration tests -- MemoryAgent,
# memory-conditioned RuleBasedPlanner, and the TaskRunner golden memory
# test (retrieve -> plan -> execute -> remember -> restart -> retrieve)
python -m pytest tests/test_memory_agent.py tests/test_planner_memory_context.py \
    tests/test_orchestration_task_runner.py -v

# Run the Phase 6.4 benchmark regression tests (locks in the measured
# memory-vs-no-memory findings, incl. the stale-memory failure case)
python -m pytest tests/test_memory_evaluation_benchmark.py -v

# Run the Phase 6.4 full benchmark suite -- memory_on vs memory_off,
# memory-size/pollution/ablation experiments, writes JSON+CSV results
# to experiments/results/ (deterministic, no AI2-THOR/LLM required)
python -m memory_evaluation.run_benchmark

# Or simply run everything under backend/tests/ (what CI runs)
python -m pytest tests/ -v

# Optional: real AI2-THOR end-to-end Execution tests (opt-in, requires a
# reachable AI2-THOR/Unity binary + display -- never run in CI)
RUN_SIMULATOR_TESTS=true python -m pytest simulator/test_execution_e2e.py -v
```

Model weights are downloaded automatically on first run into
`models/<model_name>/` (see [`docs/phases/phase2_vision.md`](../phases/phase2_vision.md#modelmanager)).

### Running the API + Frontend (Phase 3.7)

```bash
# Terminal 1 -- backend (see "Language Parsing Runtime configuration"
# below for provider/API-key setup; the API starts fine without a key,
# it only fails at parse time if one is missing)
cd backend
uvicorn api.app:app --reload
# -> http://localhost:8000  (docs at /docs, health at /health)

# Terminal 2 -- frontend
cd frontend
npm install
npm run dev
# -> http://localhost:5173, proxies /api and /health to localhost:8000
```

Example request:

```bash
curl -X POST http://localhost:8000/api/v1/language/parse \
    -H "Content-Type: application/json" \
    -d '{"instruction": "Bring me the red mug."}'
```

Example response:

```json
{
  "status": "ok",
  "result": {
    "task_type": "single",
    "task_id": "b3b7...",
    "goal": "bring",
    "object": "mug",
    "attributes": {"color": "red"},
    "needs_clarification": false,
    "clarification_reason": null
  },
  "diagnostics": {
    "provider": "gemini",
    "model": "gemini-flash-latest",
    "prompt_version": "1.1.0",
    "schema_version": "1.0.0",
    "attempt_count": 1,
    "latency_ms": 742.0,
    "recovered": false
  }
}
```

See `backend/docs/language_interface_spec.md` section 30 for the full
endpoint contract, error-mapping table, and clarification handling.
This API has no authentication, rate limiting, or request quota
enforcement -- it is not intended to be deployed as a publicly
reachable, unauthenticated service (section 30.9).

### Browser E2E testing (Playwright)

`frontend/tests/e2e/` is a real-Chromium browser test suite (Phase
8.5), separate from `frontend/src/**/*.test.tsx`'s jsdom-based Vitest
suite -- it loads the actual app in a real browser and drives it the
way a user would (clicks, real `getUserMedia`/`MediaRecorder`, real
`<audio>` playback), while mocking the backend HTTP surface via
Playwright's `page.route()` so no FastAPI process and no real
Gemini/OpenAI/ElevenLabs credentials are ever required. Real-provider
validation (a real LLM/speech call) is a separate, manual, opt-in
activity -- see "Real provider validation" below and
`docs/troubleshooting.md` -- never something this automated suite or
CI does.

```bash
cd frontend
npm install
npx playwright install --with-deps chromium   # one-time; downloads
                                                # Chromium + every OS
                                                # library it needs
                                                # (libnspr4, libnss3,
                                                # libasound2, libgbm1,
                                                # the X11 libs, ...)

npm run test:e2e            # headless, matches CI
npm run test:e2e:headed     # watch the real browser while it runs
npm run test:e2e:ui         # Playwright's interactive UI/trace viewer
```

`playwright.config.ts` starts only the Vite dev server (`npm run dev`)
-- never the backend -- and grants microphone permission with
Chromium's `--use-fake-device-for-media-stream`/
`--use-fake-ui-for-media-stream` flags, so mic-interaction tests
(`tests/e2e/microphone.spec.ts`: permission, recording, transcript,
barge-in) run fully headless with a synthetic audio device, no
physical microphone and no manual permission dialog required. See
that file's own docstring, and `tests/e2e/milo-state.spec.ts` for a
real-browser proof of the MILO state machine reacting to a real
(mocked) task lifecycle.

**Reproducibility**: `npx playwright install --with-deps chromium` is
the single command that makes this reproducible on a fresh developer
machine or a CI runner -- it installs Chromium itself plus every
Ubuntu package the earlier "Chromium runtime libraries unavailable"
limitation was blocked on, so that limitation is no longer an
undocumented manual step. `.github/workflows/ci.yml`'s `e2e` job runs
this exact command.

The Planner API (Phase 4) needs no simulator, LLM, or extra
configuration -- it always plans against a fresh symbolic `WorldState`:

```bash
curl -X POST http://localhost:8000/api/v1/planner/plan \
    -H "Content-Type: application/json" \
    -d '{
      "planner_type": "rule_based",
      "task": {
        "task_type": "single",
        "task_id": "task_001",
        "goal": "store",
        "object": "apple",
        "target": "refrigerator",
        "needs_clarification": false
      }
    }'

# Compare all three strategies on the same task
curl -X POST http://localhost:8000/api/v1/planner/evaluate \
    -H "Content-Type: application/json" \
    -d '{"task": {"task_type": "single", "task_id": "task_001", "goal": "store", "object": "apple", "target": "refrigerator", "needs_clarification": false}}'
```

`"planner_type": "react"` additionally requires an `LLMClient` to be
wired in server-side (this endpoint currently always falls back to
`rule_based` behavior with `Plan.metadata["react_fallback"] = true`,
since no LLM client is constructed by the API layer yet -- see
[Future Phases](#future-phases)). See the
[Task Planning (Phase 4, complete)](#task-planning-phase-4-complete)
section above for the full endpoint contract.

To also exercise the Vision API against a real simulator, start the
backend with `VISION_ENABLE_SIMULATOR=true` (a reachable AI2-THOR/Unity
binary is required -- see
[`docs/architecture/spatial_perception.md`](../architecture/spatial_perception.md)'s
"Configuration" section for why this is opt-in):

```bash
VISION_ENABLE_SIMULATOR=true uvicorn api.app:app --reload

curl -X POST http://localhost:8000/api/v1/vision/perceive \
    -H "Content-Type: application/json" \
    -d '{"prompt": "chair. table. mug. apple. bottle. refrigerator."}'
```

**Keep `VISION_ENABLE_SIMULATOR=false` (`backend/.env`'s default) for
normal API development.** `--reload` re-runs FastAPI's startup/shutdown
inside the same Uvicorn worker on every code change; with the simulator
enabled, that means every reload starts (and, since the Phase 4
lifecycle fix below, cleanly stops) a real AI2-THOR/Unity subprocess.
Only set it to `true` for a deliberate, short-lived simulator-backed
session, and prefer *not* reloading repeatedly while it's on.

> **Phase 4 simulator lifecycle fix.** Early Phase 4 development hit a
> bug where `VISION_ENABLE_SIMULATOR=true` plus repeated `--reload`
> cycles launched a new Unity instance on every reload without ever
> stopping the previous one -- 10+ simultaneous AI2-THOR windows
> accumulated and crashed WSL (`Wsl/Service/E_UNEXPECTED`). The root
> cause was that `api/app.py`'s FastAPI lifespan never retained the
> `Simulator` it constructed and never called `.stop()` on shutdown. The
> fix (see `backend/api/app.py`, `backend/simulator/ai2thor_env.py`,
> `backend/simulator/simulator.py`): the lifespan now stores the
> simulator on `app.state.simulator` and always calls
> `app.state.simulator.stop()` during shutdown, and `AI2ThorEnv.start()`/
> `.stop()` are now idempotent (a second `start()` while already running
> is a no-op; `stop()` clears the controller reference so it's safe to
> call more than once) as a second line of defense. Every simulator
> instance now has exactly one owner and a guaranteed release path.

Without `VISION_ENABLE_SIMULATOR=true` (or without a reachable
simulator), the endpoint returns a clean `503 vision_unavailable` --
not a crash -- and the rest of the API (including the Language API)
keeps working normally.

The Execution API (Phase 5) shares that same simulator gate --
`VISION_ENABLE_SIMULATOR=true` and a reachable AI2-THOR binary are
required, since executing a plan means actually driving AI2-THOR. With
the backend running that way, generate a plan and execute it end to
end (the README's headline "store the apple in the refrigerator" task):

```bash
VISION_ENABLE_SIMULATOR=true uvicorn api.app:app --reload

# 1. Generate a validated plan (Phase 4) -- see the Planner API example above
PLAN=$(curl -s -X POST http://localhost:8000/api/v1/planner/plan \
    -H "Content-Type: application/json" \
    -d '{"planner_type": "rule_based", "task": {"task_type": "single", "task_id": "task_001", "goal": "store", "object": "apple", "target": "refrigerator", "needs_clarification": false}}' \
    | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["plan"]))')

# 2. Execute it (Phase 5) -- runs on a background thread, returns immediately
curl -s -X POST http://localhost:8000/api/v1/execution/start \
    -H "Content-Type: application/json" \
    -d "{\"plan\": $PLAN}"
# -> {"execution_id": "...", "plan_id": "...", "status": "running", ...}

# 3. Poll for progress/completion
curl -s http://localhost:8000/api/v1/execution/<execution_id>

# 4. Per-step results and the structured event log
curl -s http://localhost:8000/api/v1/execution/<execution_id>/steps
curl -s http://localhost:8000/api/v1/execution/<execution_id>/events

# Cancel a running execution
curl -s -X POST http://localhost:8000/api/v1/execution/<execution_id>/cancel
```

Without `VISION_ENABLE_SIMULATOR=true` (or without a reachable
simulator), `POST /api/v1/execution/start` returns a clean
`503 execution_unavailable`, matching the Vision API's own behavior.
See [Execution (Phase 5, complete)](#execution-phase-5-complete) above
for the full endpoint contract.

### Language Parsing Runtime configuration

`LanguageAgent.from_config()` reads its settings from the environment
(`backend/language/config.py`); every variable has a default except the
API key itself. The provider is selected with `LANGUAGE_LLM_PROVIDER`
-- `"openai"` (default), `"gemini"`, or `"qwen"` (local/self-hosted) --
and every other setting defaults to a value appropriate for *that*
provider, so switching providers is a one-variable change, never a
code change. `GET /api/v1/language` reports the currently configured
provider/model and whether an API key is present, without ever
exposing the key itself -- see "Provider & speech status" below.

**Skip re-exporting these every session** by copying
`backend/.env.example` to `backend/.env` and filling in your key --
`backend/api/app.py` loads it automatically on startup (via
`python-dotenv`) whenever the Phase 3.7 API is run
(`uvicorn api.app:app`), so a plain `export` in your shell is no
longer required. `backend/.env` is gitignored and never baked into the
Docker image; a value already set in your shell or via `docker run -e`
always takes priority over `.env`. This only applies to the API
process -- a bare `python -m pytest ...` or a script that imports
`language` directly still reads only real environment variables, since
`language/config.py` itself has no `.env` awareness (by design, see
`backend/api/app.py`'s docstring).

```bash
cp backend/.env.example backend/.env
# then edit backend/.env with your key
```

#### OpenAI (default)

```bash
export OPENAI_API_KEY="sk-..."
# Optional overrides (defaults shown):
export LANGUAGE_LLM_PROVIDER="openai"
export LANGUAGE_LLM_MODEL="gpt-4o-mini"
export LANGUAGE_LLM_BASE_URL="https://api.openai.com/v1"
export LANGUAGE_LLM_API_KEY_ENV_VAR="OPENAI_API_KEY"
export LANGUAGE_LLM_TIMEOUT_SECONDS="30"
export LANGUAGE_LLM_MAX_RETRIES="2"          # network-transport retries
export LANGUAGE_RUNTIME_MAX_RETRIES="2"      # Phase 3.5 recovery retries
```

#### Gemini (free-tier friendly for development)

1. Create a free-tier Gemini API key in
   [Google AI Studio](https://aistudio.google.com/apikey) (requires a
   Google account; a project is created for you automatically).
2. Export it and select the Gemini provider:

```bash
export GEMINI_API_KEY="..."                  # never commit this value
export LANGUAGE_LLM_PROVIDER="gemini"
# Optional overrides (defaults shown):
export LANGUAGE_LLM_MODEL="gemini-flash-latest"
export LANGUAGE_LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta"
export LANGUAGE_LLM_API_KEY_ENV_VAR="GEMINI_API_KEY"
export LANGUAGE_LLM_TIMEOUT_SECONDS="30"
export LANGUAGE_LLM_MAX_RETRIES="2"
export LANGUAGE_RUNTIME_MAX_RETRIES="2"
```

`gemini-flash-latest` is a Google-maintained alias for a current
Flash-tier model, chosen so this project does not silently keep
pointing at a model Google has since deprecated -- point
`LANGUAGE_LLM_MODEL` at any other Gemini model without a code change.
**Free-tier quota and model availability are controlled entirely by
Google's current API policies and your own Google AI Studio / Cloud
project eligibility** -- this project makes no pricing or quota
guarantee; check [ai.google.dev/pricing](https://ai.google.dev/pricing)
for current terms before relying on it. Never put the key value itself
in source code, tests, documentation, commit messages, or a
screenshot -- only in an environment variable.

```python
from language import LanguageAgent

agent = LanguageAgent.from_config()
task = agent.parse("Bring me the red mug.")

# Phase 3.5: same contract, plus observability metadata (provider,
# model, attempt count, whether a retry/repair actually recovered the
# result) for a future benchmark harness or API layer to consume.
outcome = agent.parse_with_diagnostics("Bring me the red mug.")
print(outcome.metadata.provider, outcome.metadata.attempt_number)
```

No environment variable is required to run the unit test suite --
every test either injects a fake `LLMClient` or monkeypatches the HTTP
call, per this project's requirement that the unit test suite never
make a real LLM API call.

#### Local Qwen / local LLM

Points `LanguageAgent` at any locally hosted, OpenAI-API-compatible
server (vLLM, Ollama, ...) serving Qwen, Llama, Phi, or any other
model that server exposes -- reuses the same
`OpenAICompatibleLLMClient` the OpenAI provider uses (see
`backend/language/provider_factory.py`); no separate client class or
planner change is involved.

```bash
export LANGUAGE_LLM_PROVIDER="qwen"
# Optional overrides (defaults shown):
export LANGUAGE_LLM_MODEL="qwen2.5-7b-instruct"
export LANGUAGE_LLM_BASE_URL="http://localhost:8000/v1"   # vLLM's default OpenAI-compatible endpoint
export LANGUAGE_LLM_API_KEY_ENV_VAR="QWEN_API_KEY"
# Many local servers don't check the bearer token at all -- if yours
# doesn't, set this to any placeholder value (never a real secret); a
# value must still be present, since credential resolution is
# identical across every provider (see llm_client.py's Security note).
export QWEN_API_KEY="not-needed"
```

Start a local vLLM server serving Qwen (example, adjust for your
hardware/model choice) and the app above will reach it with no other
change:

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-7B-Instruct --port 8000
```

#### Optional: real API smoke tests

An explicitly opt-in suite (`backend/tests/test_language_llm_smoke.py`)
makes real calls to OpenAI and/or Gemini, skipped by default and
whenever the relevant credential is absent -- normal CI never runs it:

```bash
export RUN_LLM_SMOKE_TESTS=true
export OPENAI_API_KEY="sk-..."      # to run the OpenAI smoke test
export GEMINI_API_KEY="..."         # to run the Gemini smoke test
cd backend && python -m pytest tests/test_language_llm_smoke.py -v
```

### Speech: Whisper (default) and ElevenLabs

Two independent speech subsystems exist server-side:

- **Whisper** (`backend/speech/`, `SPEECH_ENABLE_WHISPER=true`, `WHISPER_MODEL_SIZE`,
  `WHISPER_DEVICE`) -- local, offline speech-to-text.
- **ElevenLabs** (`backend/voice/`, `VOICE_ENABLE_ELEVENLABS=true`, `ELEVENLABS_API_KEY`,
  `ELEVENLABS_VOICE_ID`) -- a paid third-party API providing both speech-to-text
  (`POST /api/v1/voice/transcribe`) and MILO's spoken text-to-speech output
  (`POST /api/v1/voice/speak`), the latter already wired into the frontend's
  `VoiceContext`/MILO `speaking` state.

The frontend's live microphone pipeline (`SpeechContext.tsx`) calls whichever
STT backend `STT_PROVIDER` selects (`"whisper"`, the default, or `"elevenlabs"`)
-- fetched once from `GET /api/v1/speech` at startup. Text-to-speech is always
ElevenLabs; there is no Whisper equivalent for speech output.

```bash
# Whisper (default) -- no ElevenLabs credential required for STT.
export SPEECH_ENABLE_WHISPER=true
export STT_PROVIDER=whisper           # optional, this is already the default

# ElevenLabs STT instead -- reuses the same account/key as TTS output.
export VOICE_ENABLE_ELEVENLABS=true
export ELEVENLABS_API_KEY="..."       # never commit this value
export STT_PROVIDER=elevenlabs
```

### Provider & speech status

Two read-only, secret-free status endpoints back Settings' "LLM Provider"
and "Speech & Voice" cards -- neither ever 503s, and neither ever includes
an API key value, only whether one is configured:

```bash
curl -s localhost:8000/api/v1/language | python -m json.tool
# {"provider": "openai", "model": "gpt-4o-mini", "configured": true, "available": true}

curl -s localhost:8000/api/v1/speech | python -m json.tool
# {"provider": "whisper", "enabled": true, "available": true}

curl -s localhost:8000/api/v1/voice | python -m json.tool
# {"enabled": true, "available": true, "provider": "elevenlabs", "voice_id": "..."}
```

### Optional: a real Phase 3.6 benchmark run

`backend/evaluation/run_benchmark.py` scores a real provider against
`datasets/language/evaluation/` and writes a versioned result to
`results/language/benchmark_runs/<run_id>/`. Like the smoke tests
above, it never runs by accident: it requires `RUN_LLM_BENCHMARK=true`
explicitly, independent of whether a provider API key happens to be
set.

```bash
export RUN_LLM_BENCHMARK=true
export OPENAI_API_KEY="sk-..."      # or GEMINI_API_KEY with --provider gemini
cd backend
python -m evaluation.run_benchmark --dataset all --limit 5
```

`--provider`/`--model` override `LANGUAGE_LLM_PROVIDER`/
`LANGUAGE_LLM_MODEL`; `--dataset {all,success,failure,ambiguity}` and
`--limit <n>` bound scope and cost. Every case runs sequentially -- no
concurrency, by design (see spec section 29.10).

### Perception benchmark (Phase 3.x)

Unlike the language benchmark above, this one is fully synthetic/
deterministic (no network, GPU, or cost), so it needs no opt-in gate:

```bash
cd backend
python -m vision_evaluation.run_benchmark
```

Writes a versioned result to
`results/perception/benchmark_runs/<run_id>/` (depth MAE/RMSE/relative
error/threshold accuracy, tracking ID switches/fragmentation/recall/
success rate). See
[`docs/architecture/spatial_perception.md`](../architecture/spatial_perception.md)'s
"Benchmarking" section for why this is synthetic rather than based on a
curated labeled dataset.

