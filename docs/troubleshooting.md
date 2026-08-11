# Troubleshooting

Real, common failure modes and their actual fixes, using the
configuration this repository actually reads. Did not exist before
Phase 8.5 Stage 2 (a confirmed gap). Symptoms are grouped by area;
each points at the real file/variable responsible.

## Docker

**`docker build` fails during `pip install`.** Check you're building
from the repository root with `-f docker/Dockerfile .` (the build
context must include `backend/`) — see the root `README.md`'s Docker
section for the exact command.

**Backend image builds but is unexpectedly large / pulls CUDA
packages.** `docker/Dockerfile` installs a CPU-only `torch`/
`torchvision` build from PyTorch's own index before the general
`requirements.txt` install (Phase 8.5 fix; see that Dockerfile's
comments). If a build somehow still pulls CUDA wheels, confirm the
`--index-url https://download.pytorch.org/whl/cpu` install step wasn't
reordered or removed relative to the general `pip install -r
requirements.txt` line.

**`docker run` container never reports healthy.** `HEALTHCHECK` polls
`GET /health`, which never calls an LLM provider or the simulator (see
`backend/api/routes/health.py`). If it never turns healthy, check
`docker logs <container>` for a Python import error or port conflict
— `GET /health` failing to answer at all almost always means the
process itself never started, not a provider misconfiguration.

**A rebuilt image seems to contain stale/real credentials.** This was
a real, fixed bug: the root `.dockerignore`'s bare `.env` pattern did
not exclude `backend/.env` from the backend image's build context. Now
fixed (`backend/.env`/`**/.env` explicit entries added) and covered by
a CI regression test (`.github/workflows/ci.yml`'s "Verify backend/.env
was not baked into the image" step). If you suspect a *previously
built* image (before this fix landed) was ever pushed or distributed,
treat any credentials in it as exposed and rotate them — this fix only
protects builds going forward.

## AI2-THOR / Simulator

**`POST /api/v1/vision/perceive` or `/api/v1/execution/start` returns
`503`.** Expected unless `VISION_ENABLE_SIMULATOR=true` is set *and* a
reachable AI2-THOR/Unity binary with a display is available —
`docker/Dockerfile`'s image deliberately does not bundle Unity (no
display/GPU in that image). See `backend/api/app.py`'s `_lifespan`
docstring for the full startup-gating rationale.

**Repeated `uvicorn --reload` cycles crash WSL / spawn many Unity
windows.** A known-and-fixed Phase 3/4-era bug (`api/app.py`'s
docstring, "Why the simulator is retained on `app.state`..."). Keep
`VISION_ENABLE_SIMULATOR=false` for routine API development; only
enable it for a deliberate simulator-backed session.

## LLM provider credentials

**`GET /api/v1/language` reports `configured: false`.** The
environment variable named by `LANGUAGE_LLM_API_KEY_ENV_VAR`
(`OPENAI_API_KEY`/`GEMINI_API_KEY`/`QWEN_API_KEY` by default,
depending on `LANGUAGE_LLM_PROVIDER`) is unset or empty in the
running process. Setting it requires restarting the backend process —
config is read once at startup (`LanguageRuntimeConfig.from_env()` in
`api/app.py`'s `_lifespan`), not re-read per request.

**`POST /api/v1/language/parse` returns `503 configuration_error`.**
Same root cause as above, surfaced at the moment a parse is actually
attempted (see `language/config.py`'s security note on why the key is
never resolved until call time).

**Switching `LANGUAGE_LLM_PROVIDER` seems to have no effect.** Confirm
the backend process was actually restarted — env vars are read once
at startup. For local Qwen specifically, also confirm
`LANGUAGE_LLM_BASE_URL` actually points at a running local server
(default `http://localhost:8000/v1`); a wrong port here surfaces as a
connection-refused `LLMProviderError`, not a credentials error.

## Speech (Whisper / ElevenLabs)

**`GET /api/v1/speech` reports `available: false` with `provider:
"whisper"`.** `SPEECH_ENABLE_WHISPER` is unset/false, or the
`openai-whisper` model failed to load (check backend startup logs for
`api.vision_system_unavailable`-style warnings from `speech/` instead
— `WhisperTranscriber.from_config()` never raises, it degrades to
unavailable silently by design, so the log is the only signal).

**`GET /api/v1/speech` reports `provider: "elevenlabs"` but
`available: false`.** `VOICE_ENABLE_ELEVENLABS` is false, or
`ELEVENLABS_API_KEY` is unset — check `GET /api/v1/voice` for the
same underlying config (both endpoints read the same `VoiceConfig`).

**Frontend mic button is stuck disabled.** `TalkToMilo.tsx` disables
the mic button while `speech.state` is `"processing"`/`"transcribing"`
— if it never re-enables, the transcription request likely never
resolved (network issue, or the backend became unreachable mid-request).
Since Phase 8.5 Stage 2, a *new* recording started after this state
would have been protected from a stale response by
`SpeechContext.tsx`'s generation guard, but a request that never
resolves at all still needs its own timeout handling on a future pass
— not yet implemented.

## Frontend/backend connectivity

**Frontend requests fail with a CORS error in the browser console.**
`API_ALLOWED_ORIGINS` (comma-separated, `backend/api/app.py`) defaults
to the Vite dev server's origin (`http://localhost:5173`). A
production/Docker deployment behind a different origin (e.g. nginx on
`:8080`) must set this explicitly — see `docker-compose.yml`'s backend
service environment.

**Frontend can't reach the backend at all (`/api/...` 404s or
connection refused).** In dev, confirm `vite.config.ts`'s proxy is
pointed at the right backend port. In Docker Compose, confirm
`frontend/nginx.conf.template`'s `BACKEND_ORIGIN` substitution resolved
correctly — `docker logs` on the frontend container will show nginx's
own startup errors if the template failed to render.

## Browser E2E (Playwright)

**`npx playwright install chromium` succeeds but tests fail with a
missing shared library (`libnspr4`/`libnss3`/etc.) or Chromium won't
launch.** Use `npx playwright install --with-deps chromium` instead —
`--with-deps` installs the OS-level packages Chromium needs on top of
the browser binary itself (see `frontend/README`'s "Browser E2E
testing" section). This is the single command that made browser
automation reproducible for this repository; a bare
`playwright install chromium` without `--with-deps` on a fresh Ubuntu
machine is the exact scenario that previously left this an
undocumented manual blocker.

**A `tests/e2e/*.spec.ts` test times out waiting for a selector.**
Confirm the dev server actually started — `playwright.config.ts`'s
`webServer` runs `npm run dev` on port 5175 and Playwright waits for
it; a port conflict (another `vite`/`playwright` process already
running) is the most common cause. Run `npm run test:e2e:headed` to
watch the real browser and see what actually rendered.

**A microphone/recording test fails or hangs.** Confirm
`playwright.config.ts`'s `chromium` project still has
`--use-fake-device-for-media-stream`/`--use-fake-ui-for-media-stream`
in `launchOptions.args` and `permissions: ["microphone"]` in `use` —
without both, `getUserMedia` will either hang on a real permission
prompt (no physical mic in CI) or reject. See
`tests/e2e/microphone.spec.ts`'s module docstring.

**E2E tests seem to depend on a real backend or provider.** They
should never need to — every test mocks the backend via
`page.route()` (`tests/e2e/utils/mockApi.ts`). If a test is making a
real network call, check for a missing `page.route()` registration
for the specific endpoint it hits (Playwright lets unmocked requests
through to the real network by default).
