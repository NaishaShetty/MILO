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
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agents.memory_agent import MemoryAgentWrapper
from agents.speech_agent import SpeechAgent
from agents.vision_agent import VisionAgentWrapper
from api.routes.agents import router as agents_router
from api.routes.execution import router as execution_router
from api.routes.health import router as health_router
from api.routes.language import router as language_router
from api.routes.planner import router as planner_router
from api.routes.speech import router as speech_router
from api.routes.tasks import build_orchestrator
from api.routes.tasks import router as tasks_router
from api.routes.vision import router as vision_router
from language.agent import LanguageAgent
from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from simulator.simulator import Simulator
from speech.config import SpeechConfig
from speech.whisper_client import WhisperTranscriber
from vision.factory import DEPTH_SOURCE_GROUND_TRUTH, build_vision_system

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
    # Constructed once per process. `LanguageAgent.from_config()` reads
    # `LanguageRuntimeConfig.from_env()` internally -- this app never
    # touches provider/model/prompt configuration directly, per this
    # package's "do not duplicate Phase 3 configuration" boundary.
    app.state.language_agent = LanguageAgent.from_config()

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
    app.state.speech_agent = SpeechAgent(
        WhisperTranscriber.from_config(SpeechConfig.from_env())
    )

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
    if os.environ.get("VISION_ENABLE_SIMULATOR", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        depth_source = os.environ.get("VISION_DEPTH_SOURCE", DEPTH_SOURCE_GROUND_TRUTH)
        try:
            simulator = Simulator(
                render_depth=(depth_source == DEPTH_SOURCE_GROUND_TRUTH)
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
            app.state.simulator = None
            app.state.vision_system = None

    yield
    # `LanguageAgent`'s collaborators hold no network connections or
    # file handles that outlive a single call, so no teardown is needed
    # for it. The simulator is different: `Simulator.start()` (via
    # `AI2ThorEnv.start()`) launches a real Unity subprocess, and the OS
    # does NOT reliably reclaim it the moment this process exits --
    # under `uvicorn --reload`, the *same* process keeps running across
    # reloads, so skipping this call is exactly what let old Unity
    # instances pile up (see the startup comment above). The FastAPI
    # lifespan is this simulator's owner for its entire lifetime, so it
    # is also responsible for explicitly releasing it here, every time,
    # regardless of how shutdown was triggered.
    if app.state.simulator is not None:
        try:
            app.state.simulator.stop()
        finally:
            app.state.simulator = None


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
    allow_headers=["Content-Type"],
)

app.include_router(health_router)
app.include_router(language_router, prefix="/api/v1/language", tags=["language"])
app.include_router(planner_router, prefix="/api/v1/planner", tags=["planner"])
app.include_router(vision_router, prefix="/api/v1/vision", tags=["vision"])
app.include_router(execution_router, prefix="/api/v1/execution", tags=["execution"])
app.include_router(tasks_router, prefix="/api/v1/tasks", tags=["tasks"])
app.include_router(speech_router, prefix="/api/v1/speech", tags=["speech"])
app.include_router(agents_router, prefix="/api/v1/agents", tags=["agents"])


@app.exception_handler(HTTPException)
async def _handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    # `routes/language.py`'s error mapper always raises `HTTPException`
    # with `detail={"category": ..., "message": ...}` (matching
    # `api/models/language.py`'s `ErrorResponse`). This handler flattens
    # that dict to the top level of the response body instead of
    # FastAPI's default `{"detail": {...}}` wrapping, so every error
    # response -- validation or runtime -- has the exact same shape a
    # client can rely on.
    if isinstance(exc.detail, dict) and "category" in exc.detail:
        content = exc.detail
    else:
        content = {"category": "internal_error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def _handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Overrides FastAPI's default `{"detail": [...]}` shape (a raw list
    # of pydantic error dicts) with this API's `ErrorResponse` shape
    # (`api/models/language.py`) so every error response -- request
    # validation or runtime failure -- looks the same to a client.
    # Safe to include pydantic's own message text here: it describes
    # the *request body's* shape (e.g. "instruction must not be empty
    # or whitespace-only"), never anything from the LLM provider or a
    # credential.
    first_error = exc.errors()[0] if exc.errors() else {}
    message = first_error.get("msg", "The request body is invalid.")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"category": "invalid_request", "message": message},
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
            "message": "An unexpected error occurred. Please try again later.",
        },
    )
