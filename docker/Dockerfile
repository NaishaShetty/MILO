# syntax=docker/dockerfile:1
#
# Production Dockerfile for the backend (perception + language schema
# code under backend/). Build from the repository root so it can see
# backend/:
#
#   docker build -f docker/Dockerfile -t vision-language-robotics-backend .
#
# Scope: this image installs and packages the backend as it exists
# today (Phases 1-3.7), including the Language Parsing Runtime, its
# Phase 3.5 output validation/error recovery layer (OpenAI + Gemini
# providers -- both speak plain HTTP via `requests`, already in
# backend/requirements.txt, so no new system dependency was needed for
# Gemini support), and the Phase 3.7 FastAPI service (`backend/api/`).
# The frontend (`frontend/`) is NOT built by this image -- it is a
# separate Vite/Node project with its own build; see the CMD note at
# the bottom and `frontend/README.md`.

FROM python:3.9-slim

# Matches backend/scripts/download_torch.py's cp39 wheel and the
# interpreter pinned in .github/workflows/ci.yml.
LABEL org.opencontainers.image.description="Vision-Language Robotics backend"

# Reproducible, container-friendly Python behavior: no .pyc files, no
# output buffering (so logs stream immediately), no pip cache (keeps
# the image smaller and every build reinstalling from the same lockable
# requirements file rather than a stale wheel cache).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System libraries required at import time by opencv-python
# (backend/requirements.txt) -- not needed to build the wheel, but
# missing them makes `import cv2` fail at runtime on a slim base image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only the dependency manifest first so this layer is cached
# across builds unless requirements.txt actually changes.
COPY backend/requirements.txt ./requirements.txt

# Install CPU-only torch/torchvision wheels *before* the general
# requirements.txt install (Phase 8.5 fix). requirements.txt pins
# `torch>=2.5.1`/`torchvision>=0.20.1` with no index constraint, so a
# bare `pip install -r requirements.txt` pulls PyPI's default wheels,
# which bundle multi-GB CUDA runtime libraries -- dead weight in this
# image, which never launches AI2-THOR/Unity and has no GPU to use
# them with (see this file's own note below on why the simulator isn't
# bundled here). Installing the CPU-only build from PyTorch's own
# index first satisfies the requirement before pip ever considers the
# default index, so the general install below is a no-op for these two
# packages. Local/GPU development is unaffected: this only changes
# what this Docker image installs, not backend/requirements.txt or
# backend/scripts/download_torch.py (which developers use to fetch a
# CUDA build for actual GPU work).
#
# `--extra-index-url`, not `--index-url`: `--index-url` *replaces*
# PyPI outright for this command, not just adds PyTorch's index as a
# preferred source. torch's own dependency resolution here still pulls
# in ordinary PyPI packages (e.g. typing-extensions) alongside
# torch/torchvision themselves; when pip has to fall back to building
# one of those from an sdist (observed in CI: a `typing-extensions`
# wheel was discarded over a package-name normalization mismatch,
# forcing a build from source), that build's own PEP 517 backend
# (`flit_core`) has to come from somewhere -- and with a bare
# `--index-url` restricting the whole command to
# download.pytorch.org/whl/cpu, which mirrors PyTorch's own packages
# only, there is nowhere for it to come from, and the install fails
# with "Could not find a version that satisfies the requirement
# flit_core<4,>=3.11". `--extra-index-url` keeps PyPI available as a
# fallback for every package this command touches besides torch/
# torchvision themselves, while pip still prefers the CPU-only builds
# from PyTorch's index for those two -- the documented approach from
# PyTorch's own install instructions for exactly this "CPU build,
# still need everything else from PyPI" case.
RUN pip install "torch>=2.5.1" "torchvision>=0.20.1" \
        --extra-index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

# Now copy the backend source itself. .dockerignore (repo root) keeps
# caches, test artifacts, and unrelated top-level directories (models/,
# datasets/, docs/, frontend/, ...) out of the build context.
COPY backend/ ./

# Run as a non-root user in the final image.
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# Published by the Phase 3.7 FastAPI service (uvicorn, below).
EXPOSE 8000

# GET /health (backend/api/routes/health.py) never calls the LLM
# provider or the simulator -- see that module's docstring -- so this
# stays a cheap, purely-local liveness probe. Uses Python's stdlib
# rather than curl/wget, neither of which this slim image installs.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

# Runs the Phase 3.7 API by default. No LLM provider credential is
# baked into the image or required to build/start it -- the container
# starts and answers GET /health without one; POST /api/v1/language/parse
# only fails at request time (a safe 503 "configuration_error", see
# backend/api/routes/language.py) if OPENAI_API_KEY/GEMINI_API_KEY was
# not supplied via `docker run -e` (never in the image itself). The
# image remains equally usable for the test suite or a shell by
# overriding this CMD, e.g.:
#   docker run --rm vision-language-robotics-backend python -m pytest tests/
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
