"""
voice (backend/voice)

Purpose
-------
Phase 8.2's ElevenLabs voice subsystem: real speech-to-text and
text-to-speech, backed by the ElevenLabs API. Mirrors `backend/speech/`'s
package shape (`config.py`, `errors.py`, a client module) deliberately --
same "config -> typed errors -> one client class, wrapped by an Agent"
pattern, so a caller familiar with `backend/speech/` already knows how
to read this package.

Why this is a separate package from `backend/speech/`, not an extension
of it
------------------------------------------------------------------------
`backend/speech/` is explicitly, structurally Whisper-only (see that
package's own docstring) and already has callers depending on its
narrow "audio bytes in, transcript out, nothing else" contract.
`backend/voice/` adds a second, independent capability -- ElevenLabs
STT *and* TTS -- without touching or risking that existing, tested
path. The two are expected to coexist: `SPEECH_ENABLE_WHISPER` and
`VOICE_ENABLE_ELEVENLABS` are independent opt-in switches.

Scope boundary
-------------------------------------------------
Nothing in this package imports `planner`, `execution`, `orchestration`,
or `schemas.task` directly -- `voice/response_composer.py` is the one
exception permitted to read `agents.task_state.TaskState` and
`memory.retrieval.MemoryResult`, since composing a spoken summary is
inherently about those types' real, structured fields (never inventing
facts -- see that module's docstring). Turning speech into a task
remains `language.agent.LanguageAgent`'s job, exactly as it already is
for `backend/speech/` and typed text input.
"""
