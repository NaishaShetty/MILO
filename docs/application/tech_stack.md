# MILO — Technical Stack

Only technologies actually present in this repository's dependencies and
imports — nothing aspirational.

## Backend

- **Python**, **FastAPI** + **Uvicorn** — the API layer (`backend/api/`).
- **Pydantic** — request/response/domain models throughout.
- **AI2-THOR** — the simulated robot environment (`backend/simulator/`).
- **Grounding DINO** — open-vocabulary object detection.
- **SAM2** (Segment Anything 2) — segmentation.
- **SQLite** + a vector store — memory persistence
  (`backend/memory/sqlite_store.py`, `sqlite_vector_store.py`).
- **LLM providers** (pluggable, provider-abstracted): OpenAI, Google
  Gemini, or a local Qwen-compatible OpenAI-API server (vLLM/Ollama) —
  `backend/language/provider_factory.py`.
- **OpenAI Whisper** — local speech-to-text.
- **ElevenLabs** — speech-to-text (alternative provider) and
  text-to-speech.
- **pytest** — the backend test suite.

## Frontend

- **React** + **TypeScript**, built with **Vite**.
- **react-router-dom** — client-side routing across the 7 pages.
- **Vitest** + **@testing-library/react** — unit/component tests.
- **Playwright** — real-browser E2E tests, including the Phase 8.6
  screenshot workflow.
- No CSS framework — a single hand-authored `index.css` using CSS
  custom properties for the dark/violet MILO design system (see
  `docs/architecture/milo_state_system.md` and the Phase 8.2 design
  tokens at the top of `frontend/src/index.css`).
- No state management library beyond React Context — six purpose-built
  contexts (see `architecture.md`), each a thin polling wrapper.

## Infrastructure

- **Docker** + **docker-compose** — containerized backend/frontend.
- **nginx** — frontend production serving (`frontend/nginx.conf.template`).
- **GitHub Actions** — CI (`.github/workflows/ci.yml`).

## Explicitly not used

- No WebSocket/SSE transport — all real-time UI updates are polling.
- No message queue / event bus between agents — direct method calls
  orchestrated by a single `Orchestrator` instance.
- No ORM — SQLite accessed directly for memory storage.
- No third-party UI/component library.
