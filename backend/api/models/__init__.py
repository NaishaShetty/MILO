"""
backend/api/models

Purpose
-------
Pydantic models describing the HTTP contract of Phase 3.7's API --
request bodies, response envelopes, and the safe error shape returned
to clients. Kept separate from `backend/schemas/` deliberately: those
models describe *task* data (`ParsedInstruction`); these describe the
*transport* around it (status, diagnostics, error category). See
`language.py`'s module docstring for the full rationale.
"""
