"""
backend/api/routes

Purpose
-------
FastAPI `APIRouter` modules. Each module owns exactly one resource
(`health.py` -> liveness, `language.py` -> the parse endpoint) and
contains no language-understanding logic itself -- every route
function's body is "validate input shape, call `LanguageAgent`,
translate the result/exception to an HTTP response", nothing more. See
`backend/api/__init__.py` for the full architectural boundary this is
required to respect.
"""
