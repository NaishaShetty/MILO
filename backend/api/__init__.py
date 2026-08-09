"""
backend/api

Purpose
-------
Phase 3.7's HTTP interface layer around the already-complete Language
Understanding subsystem (`backend/language/`, `backend/schemas/`). This
package exists so a frontend (or any other external caller) can submit
a natural language instruction over HTTP and receive back a validated
`ParsedInstruction`, without that caller ever needing to import Python,
hold an LLM provider credential, or know anything about prompts,
retries, or schema validation.

Why this is a separate top-level package from `backend/language/`
-------------------------------------------------------------------
`backend/language/` is the Phase 3.4/3.5 *runtime* -- it has no notion
of HTTP, request/response envelopes, or CORS, and must not gain one:
every consumer of this runtime (a CLI, a test, this API, and
eventually the Phase 4 Planner) should see the exact same
`LanguageAgent.parse()`/`parse_with_diagnostics()` contract. `backend/api/`
depends on `backend/language/`; the reverse dependency must never
exist. See `backend/docs/language_interface_spec.md` section 30 for
the full architectural boundary this package is required to respect.

What lives here
----------------
- `app.py`: the FastAPI application object, CORS configuration, and
  the `LanguageAgent` lifecycle (constructed once at startup, reused
  across requests).
- `routes/language.py`: the `POST /api/v1/language/parse` endpoint --
  translates HTTP request/response to/from `LanguageAgent` calls and
  maps `LanguageRuntimeError` subclasses to safe HTTP responses.
- `routes/health.py`: a dependency-free liveness check.
- `models/language.py`: Pydantic request/response envelopes for the
  API contract. These are deliberately distinct from
  `backend/schemas/task.py` -- they describe the *HTTP* contract
  (status, diagnostics, error shape), not the task data itself, which
  is always the real `ParsedInstruction` serialized as-is.
"""
