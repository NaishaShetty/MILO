# docker/

Purpose
-------
Home for container definitions that make this project's environment
reproducible -- pinned CUDA/PyTorch/`transformers` versions, AI2-THOR's
Unity dependencies, and the project-local `models/` weight cache
described in `docs/phases/phase2_vision.md#modelmanager`.

Why it matters for this project specifically
-------------------------------------------------
`config/model_manager.py` already avoids depending on a user's global
Hugging Face cache so runs are reproducible across machines; a
container definition here is the same idea one level up -- pinning the
OS/CUDA/Python environment so a checkout behaves identically on a
teammate's machine, a CI runner, or a deployment target (see
`deployment/README.md`).

Current contents
-----------------
- `Dockerfile` -- builds a reproducible backend environment: Python
  3.9, `backend/requirements.txt`, and the system libraries
  `opencv-python` needs at runtime. Build from the repository root
  (see the root `README.md`'s "Engineering Infrastructure" section for
  the exact commands):

  ```
  docker build -f docker/Dockerfile -t vision-language-robotics-backend .
  docker run --rm -p 8000:8000 vision-language-robotics-backend
  ```

  `COPY backend/ ./` packages the entire `backend/` tree as it exists
  today -- not a fixed phase snapshot -- so later backend-only
  additions (e.g. Phase 6 Memory, Phase 7 Agents/Orchestration) are
  included automatically and have never required a Dockerfile change,
  since none of them added a new system/Python dependency beyond what
  `backend/requirements.txt` already declared.

  `torch`/`torchvision` in `backend/requirements.txt` have no index
  constraint, so a plain `pip install -r requirements.txt` would pull
  PyPI's default (CUDA-bundled) wheels into this CPU-only, no-GPU
  image (Phase 8.5 fix). The `Dockerfile` installs the CPU-only build
  from PyTorch's own package index
  (`--index-url https://download.pytorch.org/whl/cpu`) *before* the
  general `requirements.txt` install, so that install is a no-op for
  those two packages -- local/GPU development
  (`backend/scripts/download_torch.py`) is unaffected, since only this
  image's install order changed.

  By default the container runs the FastAPI service (`uvicorn
  api.app:app --host 0.0.0.0 --port 8000`, published on `EXPOSE 8000`)
  -- `GET /health` answers immediately with no configuration; routes
  that need an LLM provider key (e.g. `POST /api/v1/language/parse`)
  return a safe `503 configuration_error` until `OPENAI_API_KEY` /
  `GEMINI_API_KEY` is passed via `docker run -e` (never baked into the
  image). The same image doubles as a test/shell environment by
  overriding `CMD`, e.g. `docker run --rm
  vision-language-robotics-backend python -m pytest tests/`. Runs as a
  non-root `appuser`. The frontend (`frontend/`) is a separate
  Vite/Node project **not** built by this image -- see
  `frontend/README.md`.

Phase 5 (Execution)
--------------------
`backend/execution/` adds no new Python dependency (it reuses
`backend/requirements.txt` as-is), so the existing `Dockerfile` already
covers it code-wise. AI2-THOR/Unity itself is deliberately NOT bundled
into this image, same as before Phase 5: it needs a display/GPU
environment this slim backend image does not provide, and blindly
containerizing it would fight that constraint rather than solve it.
The supported workflow is: run this image (or a local `backend/`
checkout) for the API/tests, and run AI2-THOR/Unity on a machine that
actually has a display -- `POST /api/v1/execution/start` degrades to a
clean `503 execution_unavailable` in this image, exactly like the
Vision API already does, until `VISION_ENABLE_SIMULATOR=true` is set
against a simulator-capable host.

Phase 8.4 (Docker, Deployment & CI/CD)
----------------------------------------
- `../frontend/Dockerfile` -- the frontend's own production image
  (multi-stage: `npm run build`, then nginx serving the static
  output). Lives in `frontend/` rather than here so its build context
  is just that project, not the whole repo -- see that Dockerfile's
  own docstring.
- `../docker-compose.yml` (repo root) -- runs both images together,
  wired the way `frontend/nginx.conf.template` expects (the frontend
  reverse-proxies `/api`/`/health` to the backend by its compose
  service name, `backend`, so the frontend never needs an absolute
  backend URL -- same relative-URL contract as local dev's Vite
  proxy). Usage:

  ```
  cp backend/.env.example backend/.env   # fill in a real LLM API key
  docker compose up --build
  # frontend: http://localhost:8080
  # backend directly (optional): http://localhost:8000/health
  ```

  Both images now define a `HEALTHCHECK` (backend: `GET /health` via
  Python's stdlib, no curl/wget dependency; frontend: `GET /` via
  nginx's own image). `.github/workflows/ci.yml`'s `docker` job builds
  both on every push/PR (no registry push) and smoke-tests the backend
  container with zero credentials configured.
- Secrets: `backend/.env` is read only at container *run* time via
  `docker-compose.yml`'s `env_file:` (marked `required: false`, so
  compose still starts without it) -- never copied into either image
  (see `.dockerignore` at the repo root and `frontend/.dockerignore`'s
  "Env / secrets" sections).

Planned contents
-----------------
- A GPU-enabled variant for running the perception pipeline (Grounding
  DINO, SAM2) with CUDA, and AI2-THOR/Unity's own dependencies (not yet
  needed -- the current `Dockerfile` covers the code that can run
  headless). AI2-THOR/Unity itself still needs a display/GPU
  environment neither container here provides -- see the Phase 5 note
  above; docker-compose's two services cover the API + web UI, not the
  simulator.
