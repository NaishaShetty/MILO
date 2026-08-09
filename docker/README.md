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
  the exact commands). It packages the backend as it exists today
  (Phases 1-3.5, including the Language Parsing Runtime and its output
  validation/error recovery layer) and deliberately runs nothing by
  default -- there is still no FastAPI service (Phase 3.7+).

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

Planned contents
-----------------
- A GPU-enabled variant for running the perception pipeline (Grounding
  DINO, SAM2) with CUDA, and AI2-THOR/Unity's own dependencies (not yet
  needed -- the current `Dockerfile` covers the code that can run
  headless).
- `docker-compose` (or equivalent) wiring, once more than one service
  needs to run together (e.g. simulator + perception + a future API
  server).
