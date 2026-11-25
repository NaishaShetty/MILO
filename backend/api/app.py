"""
app.py (backend/api)

Purpose
-------
Constructs the FastAPI application: the single process entry point for
Phase 3.7's HTTP interface around the Phase 3.4/3.5 Language
Understanding runtime. Run with:

    cd backend && uvicorn api.app:app --reload

Why the `LanguageAgent` is built once, at startup
---------------------------------------------------
`LanguageAgent.from_config()` (`language/agent.py`) wires a
`PromptBuilder` (which reads and caches `parser_prompt.txt` +
`prompt_config.yaml` from disk) and an `LLMClient` (which reads
provider configuration and an API key from the environment) -- none of
that is per-request state, and re-doing it on every request would mean
re-reading disk/environment on every single call for no benefit. This
module instead constructs one `LanguageAgent` in FastAPI's `lifespan`
context manager and stores it on `app.state`; `routes/language.py`'s
dependency function reads it back per-request without constructing
anything. This mirrors exactly how `LanguageAgent` is meant to be used
in any long-lived process (see `agent.py`'s own docstring on
`from_config` being a factory, not a per-call constructor).

Why CORS is configuration-driven, not `allow_origins=["*"]`
----------------------------------------------------------------
A wildcard origin would let *any* website's JavaScript call this API
from a user's browser -- harmless for a same-origin-only research tool,
but not a default this project wants to ship even for a research
prototype. `API_ALLOWED_ORIGINS` (comma-separated) controls the
allow-list; it defaults to the Vite dev server's default origin
(`http://localhost:5173`) so local development works out of the box
without the developer needing to set anything. A real deployment is
expected to set this explicitly (see
`backend/docs/language_interface_spec.md` section 30.9 and this
project's Phase 3.7 "Production Limitations" note: this API has no
authentication or rate limiting yet, and is not intended to be
publicly reachable as configured here).

Why the `VisionSystem` construction is opt-in and can fail without
crashing the app
------------------------------------------------------------------------
Unlike `LanguageAgent` (pure network/config, always constructible),
`VisionSystem` (`vision/factory.py`) needs a running AI2-THOR/Unity
simulator -- not available in every environment this API might run in
(this project's CI, a headless deployment without the simulator
installed), and attempting to launch Unity with no display available
can block far longer than a startup path should. `_lifespan` only
attempts it at all when `VISION_ENABLE_SIMULATOR=true` is explicitly
set (default: disabled -- see the inline comment in `_lifespan` for why
this needs to be an opt-in gate, not just a `try/except`); when it does
attempt it, `Simulator().start()` + `build_vision_system(...)` are
still wrapped in `try/except` for every other failure mode (missing
model weights, etc.), logging and leaving `app.state.vision_system =
None` rather than letting an unavailable simulator take down the
entirely-unrelated Language API. `routes/vision.py`'s dependency
function turns that `None` into a clean 503 per request -- see that
module's docstring. `VISION_DEPTH_SOURCE` (env var, default
`"ground_truth"`) selects which `BaseDepthEstimator`
`build_vision_system` wires in; see
`docs/architecture/spatial_perception.md`.

Why the simulator is retained on `app.state` and explicitly stopped
------------------------------------------------------------------------
`Simulator.start()` launches a real Unity subprocess (via
`AI2ThorEnv`/`ai2thor.controller.Controller`) -- it is not something the
OS reliably reclaims the moment this app "restarts," because under the
normal development command (`uvicorn api.app:app --reload`) a reload
does not start a new OS process; it re-runs this module's `_lifespan`
inside the *same* Uvicorn worker process. A version of this file used
to construct the simulator as a local variable and never call
`.stop()` on shutdown ("OS cleans it up" -- it doesn't, for the reason
above); every reload therefore launched *another* Unity instance on top
of the previous one, and enough reloads accumulated 10+ simultaneous
AI2-THOR windows and crashed WSL (`Wsl/Service/E_UNEXPECTED`). The fix
is for this lifespan to be the simulator's sole owner for its entire
life: the instance is stored on `app.state.simulator` at startup and
`app.state.simulator.stop()` is always called during teardown (see the
`yield` in `_lifespan`), so shutdown/reload always releases the exact
Unity process this startup created before anything can launch another
one. `AI2ThorEnv.start()`/`.stop()` are themselves idempotent (see that
module's docstring) as a second line of defense, but this app should
never rely on that -- it should call `stop()` exactly once, always.
For routine API development, keep `VISION_ENABLE_SIMULATOR=false`
(`backend/.env`) so `--reload` never touches Unity at all; only set it
`true` for a deliberate simulator-backed session (see
`docs/` and this repository's root `README.md`).

Why `.env` is loaded here, and only here
-------------------------------------------
`language/config.py` reads every setting (provider, model, API key
env var name, ...) from `os.environ` -- it has no `.env`-loading logic
of its own, deliberately: a config module should not decide *how*
environment variables got set (a real shell export, a process
manager, a `.env` file, a Docker `-e` flag are all equally valid to
it). Loading `backend/.env` -- a developer convenience so
`OPENAI_API_KEY`/`GEMINI_API_KEY` don't need to be re-exported in
every new terminal -- is instead this module's job, since it is the
one place that already represents "the process is starting up".
`load_dotenv()` only *fills gaps* in `os.environ`; it never overrides
a variable already set by the shell or `docker run -e`, so the two
mechanisms compose safely. `backend/.env` is gitignored (see the
repository root `.gitignore`) and only ever read locally -- it is
never copied into the Docker image (see `docker/Dockerfile`'s own
credential note) and never reaches the frontend, which has no `.env`
loading of its own and must never hold an LLM key (section 30.9).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agents.memory_agent import MemoryAgentWrapper
from agents.speech_agent import SpeechAgent
from agents.vision_agent import VisionAgentWrapper
from agents.voice_agent import VoiceAgent
from api.routes.agents import router as agents_router
from api.routes.benchmark import router as benchmark_router
from api.routes.execution import router as execution_router
from api.routes.health import router as health_router
from api.routes.lab import router as lab_router
from api.routes.language import router as language_router
from api.routes.memory import router as memory_router
from api.routes.planner import router as planner_router
from api.routes.scene_map import router as scene_map_router
from api.routes.skills import router as skills_router
from api.routes.speech import router as speech_router
from api.routes.tasks import build_orchestrator
from api.routes.tasks import router as tasks_router
from api.routes.traces import router as traces_router
from api.routes.vision import router as vision_router
from api.routes.voice import router as voice_router
from api.security import rate_limit, require_api_key
from language.agent import LanguageAgent
from language.config import LanguageRuntimeConfig
from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from simulator.simulator import Simulator
from speech.config import SpeechConfig
from speech.whisper_client import WhisperTranscriber
from vision.factory import DEPTH_SOURCE_GROUND_TRUTH, build_vision_system
from voice.config import VoiceConfig
from voice.elevenlabs_client import ElevenLabsClient

# Loaded from an explicit path (backend/.env), not a bare
# `load_dotenv()`, so it is found regardless of the working directory
# the server happens to be started from -- `cd backend && uvicorn
# api.app:app` and `uvicorn api.app:app` from the repository root
# resolve to the same file either way. Runs at module import time,
# before `_allowed_origins()` reads `API_ALLOWED_ORIGINS` and before
# `_lifespan` calls `LanguageAgent.from_config()` -- both need
# `os.environ` already populated.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)


#: Deployment targets that need an explicit `ai2thor.platform` (a real
#: headless GPU server, no X server -- see `simulator/ai2thor_env.py`'s
#: "Headless GPU deployment" note). Anything else (unset, "auto") keeps
#: today's local auto-detected behavior by passing `platform=None`
#: through unchanged.
_SIMULATOR_PLATFORMS = {"cloud_rendering": "CloudRendering", "linux64": "Linux64"}


def _resolve_simulator_platform():
    """
    Reads `VISION_SIMULATOR_PLATFORM` and resolves it to the matching
    `ai2thor.platform` class, or `None` if unset/unrecognized -- the
    same "keep existing behavior unless explicitly opted into" pattern
    `VISION_ENABLE_SIMULATOR`/`VISION_DEPTH_SOURCE` already use just
    below. Only a real headless GPU deployment needs to set this.
    """
    raw = os.environ.get("VISION_SIMULATOR_PLATFORM", "").strip().lower()
    class_name = _SIMULATOR_PLATFORMS.get(raw)
    if class_name is None:
        return None
    import ai2thor.platform

    return getattr(ai2thor.platform, class_name)


def _allowed_origins() -> list[str]:
    """
    Reads `API_ALLOWED_ORIGINS` (comma-separated) from the environment,
    falling back to the Vite dev server's default origin. Kept as a
    plain function (not a dataclass/config object) since this is the
    one setting this module owns -- everything else is delegated to
    `LanguageRuntimeConfig.from_env()` (see this module's docstring on
    not duplicating Phase 3.4 configuration).
    """
    raw = os.environ.get("API_ALLOWED_ORIGINS", "http://localhost:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Built explicitly (rather than letting `LanguageAgent.from_config()`
    # read the environment internally) so `app.state.language_config` is
    # also available to `routes/language.py`'s `GET /language` status
    # endpoint (Phase 8.5) -- it needs `provider`/`model`/
    # `api_key_env_var` to report safe status without either
    # reconstructing config a second time or reaching into
    # `LanguageAgent`'s private collaborators. `from_config()` still
    # does the exact same wiring either way (see its own docstring).
    language_config = LanguageRuntimeConfig.from_env()
    app.state.language_config = language_config
    app.state.language_agent = LanguageAgent.from_config(language_config)

    # Built unconditionally (matches `language_agent` above): memory
    # needs no simulator, and `MemoryAgent.from_config()` never raises
    # -- see that method's own docstring -- so this can never take the
    # app down at startup even with an unwritable/misconfigured memory
    # path.
    app.state.memory_agent = MemoryAgent.from_config(MemoryConfig.from_env())

    # Built unconditionally, same rationale as `memory_agent` above:
    # `WhisperTranscriber.from_config()` never raises (see that
    # method's own docstring) -- when `SPEECH_ENABLE_WHISPER` is unset
    # (default) or the model fails to load, `SpeechAgent.is_available()`
    # is simply `False` and `routes/speech.py` reports a clean 503.
    # `speech_config` is also retained on its own (mirroring
    # `voice_config` below) so `GET /api/v1/speech`'s status endpoint
    # (Phase 8.5) can report the configured `stt_provider` without
    # re-reading the environment a second time.
    speech_config = SpeechConfig.from_env()
    app.state.speech_config = speech_config
    app.state.speech_agent = SpeechAgent(WhisperTranscriber.from_config(speech_config))

    # Built unconditionally, same rationale as `speech_agent` above:
    # `ElevenLabsClient.from_config()` never raises -- when
    # `VOICE_ENABLE_ELEVENLABS` is unset (default) or no API key is
    # present, `VoiceAgent.is_available()` is simply `False` and
    # `routes/voice.py` reports a clean 503. Not simulator-gated: voice
    # is a pure network integration, same as the language agent.
    # Also retained on its own so `routes/voice.py`'s `GET /voice`
    # status endpoint can report `voice_id`/`enabled` even when the
    # agent itself is unavailable (`ElevenLabsClient.from_config()`
    # discards its config entirely when `enabled=False` -- see that
    # method's docstring) -- Settings' "Speech & Voice" section needs
    # to show the real configured voice ID regardless of whether
    # voice is currently on.
    voice_config = VoiceConfig.from_env()
    app.state.voice_config = voice_config
    app.state.voice_agent = VoiceAgent(ElevenLabsClient.from_config(voice_config))

    # See this module's docstring ("Why the VisionSystem construction
    # can fail without crashing the app") -- a missing AI2-THOR/Unity
    # binary must not take down the (unrelated) Language API.
    #
    # `Simulator().start()` launches (or attempts to launch) a Unity
    # subprocess -- unlike every other failure mode this try/except
    # guards against, an *unavailable* Unity binary/display does not
    # necessarily raise quickly; on a machine with no display server at
    # all (this project's CI, most containers) it can block far longer
    # than a request-handling process should ever wait at startup. So
    # this is explicitly opt-in via `VISION_ENABLE_SIMULATOR=true`
    # (default: disabled) -- the same "don't attempt something that can
    # hang/cost resources unless explicitly asked" gate this project
    # already uses for `RUN_LLM_BENCHMARK`
    # (`backend/evaluation/run_benchmark.py`) and the LLM smoke test
    # (`backend/tests/test_language_llm_smoke.py`). CI and this
    # repository's own test suite never set this variable, so
    # `app.state.vision_system` stays `None` and every vision test
    # exercises the route via `app.dependency_overrides` instead (see
    # `backend/tests/test_api_vision.py`).
    app.state.simulator = None
    app.state.vision_system = None
    # Owned here for the whole lifespan and stopped in the `finally`
    # at the bottom, whichever way this function exits. It is also kept
    # as a local so a simulator that started but then failed to be
    # wired up (and so never reached `app.state`) is still stopped --
    # previously the startup `except` below dropped it on the floor and
    # leaked a Unity subprocess.
    simulator = None
    try:
        simulator = _start_vision_and_tasks(app)
        yield
    finally:
        _stop_simulator(app.state.simulator or simulator)
        app.state.simulator = None


def _planner_llm_client(language_config):
    """The language-model client the `react` planner uses, or `None` when
    none can be built (no key configured) -- `react` then falls back to the
    rule-based planner and says so on the task."""
    try:
        from language.provider_factory import create_llm_client

        return create_llm_client(language_config.llm)
    except Exception:
        logger.info("api.react_planner_llm_unavailable", exc_info=True)
        return None


def _stop_simulator(simulator) -> None:
    """
    Stops `simulator` if there is one. Never raises: it runs during
    teardown and error handling, where a second exception must not mask
    the first or stop the app from shutting down. `Simulator.stop()` is
    idempotent (see `AI2ThorEnv`), so calling it for a simulator that
    never fully started is safe.
    """
    if simulator is None:
        return
    try:
        simulator.stop()
    except Exception:
        logger.warning("api.simulator_stop_failed", exc_info=True)


def _start_vision_and_tasks(app: FastAPI):
    """
    Starts the opt-in simulator and everything that needs it, filling
    `app.state.simulator`/`vision_system`. Returns the started
    simulator (or `None`) -- *including* when a later step failed and
    the simulator was already stopped here, so the caller can always
    call `_stop_simulator()` on whatever this returns. Never raises:
    any failure degrades to "vision unavailable" (see this module's
    docstring).
    """
    simulator = None
    if os.environ.get("VISION_ENABLE_SIMULATOR", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        depth_source = os.environ.get("VISION_DEPTH_SOURCE", DEPTH_SOURCE_GROUND_TRUTH)
        try:
            simulator = Simulator(
                render_depth=(depth_source == DEPTH_SOURCE_GROUND_TRUTH),
                platform=_resolve_simulator_platform(),
            )
            simulator.start()
            # Stored on `app.state` (not just closed over as a local),
            # so the teardown branch below can find and stop the exact
            # same instance -- this is the fix for a Phase 4 stability
            # bug where the simulator was never retained anywhere, so
            # nothing could ever call `simulator.stop()` on shutdown/
            # reload, and repeated `uvicorn --reload` cycles each
            # started a new, never-stopped Unity subprocess until WSLg
            # ran out of resources (`Wsl/Service/E_UNEXPECTED`).
            app.state.simulator = simulator
            app.state.vision_system = build_vision_system(
                simulator, depth_source=depth_source
            )
            # `routes/tasks.py`'s Orchestrator needs a running
            # simulator to execute plans against -- built here, right
            # alongside `vision_system`, rather than lazily per
            # request, for the same "construct once, at startup"
            # rationale as `language_agent`/`memory_agent` above.
            # `vision_agent` wraps the exact same `VisionAgent`
            # `vision_system.agent` already is -- Orchestrator's
            # OBSERVE step (section 7.16) and `GET /api/v1/vision/
            # perceive` therefore perceive through the identical
            # perception pipeline, never a second competing one.
            # `app.state.vision_system` can itself be `None` here (a
            # test double, or a real detector/model failure inside
            # `build_vision_system` that -- unlike an unavailable
            # simulator -- does not need to take the simulator down
            # too); Orchestrator's OBSERVE step already treats no
            # `vision_agent` as "skip observation," so this stays None
            # rather than raising.
            vision_agent = (
                VisionAgentWrapper(app.state.vision_system.agent)
                if app.state.vision_system is not None
                else None
            )
            orchestrator = build_orchestrator(
                simulator,
                memory_agent=MemoryAgentWrapper(app.state.memory_agent),
                vision_agent=vision_agent,
                llm_client=_planner_llm_client(app.state.language_config),
            )
            if orchestrator.registry is not None:
                orchestrator.registry.register(app.state.speech_agent)
        except Exception as exc:
            # Any startup failure here (missing Unity binary, missing
            # model weights, ...) must degrade to "vision unavailable,"
            # never crash the app -- see this module's docstring.
            logger.warning(
                "api.vision_system_unavailable",
                extra={"exception_type": type(exc).__name__},
            )
            # The simulator may already be running (the failure came
            # after `start()`): stop it now rather than leaking a Unity
            # subprocess that nothing will ever reference again.
            _stop_simulator(simulator)
            simulator = None
            app.state.simulator = None
            app.state.vision_system = None
    # `LanguageAgent`'s collaborators hold no network connections or
    # file handles that outlive a single call, so no teardown is needed
    # for it. The simulator is different -- `_lifespan`'s `finally`
    # stops it on every exit path (see there).
    return simulator


app = FastAPI(
    title="Vision-Language Robotics API",
    description=(
        "HTTP interface around this project's Language Understanding "
        "runtime (Phase 3.4/3.5/3.7), Spatial & Temporal Perception "
        "Vision subsystem (Phase 3.x), and Task Planning subsystem "
        "(Phase 4, backend/planner/). The Language API converts a "
        "natural language instruction into a validated ParsedInstruction; "
        "the Vision API perceives the simulator's current scene "
        "(detection, segmentation, depth, tracking, scene graph); the "
        "Planner API expands a task into a validated, simulator-"
        "independent Plan; the Execution API (Phase 5) drives a "
        "validated Plan through the simulator step by step, with "
        "explicit state tracking, precondition checking, and result "
        "validation. Vision and Planning/Execution are not yet fused "
        "(a Plan is planned and executed against a fresh WorldState, "
        "not one grounded in a live Vision scene) -- see "
        "backend/docs/language_interface_spec.md section 30, "
        "docs/architecture/spatial_perception.md, and "
        "docs/phases/phase5_execution.md."
    ),
    version="5.0.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
    # `POST /api/v1/voice/speak` (routes/voice.py) returns MILO's
    # spoken response text in this header alongside the audio body --
    # browsers hide all but a small "safe" set of response headers
    # from JS by default, so it must be explicitly exposed here or the
    # dialogue bubble could never read it.
    expose_headers=["X-Milo-Response-Text", "Retry-After"],
)

app.include_router(health_router)
# Optional guards (off unless API_KEY / RATE_LIMIT_PER_MINUTE are set) on the
# routers that run jobs or change things -- see `api/security.py`.
_GUARDED = [Depends(require_api_key), Depends(rate_limit)]

app.include_router(
    lab_router, prefix="/api/v1/lab", tags=["lab"], dependencies=_GUARDED
)
app.include_router(language_router, prefix="/api/v1/language", tags=["language"])
app.include_router(
    memory_router,
    prefix="/api/v1/memory",
    tags=["memory"],
    dependencies=[Depends(require_api_key)],
)
app.include_router(planner_router, prefix="/api/v1/planner", tags=["planner"])
app.include_router(vision_router, prefix="/api/v1/vision", tags=["vision"])
app.include_router(execution_router, prefix="/api/v1/execution", tags=["execution"])
app.include_router(
    tasks_router, prefix="/api/v1/tasks", tags=["tasks"], dependencies=_GUARDED
)
app.include_router(speech_router, prefix="/api/v1/speech", tags=["speech"])
app.include_router(voice_router, prefix="/api/v1/voice", tags=["voice"])
app.include_router(agents_router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(
    traces_router, prefix="/api/v1/traces", tags=["traces"], dependencies=_GUARDED
)
app.include_router(
    skills_router, prefix="/api/v1/skills", tags=["skills"], dependencies=_GUARDED
)
app.include_router(benchmark_router, prefix="/api/v1/benchmark", tags=["benchmark"])
app.include_router(scene_map_router, prefix="/api/v1/scene", tags=["scene"])


_STATUS_MESSAGES = {
    404: "I couldn't find that. Check the address and try again.",
    405: "That isn't something I can do at this address.",
}


@app.exception_handler(StarletteHTTPException)
async def _handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    # Routes raise `HTTPException` with `detail={"category": ..., "message":
    # ...}` (matching `api/models/language.py`'s `ErrorResponse`). This
    # handler flattens that dict to the top level of the response body
    # instead of FastAPI's default `{"detail": {...}}` wrapping, so every
    # error response -- validation or runtime -- has the exact same shape
    # a client can rely on. It also catches Starlette's own 404/405, which
    # would otherwise be a bare `{"detail": "Not Found"}`.
    if isinstance(exc.detail, dict) and "category" in exc.detail:
        content = exc.detail
    else:
        content = {
            "category": "internal_error",
            "message": _STATUS_MESSAGES.get(exc.status_code, str(exc.detail)),
        }
    return JSONResponse(
        status_code=exc.status_code, content=content, headers=exc.headers
    )


def _friendly_validation_message(errors: list) -> str:
    """One sentence a person can act on, from pydantic's first error."""
    if not errors:
        return "The request isn't quite right. Please check it and try again."
    first = errors[0]
    loc = [str(part) for part in first.get("loc", ()) if part != "body"]
    field = loc[-1] if loc else "request"
    kind = first.get("type", "")
    msg = first.get("msg", "")
    if field == "instruction" and kind in ("string_too_short", "missing"):
        return "Please tell MILO what to do -- the instruction can't be empty."
    if field == "instruction" and kind == "string_too_long":
        return "That instruction is too long. Please keep it under 2000 characters."
    if field == "planner":
        return (
            "I don't know that planner. Choose one of: rule_based, react, "
            "behavior_tree, htn."
        )
    if kind == "missing":
        return f"Something is missing: '{field}' is required."
    if msg.startswith("Value error, "):
        return msg[len("Value error, ") :]
    return f"There's a problem with '{field}': {msg}"


@app.exception_handler(RequestValidationError)
async def _handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Overrides FastAPI's default `{"detail": [...]}` shape (a raw list
    # of pydantic error dicts) with this API's `ErrorResponse` shape
    # (`api/models/language.py`) so every error response -- request
    # validation or runtime failure -- looks the same to a client, and
    # the message is a sentence the UI can show as-is. Safe to build from
    # pydantic's own text: it describes the *request's* shape, never
    # anything from the LLM provider or a credential.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "category": "invalid_request",
            "message": _friendly_validation_message(list(exc.errors())),
        },
    )


@app.exception_handler(Exception)
async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Final safety net: any exception that escapes a route handler
    # without already being translated (i.e. a bug in this API layer
    # itself, not a `LanguageRuntimeError` -- those are already handled
    # in `routes/language.py`) is logged server-side with its type only
    # and reported to the client as a generic, stack-trace-free 500.
    logger.error(
        "api.unhandled_exception",
        extra={"exception_type": type(exc).__name__, "path": request.url.path},
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "category": "internal_error",
            "message": "Something went wrong on my side. Please try again in a moment.",
        },
    )
