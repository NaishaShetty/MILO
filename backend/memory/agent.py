"""
agent.py (backend/memory)

Purpose
-------
Phase 6.3's `MemoryAgent` -- the application-level interface between
the robot (Planner, Execution, a future Reflection module) and the
memory subsystem. Every non-memory caller in this repository is
expected to depend on `MemoryAgent`, never on `MemoryManager`,
`RetrievalEngine`, `SQLiteMemoryStore`, or `SQLiteVectorStore`
directly -- this is what keeps memory from becoming hidden state
reached into from arbitrary call sites (the phase spec's section 6).

```
Planner / Execution / Reflection
              |
              v
        MemoryAgent (this module)
              |
              v
        RetrievalEngine (memory.retrieval, Phase 6.2)
              |
       +------+------+
       v             v
   MemoryManager   Embedder
   (Phase 6.1)     + VectorStore
```

Why this module still knows nothing about `execution`/`planner`
------------------------------------------------------------------------
`MemoryAgent`'s public methods accept `memory.semantics.EpisodicDetails`
/`FailureDetails` (Phase 6.2 types) plus plain `episode_id`/`task_id`
strings -- never `execution.models.ExecutionRecord` or
`planner.models.Plan`. Translating an `ExecutionRecord` into
`EpisodicDetails`/`FailureDetails` is `backend/orchestration/`'s job
(the one module that legitimately depends on both `execution` and
`memory`), not this one's -- keeping `backend/memory/` exactly as
self-contained as Phase 6.1/6.2 left it, per this phase's "do not
redesign 6.1/6.2" instruction.

Graceful degradation -- section 5's core requirement
---------------------------------------------------------
Every public method on `MemoryAgent` catches every exception the
underlying `RetrievalEngine`/`MemoryManager` call could raise
(`memory.exceptions.MemoryError` and anything a corrupted/unavailable
backend could throw) and degrades to a safe, well-defined fallback
(an empty `PlannerMemoryContext`, or `None` for a write) rather than
propagating -- logging a warning with enough structure to debug, never
silently. `MemoryAgent.from_config()` applies the same policy to
*construction* itself: if `RetrievalEngine`/`SQLiteMemoryStore`/
`SQLiteVectorStore` fail to initialize (e.g. an unwritable disk), the
returned `MemoryAgent` is simply `is_available() == False` rather than
raising out of a caller's startup path. A caller (the orchestrator)
never needs its own try/except around a `MemoryAgent` call -- that
would just be this same logic, duplicated at every call site.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from memory.config import MemoryConfig
from memory.conflicts import store_semantic_observation
from memory.embeddings import EmbeddingConfig
from memory.models import Memory, MemoryProvenance, MemoryType
from memory.retrieval import (
    MemoryResult,
    RankingWeights,
    RetrievalContext,
    RetrievalEngine,
    build_retrieval_engine,
)
from memory.semantics import (
    EpisodicDetails,
    FailureDetails,
    build_episodic_memory,
    build_failure_memory,
    build_semantic_memory,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryQueryContext:
    """
    Structured, inspectable input to memory retrieval -- section 3.
    Deliberately built from fields already present on `schemas.task.
    SingleTask` (`goal`/`object`/`target`) rather than a duplicate task
    model; `location`/`observations`/`user` are the fields no existing
    task model carries. Every field is optional -- a caller supplies
    whatever it actually knows, and `MemoryAgent` builds a retrieval
    query and a `memory.retrieval.RetrievalContext` from exactly what
    was given, nothing invented.
    """

    task_id: Optional[str] = None
    episode_id: Optional[str] = None
    goal: Optional[str] = None
    object: Optional[str] = None
    target: Optional[str] = None
    location: Optional[str] = None
    observations: Sequence[str] = field(default_factory=tuple)
    user: Optional[str] = None

    def to_query_text(self) -> str:
        """
        Builds the natural-language-ish query string `RetrievalEngine.
        retrieve()` embeds -- every populated field, space-joined, in a
        fixed field order (deterministic, matching `memory.
        representation`'s "no ad-hoc string formatting per caller"
        convention).
        """
        parts = [
            value
            for value in (self.goal, self.object, self.target, self.location)
            if value
        ]
        parts.extend(self.observations)
        return " ".join(parts)


@dataclass(frozen=True)
class PlannerMemoryContext:
    """
    What a `Planner` actually receives -- section 4's "structured
    context, not hidden global state." Carries the query that produced
    `results` (for logging/`Plan.metadata`, so a plan is
    self-explanatory about what memory query informed it) alongside the
    ranked `memory.retrieval.MemoryResult`s themselves -- reusing that
    Phase 6.2 type directly rather than inventing a second "memory
    handed to the planner" shape, since it already carries exactly the
    confidence/provenance/recency/similarity detail section 4's example
    rendering calls for.
    """

    query: str
    results: List[MemoryResult] = field(default_factory=list)
    episode_id: Optional[str] = None
    task_id: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return not self.results

    def summary(self) -> Dict[str, Any]:
        """
        A small, loggable/`Plan.metadata`-able digest -- section 19's
        observability fields (`memory_query`, `number_of_memories_
        retrieved`, `memory_ids`), never the full `Memory.content`/
        `metadata` payloads (keeps logs/plan records small and free of
        anything that could be sensitive user data).
        """
        return {
            "query": self.query,
            "count": len(self.results),
            "memory_ids": [r.memory.memory_id for r in self.results],
        }


class MemoryAgent:
    """
    High-level, application-facing memory operations -- see this
    module's docstring for the full architectural role. Wraps exactly
    one `RetrievalEngine` (Phase 6.2); never touches `sqlite3`, a
    vector store, or an embedding model directly.
    """

    def __init__(self, engine: Optional[RetrievalEngine]) -> None:
        # `engine is None` is the "memory subsystem unavailable"
        # state -- see `from_config()`. Every public method checks
        # this first and short-circuits to the safe fallback.
        self._engine = engine

    @classmethod
    def from_config(
        cls,
        memory_config: MemoryConfig,
        embedding_config: Optional[EmbeddingConfig] = None,
        weights: Optional[RankingWeights] = None,
    ) -> "MemoryAgent":
        """
        Production entry point. Never raises: if constructing the
        underlying `RetrievalEngine` fails for any reason (unwritable
        disk, corrupted database, ...), logs a warning and returns a
        `MemoryAgent` with `is_available() == False` instead of taking
        down whatever is starting up the robot -- section 5's "the
        robot must remain functional if... the memory subsystem is
        temporarily unavailable," applied at construction time too.
        """
        try:
            engine = build_retrieval_engine(memory_config, embedding_config, weights)
        except Exception:
            logger.warning("memory_agent.unavailable", exc_info=True)
            return cls(engine=None)
        return cls(engine=engine)

    def is_available(self) -> bool:
        return self._engine is not None

    @property
    def engine(self) -> Optional[RetrievalEngine]:
        """
        The underlying `RetrievalEngine`, or `None` if unavailable --
        read-only, exposed for callers (chiefly tests) that need to
        verify a write actually reached storage; ordinary callers
        should never need this, since every operation `MemoryAgent`
        supports already has its own method.
        """
        return self._engine

    # -- retrieval ----------------------------------------------------

    def retrieve_relevant_memories(
        self,
        context: MemoryQueryContext,
        *,
        memory_types: Optional[Sequence[MemoryType]] = None,
        top_k: int = 5,
        now: Optional[float] = None,
    ) -> PlannerMemoryContext:
        """
        Retrieves memories relevant to `context` -- section 4's
        "Planner -> Memory Flow." Never raises: an empty/unavailable
        memory subsystem, a retrieval exception, or a query that
        matches nothing all produce an empty `PlannerMemoryContext`
        (`is_empty == True`), which every consumer of this method
        (`Planner.plan()`) is required to treat as "proceed with
        normal planning," never as an error condition (section 5).
        """
        query = context.to_query_text()
        empty = PlannerMemoryContext(
            query=query,
            results=[],
            episode_id=context.episode_id,
            task_id=context.task_id,
        )
        if self._engine is None or not query.strip():
            return empty

        retrieval_context = RetrievalContext(
            episode_id=context.episode_id,
            task_id=context.task_id,
            metadata_filters=(
                {"location": context.location} if context.location else {}
            ),
        )
        started_at = time.monotonic()
        try:
            results = self._engine.retrieve(
                query,
                memory_types=memory_types,
                context=retrieval_context,
                top_k=top_k,
                now=now,
            )
        except Exception:
            logger.warning(
                "memory_agent.retrieval_failed",
                exc_info=True,
                extra={"task_id": context.task_id, "episode_id": context.episode_id},
            )
            return empty
        latency_ms = (time.monotonic() - started_at) * 1000.0

        logger.info(
            "memory_agent.retrieved",
            extra={
                "task_id": context.task_id,
                "episode_id": context.episode_id,
                "memory_query": query,
                "number_of_memories_retrieved": len(results),
                "memory_ids": [r.memory.memory_id for r in results],
                "retrieval_latency_ms": latency_ms,
            },
        )
        return PlannerMemoryContext(
            query=query,
            results=results,
            episode_id=context.episode_id,
            task_id=context.task_id,
        )

    # -- listing --------------------------------------------------------

    def list_memories(
        self,
        *,
        memory_type: Optional[MemoryType] = None,
        limit: Optional[int] = None,
    ) -> List[Memory]:
        """
        Thin passthrough to `MemoryManager.list()` (`manager.py`),
        newest first -- the read-only counterpart to `retrieve_relevant_
        memories()` for callers that want an unranked listing/browse
        view (e.g. the Phase 8.2 Memory API) rather than a query-scored
        retrieval. Never raises: an unavailable memory subsystem or a
        store error both degrade to an empty list, matching every other
        method on this class.
        """
        if self._engine is None:
            return []
        try:
            return self._engine.manager.list(memory_type=memory_type, limit=limit)
        except Exception:
            logger.warning("memory_agent.list_failed", exc_info=True)
            return []

    # -- writes: episodic / failure / observation --------------------

    def remember_episode(
        self,
        details: EpisodicDetails,
        *,
        episode_id: str,
        task_id: Optional[str] = None,
        provenance: MemoryProvenance = MemoryProvenance.EXECUTION,
        confidence: float = 1.0,
        recovered_failure_ids: Optional[Sequence[str]] = None,
    ) -> Optional[Memory]:
        """
        Persists one episodic memory -- section 9's "Execution ->
        Episodic Memory." Returns `None` (never raises) if the memory
        subsystem is unavailable or the write fails, logging a warning
        either way -- a failed memory write must never fail the task
        that produced it (section 5). `recovered_failure_ids`, when
        given, links this episode to prior failure memories it
        recovered from (section 11) -- see `link_recovery()`.
        """
        memory = build_episodic_memory(
            details,
            provenance=provenance,
            confidence=confidence,
            episode_id=episode_id,
            task_id=task_id,
        )
        stored = self._store_and_index(memory, event="episodic")
        if stored is not None and recovered_failure_ids:
            self.link_recovery(stored.memory_id, recovered_failure_ids)
            # `link_recovery()` re-fetches its own copy of `stored` from
            # the store to mutate/persist -- keep the object handed back
            # to *this* caller in sync with what was just written, so a
            # caller inspecting the returned `Memory` sees the same
            # `recovered_from` tag a fresh `manager.get()` would.
            stored.metadata["recovered_from"] = list(recovered_failure_ids)
        return stored

    def remember_failure(
        self,
        details: FailureDetails,
        *,
        episode_id: str,
        task_id: Optional[str] = None,
        provenance: MemoryProvenance = MemoryProvenance.EXECUTION,
        confidence: float = 1.0,
    ) -> Optional[Memory]:
        """
        Persists one failure memory -- section 10's "Execution Failure
        -> Failure Memory." `details.cause`/`details.recovery` are
        expected to already be `None` (rendered as `"unknown"` by
        `representation.format_failure_content`) when the caller has no
        actual evidence -- this method never invents one; see
        `FailureDetails`' own docstring and section 10's explicit
        "do NOT hallucinate a cause" requirement, enforced by the
        caller (`backend/orchestration/`) never this method.
        """
        memory = build_failure_memory(
            details,
            provenance=provenance,
            confidence=confidence,
            episode_id=episode_id,
            task_id=task_id,
        )
        return self._store_and_index(memory, event="failure")

    def remember_observation(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        provenance: MemoryProvenance,
        confidence: float = 1.0,
        episode_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Optional[Memory]:
        """
        Persists one controlled semantic-memory observation -- section
        12's "controlled pathway," never a raw per-frame dump (section
        13). The caller (`backend/orchestration/`) is responsible for
        deciding an observation is worth remembering at all; this
        method's only added value is turning that decision into a
        `Memory`, running it through `conflicts.
        store_semantic_observation()` (so a duplicate/conflicting prior
        observation is tagged, never silently overwritten -- Phase
        6.2's conflict policy), and degrading safely on failure.
        """
        memory = build_semantic_memory(
            subject,
            predicate,
            object_,
            provenance=provenance,
            confidence=confidence,
            episode_id=episode_id,
            task_id=task_id,
        )
        if self._engine is None:
            logger.warning(
                "memory_agent.write_skipped_unavailable",
                extra={"event": "observation", "subject": subject},
            )
            return None
        try:
            stored = store_semantic_observation(self._engine.manager, memory)
            self._engine.index_memory(stored)
        except Exception:
            logger.warning(
                "memory_agent.write_failed",
                exc_info=True,
                extra={"event": "observation", "subject": subject},
            )
            return None
        logger.info(
            "memory_agent.memory_created",
            extra={
                "memory_type": MemoryType.SEMANTIC.value,
                "memory_id": stored.memory_id,
                "episode_id": episode_id,
                "task_id": task_id,
            },
        )
        return stored

    def link_recovery(
        self, episode_memory_id: str, failure_memory_ids: Sequence[str]
    ) -> None:
        """
        Tags `episode_memory_id`'s metadata with the failure memories it
        recovered from, and each referenced failure memory with the
        episode that recovered it -- section 11's "preserve the failure
        experience" alongside the successful outcome, via the same
        non-destructive metadata-tagging pattern `memory.conflicts`
        already established for duplicate/conflict relationships
        (never deletes or rewrites `content`, only adds a metadata
        cross-reference). Failures here (a referenced id no longer
        existing, a storage error) are logged and otherwise ignored --
        this is enrichment, not a task-critical write.
        """
        if self._engine is None:
            return
        manager = self._engine.manager
        try:
            episode = manager.get(episode_memory_id)
            if episode is not None:
                episode.metadata["recovered_from"] = list(failure_memory_ids)
                manager.update(episode)
            for failure_id in failure_memory_ids:
                failure = manager.get(failure_id)
                if failure is not None:
                    failure.metadata["recovered_by"] = episode_memory_id
                    manager.update(failure)
        except Exception:
            logger.warning("memory_agent.link_recovery_failed", exc_info=True)

    # -- internal -----------------------------------------------------

    def _store_and_index(self, memory: Memory, *, event: str) -> Optional[Memory]:
        if self._engine is None:
            logger.warning(
                "memory_agent.write_skipped_unavailable",
                extra={"event": event, "memory_type": memory.memory_type.value},
            )
            return None
        try:
            stored = self._engine.store_and_index(memory)
        except Exception:
            logger.warning(
                "memory_agent.write_failed",
                exc_info=True,
                extra={"event": event, "memory_type": memory.memory_type.value},
            )
            return None
        logger.info(
            "memory_agent.memory_created",
            extra={
                "memory_type": stored.memory_type.value,
                "memory_id": stored.memory_id,
                "episode_id": stored.episode_id,
                "task_id": stored.task_id,
            },
        )
        return stored
