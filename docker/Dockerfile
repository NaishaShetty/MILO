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
RUN pip install -r requirements.txt

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
