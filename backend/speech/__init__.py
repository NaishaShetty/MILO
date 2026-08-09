"""
speech (backend/speech)

Purpose
-------
Phase 7.14's speech-to-text subsystem: audio bytes in, a transcript
out, nothing else. Mirrors `backend/language/`'s package shape
(`config.py`, `errors.py`/`exceptions.py`, a client module) so a
caller familiar with one already knows how to read the other.

Scope boundary (7.14's explicit requirement)
-------------------------------------------------
Nothing in this package imports `planner`, `execution`, `memory`, or
`schemas.task` -- enforced structurally, not just by convention.
Turning a transcript into a `SingleTask` is `language.agent.
LanguageAgent`'s job, exactly as it already is for typed text input;
`agents.speech_agent.SpeechAgent` (the `BaseAgent` wrapper around this
package) is the only thing downstream code depends on, and it exposes
`transcribe()` only -- never a shortcut into task creation.
"""
