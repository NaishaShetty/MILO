"""
representation.py (backend/memory)

Purpose
-------
Defines exactly how a `Memory` becomes the text an `Embedder`
(`embeddings.py`) actually embeds. Per the phase spec, this must be
deterministic, documented, and never "embed the raw JSON serialization
of the object" -- a JSON blob's key ordering/punctuation/braces are
embedding noise that has nothing to do with the fact being represented,
and would make two memories describing the identical relationship
embed differently depending on incidental metadata like `memory_id` or
timestamps.

Design: `content` IS the canonical representation
-------------------------------------------------------
`semantics.py`'s `build_*_memory` factories already compute `Memory.
content` from structured fields via the `format_*_content` functions
in this module -- so for any `Memory` built through those factories,
`canonical_text(memory)` is simply `memory.content`: there is exactly
one formatting step, not two representations that could drift apart.
For a `Memory` constructed by hand (bypassing the factories --
possible but discouraged), `canonical_text()` still falls back to
`memory.content`, since `content` is documented (`models.py`) as
"the" primary payload regardless of how a `Memory` was built.

Why per-type formatting functions are exposed separately
--------------------------------------------------------------
`format_semantic_triple_content`/`format_episodic_content`/
`format_failure_content` are the actual deterministic formatters --
kept here (not inlined into `semantics.py`) so this module is the
single place that owns "what does a canonical sentence for type X look
like," independent of how a `Memory` gets constructed. A future
milestone reformatting episodic memories (e.g. to include more detail)
changes exactly one function here.
"""

from __future__ import annotations

# `semantics` is imported lazily inside each formatter's type hint via
# TYPE_CHECKING to avoid a circular import (`semantics.py` imports
# these formatters); the formatters only ever access plain attributes,
# so no runtime import of `semantics` is needed here.
from typing import TYPE_CHECKING, Protocol

from memory.models import Memory

if TYPE_CHECKING:  # pragma: no cover
    from memory.semantics import EpisodicDetails, FailureDetails


class _Triple(Protocol):
    """
    Structural type for anything triple-shaped -- both `semantics.
    SemanticTriple` and `semantics.UserFact` satisfy this without
    either needing to subclass the other (they are deliberately
    distinct nominal types -- see `semantics.py`'s `UserFact`
    docstring for why). A `Protocol` here (rather than importing both
    concrete classes) is what lets `format_semantic_triple_content`
    serve both without `semantics.py` and this module import-cycling.
    """

    subject: str
    predicate: str
    object: str


def format_semantic_triple_content(triple: _Triple) -> str:
    """
    Canonical sentence for a subject/predicate/object triple --
    `"red_mug located_on dining_table"`. A fixed `"{subject}
    {predicate} {object}"` template (not a free-form English sentence
    like "the red mug is located on the dining table") deliberately: it
    is trivially deterministic (no grammar/pluralization choices to
    keep consistent), and every triple with the same three fields
    produces byte-identical text regardless of caller.

    Deliberately *without* a `"Subject: ... | Predicate: ..."` label
    scaffold (an earlier version of this function used one): those
    labels are identical across every triple regardless of content, so
    they act as pure noise for `embeddings.HashingEmbedder` -- diluting
    the token-overlap signal that actually distinguishes one triple
    from another and measurably hurting retrieval precision (verified
    empirically against `backend/memory_evaluation/dataset.py`). A
    future learned-embedding provider would likely be far less
    sensitive to this, but the plain, label-free form is strictly
    better for the deterministic hashing embedder and no worse for any
    other, so it is the default for every provider.
    """
    return f"{triple.subject} {triple.predicate} {triple.object}"


def format_episodic_content(details: "EpisodicDetails") -> str:
    """
    Canonical sentence for an episodic memory -- includes the task,
    location, outcome, and objects involved (the fields most likely to
    match a future retrieval query) followed by the free-form summary
    last, so the structured facts are never at the mercy of a summary
    that a caller might phrase inconsistently.
    """
    parts = [f"Task: {details.task_summary}", f"Outcome: {details.outcome}"]
    if details.location:
        parts.append(f"Location: {details.location}")
    if details.relevant_objects:
        parts.append(f"Objects: {', '.join(details.relevant_objects)}")
    if details.duration_seconds is not None:
        parts.append(f"Duration: {details.duration_seconds:.0f}s")
    return " | ".join(parts)


def format_failure_content(details: "FailureDetails") -> str:
    """
    Canonical sentence for a failure memory -- task, action, and
    failure reason first (the fields a "why did X fail" query is most
    likely to match against), cause/context/recovery/outcome appended
    when present.
    """
    parts = [
        f"Task: {details.task}",
        f"Action: {details.action}",
        f"Failure: {details.failure_reason}",
    ]
    if details.cause:
        parts.append(f"Cause: {details.cause}")
    if details.context:
        parts.append(f"Context: {details.context}")
    if details.recovery:
        parts.append(f"Recovery: {details.recovery}")
    if details.outcome:
        parts.append(f"Outcome: {details.outcome}")
    return " | ".join(parts)


def canonical_text(memory: Memory) -> str:
    """
    The single entry point `embeddings.py`/`retrieval.py` call to turn
    a `Memory` into embeddable text. See this module's docstring for
    why this is `memory.content`, never a JSON dump of the whole
    record.
    """
    return memory.content
