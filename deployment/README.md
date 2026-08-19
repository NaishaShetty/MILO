# deployment/

Current deployment status
--------------------------
**MILO is not currently deployed publicly.** Running it against a real
GPU host turned out to require infrastructure (a dedicated CUDA-capable
machine, always-on hosting) that isn't feasible to maintain at this
stage, so the project's priority right now is local reproducibility --
anyone cloning this repo can run the full stack on their own machine
(see the root README's Quick Start).

The configuration below is real and was build/run-verified against a
real backend, but is not currently running anywhere public.

**Backend** -- a GPU-enabled Docker image (`docker/Dockerfile.gpu`,
CUDA 12.1 + headless AI2-THOR `CloudRendering`) and
`docker-compose.prod.yml`, which fronts it with a Cloudflare Quick
Tunnel (no purchased domain required) rather than a public port -- see
that file's header comment for the full setup and its "Quick Tunnel
limitations" section for why this isn't an always-on production
deployment (the tunnel's URL is random and changes every time the
`cloudflared` container restarts).

It is **not** deployable to a stateless/serverless platform like
Vercel: task execution runs in a background thread inside the FastAPI
process (`backend/api/routes/tasks.py`) that outlives the triggering
request, `MemoryConfig`/`SQLiteMemoryStore` persist to a local file
(`backend/outputs/memory/memory.db`), and
`VISION_ENABLE_SIMULATOR=true` launches a real AI2-THOR/Unity
subprocess (`backend/api/app.py`'s lifespan) -- none of which survive
a stateless, short-lived-per-request serverless execution model.

**Frontend** -- a static Vite build (`frontend/`, `npm run build`),
deployable to any static host (Vercel, Netlify, etc.). There's no
host-specific config checked into this repo, since there's currently
no live backend for it to point at -- standing one up just needs a
rewrite/proxy rule sending `/api` and `/health` to the real backend
origin (matching what `frontend/nginx.conf.template` does in the
Docker setup), plus that backend's `API_ALLOWED_ORIGINS` updated to
include the frontend's deployed origin.

If the backend is exposed via a Cloudflare Quick Tunnel (see above),
its hostname changes on every tunnel restart, so any static frontend
rewrite/proxy config pointing at it needs updating and redeploying
each time -- inherent to the free Quick Tunnel approach, not something
to work around.

Purpose
-------
Home for everything needed to run this project outside a local dev
checkout -- configuration for deploying the perception/planning stack
to a real robot, a cloud inference endpoint, or a long-running
simulation host.

Why it's separate from `backend/`
-------------------------------------
`backend/` answers "how does perception/planning work." `deployment/`
answers "how does a working system get onto a target environment" --
environment-specific configuration, secrets management, process
supervision, and (per `docs/architecture/perception_pipeline.md`'s
simulator-swap design) eventually the config that points the
`Simulator` abstraction at a real robot instead of AI2-THOR. Neither
concern should leak into the other: `backend/` code should never
hardcode a deployment target, and deployment configuration should
never need to know how a model is implemented internally.

Planned contents
-----------------
- Environment-specific config (dev / simulation / real-robot).
- Process/service definitions for running `VisionAgent` +
  `PerceptionPipeline` continuously rather than as a one-shot script.
- Once a real robot target exists: the concrete `Simulator`-interface
  implementation and its deployment config, kept out of
  `backend/simulator/` itself so swapping targets doesn't touch the
  interface.

See also `docker/README.md` for containerization, which this
directory is expected to reference once a target is defined.

Nothing is implemented here yet -- this file establishes the
directory's purpose ahead of that work.
