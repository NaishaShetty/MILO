"""
retrieval.py (backend/memory)

Purpose
-------
Phase 6.2's retrieval engine: `RetrievalEngine.retrieve()` turns a
natural-language query plus optional structured `RetrievalContext` into
a ranked, explainable list of `MemoryResult`s. This is the first real
consumer of `memory.store.VectorStore` (Phase 6.1 defined the
interface; `sqlite_vector_store.py` implements it; this module wires
embedder + vector store + structured store together) and the only
module in this package that combines them -- `MemoryManager` itself
stays exactly as Phase 6.1 left it (no retrieval/ranking logic was
added there, per that phase's explicit scope boundary).

Pipeline (see `docs/phases/phase6_memory.md` for the full diagram)
--------------------------------------------------------------------
```
query --embed--> query vector --vector_store.search--> raw candidates
    --hard filter (type/status/time window)--> passing candidates
    --score (similarity+confidence+recency+provenance+context)--> MemoryResult[]
    --sort by (-final_score, -created_at, memory_id)--> top_k
```

Why vector search runs before structured filtering, not the other way
around
------------------------------------------------------------------------
`VectorStore.search()` (Phase 6.1's interface) has no filter parameter
-- it only ever accepts a query vector and `top_k`. This implementation
therefore over-fetches a *candidate pool* (`top_k *
candidate_pool_multiplier`, floored at `min_candidate_pool`) from the
vector store first, then applies structured filters and hard-context
checks to that pool in Python (fetching each candidate's full `Memory`
via `MemoryManager.get()`, which is already backed by indexed SQLite
columns -- see `sqlite_store.py`). This is the standard "retrieve then
filter" hybrid-retrieval shape used whenever the vector backend cannot
push filters down into the similarity search itself; a future
`VectorStore` implementation with native filtered search (e.g. a real
vector database's metadata-filter support) could push these same
filters down without changing this module's public API.

Hard filters vs. soft context scoring -- a deliberate split
------------------------------------------------------------------
Three things are **hard filters** (a mismatch excludes the candidate
entirely, never merely lowers its score): `memory_types` (a caller
asking for `FAILURE` memories should never see a `SEMANTIC` one),
lifecycle/`status` (an `ARCHIVED` memory is excluded by default, per
Phase 6.1's own documented intent for that status -- see
`models.MemoryStatus.ARCHIVED`'s docstring), and an explicit
`time_start`/`time_end` window (a caller who asked for "what happened
last week" should never see memories from a year ago). Everything else
context can express -- `episode_id`, `task_id`, arbitrary
`metadata_filters` (e.g. `{"location": "kitchen"}`) -- is a **soft
ranking signal** (`context_relevance`, below), not a filter: a semantic
memory about apple storage has no `episode_id` at all and should still
be retrievable for a query scoped to a specific episode, just not
boosted the way an actually-matching memory is. Hard-filtering on
episode/task/metadata would silently exclude exactly the
cross-episode, cross-task knowledge (semantic and user memory,
especially) retrieval is supposed to surface.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from memory.config import MemoryConfig
    from memory.embeddings import EmbeddingConfig

from memory.embeddings import Embedder
from memory.manager import MemoryManager
from memory.models import Memory, MemoryProvenance, MemoryStatus, MemoryType
from memory.representation import canonical_text
from memory.store import VectorStore

# ---------------------------------------------------------------------
# Ranking configuration
# ---------------------------------------------------------------------

#: Default per-provenance trust weight (section 13 -- "make provenance
#: effects configurable; document the default policy"). Rationale:
#: direct evidence (`OBSERVATION`, `USER_INPUT`) is maximally trusted;
#: `EXECUTION` results are near-direct (a simulator ground-truth
#: postcondition check, per `execution.validator.ResultValidator`) so
#: scored just under direct observation; `SYSTEM` defaults are
#: middling (not evidence, but not a guess either); `INFERENCE` and
#: `REFLECTION` are derived from other memories/reasoning, so they are
#: scored lowest -- a chain of inference should never automatically
#: outrank the observations it was inferred from.
_DEFAULT_PROVENANCE_SCORES: Dict[MemoryProvenance, float] = {
    MemoryProvenance.OBSERVATION: 1.0,
    MemoryProvenance.USER_INPUT: 1.0,
    MemoryProvenance.EXECUTION: 0.9,
    MemoryProvenance.SYSTEM: 0.7,
    MemoryProvenance.INFERENCE: 0.6,
    MemoryProvenance.REFLECTION: 0.5,
}

_SECONDS_PER_DAY = 86400.0


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw is not None else default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw is not None else default


@dataclass(frozen=True)
class RankingWeights:
    """
    Every configurable ranking parameter -- section 11/23's "make
    weights configurable, document the rationale" and "all meaningful
    retrieval parameters should be configurable." Defaults below are a
    documented starting point, not a tuned result (no labeled
    relevance-judgment dataset exists yet to tune against) -- see
    `backend/memory_evaluation/` for the infrastructure that makes
    comparing alternate weight sets (the phase spec's "ablation")
    possible.

    Default weights: similarity is the dominant signal (0.45) because
    it is the only signal that actually measures "does this memory
    answer the query" -- every other component is a *trust/relevance
    modifier* on top of that base match, not a substitute for it.
    Confidence is second (0.20) per the phase spec's explicit example
    ("a highly similar memory with very low confidence should not
    automatically outrank a slightly less similar but highly reliable
    memory") -- weighted high enough to matter, not so high it
    overwhelms similarity. Recency (0.15) and provenance (0.10) are
    modest tie-breakers. Context (0.10) is smallest because it is
    already doing indirect work by shrinking the candidate pool before
    scoring even begins (memory_types/status/time-window hard filters).
    """

    similarity: float = 0.45
    confidence: float = 0.20
    recency: float = 0.15
    provenance: float = 0.10
    context: float = 0.10

    #: Half-life of the exponential recency decay, in seconds. Default:
    #: 7 days -- short-horizon household tasks (this project's target
    #: domain) make a week-old observation meaningfully "fresher" than
    #: a month-old one, but not so aggressively that a two-day-old
    #: memory is nearly discounted to zero.
    recency_half_life_seconds: float = 7 * _SECONDS_PER_DAY

    #: Per-provenance trust score -- see `_DEFAULT_PROVENANCE_SCORES`'s
    #: comment for the rationale. Treated as immutable by convention
    #: (a frozen dataclass field can still hold a mutable dict; callers
    #: must not mutate this in place -- construct a new `RankingWeights`
    #: with a different `provenance_scores` instead).
    provenance_scores: Dict[MemoryProvenance, float] = field(
        default_factory=lambda: dict(_DEFAULT_PROVENANCE_SCORES)
    )
    default_provenance_score: float = 0.5

    #: Raw (unclipped) vector similarity below this value excludes a
    #: candidate outright, before scoring -- `0.0` (the default) means
    #: no cutoff (every candidate the vector store returns is scored).
    similarity_threshold: float = 0.0

    #: How large a candidate pool to pull from the vector store before
    #: structured filtering -- `max(min_candidate_pool, top_k *
    #: candidate_pool_multiplier)`. Larger values cost more `MemoryManager
    #: .get()` calls but reduce the chance that a restrictive
    #: `RetrievalContext` filters the pool down to fewer than `top_k`
    #: results.
    candidate_pool_multiplier: int = 5
    min_candidate_pool: int = 20

    @classmethod
    def from_env(cls) -> "RankingWeights":
        """
        Env-driven construction, matching `memory.config.MemoryConfig
        .from_env()`'s convention. `provenance_scores` is deliberately
        not individually env-configurable (six separate variables for
        one rarely-tuned setting is not worth the configuration
        surface) -- pass a custom `RankingWeights(provenance_scores=
        {...})` in code for that.
        """
        return cls(
            similarity=_float_env("MEMORY_RETRIEVAL_WEIGHT_SIMILARITY", 0.45),
            confidence=_float_env("MEMORY_RETRIEVAL_WEIGHT_CONFIDENCE", 0.20),
            recency=_float_env("MEMORY_RETRIEVAL_WEIGHT_RECENCY", 0.15),
            provenance=_float_env("MEMORY_RETRIEVAL_WEIGHT_PROVENANCE", 0.10),
            context=_float_env("MEMORY_RETRIEVAL_WEIGHT_CONTEXT", 0.10),
            recency_half_life_seconds=_float_env(
                "MEMORY_RETRIEVAL_RECENCY_HALF_LIFE_SECONDS", 7 * _SECONDS_PER_DAY
            ),
            similarity_threshold=_float_env(
                "MEMORY_RETRIEVAL_SIMILARITY_THRESHOLD", 0.0
            ),
            candidate_pool_multiplier=_int_env(
                "MEMORY_RETRIEVAL_CANDIDATE_POOL_MULTIPLIER", 5
            ),
            min_candidate_pool=_int_env("MEMORY_RETRIEVAL_MIN_CANDIDATE_POOL", 20),
        )


# ---------------------------------------------------------------------
# Query context
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalContext:
    """
    Optional structured context accompanying a query -- section 9's
    "task, room, object, target, episode, user, time window," narrowed
    to what this repository's actual schema supports (no `room`/
    `target` field exists on `Memory` itself; those are expressed via
    `metadata_filters` against whatever key a memory's `metadata`
    actually uses, e.g. `{"location": "kitchen"}` for an episodic
    memory built by `semantics.build_episodic_memory`). See this
    module's docstring for which fields are hard filters vs. soft
    ranking signals.
    """

    episode_id: Optional[str] = None
    task_id: Optional[str] = None
    #: Exact-match filters against `Memory.metadata` -- e.g.
    #: `{"location": "kitchen"}`, `{"subject": "user"}`. Soft signal
    #: (contributes to `context_relevance`), not a hard filter.
    metadata_filters: Dict[str, Any] = field(default_factory=dict)
    #: Inclusive Unix-seconds window against `observed_at` (falling
    #: back to `created_at` when unset). Hard filter.
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    #: Explicit lifecycle filter -- when set, only memories with this
    #: exact status are returned (hard filter). When `None` (the
    #: default), `include_archived` decides.
    status: Optional[MemoryStatus] = None
    #: When `status` is unset, whether `ARCHIVED` memories are eligible
    #: at all. Default `False` -- matches Phase 6.1's documented intent
    #: for `MemoryStatus.ARCHIVED` ("excluded from ordinary retrieval").
    include_archived: bool = False


def _passes_hard_filters(memory: Memory, context: RetrievalContext) -> bool:
    if context.status is not None:
        if memory.status != context.status:
            return False
    elif not context.include_archived and memory.status != MemoryStatus.ACTIVE:
        return False

    reference_time = (
        memory.observed_at if memory.observed_at is not None else memory.created_at
    )
    if context.time_start is not None and reference_time < context.time_start:
        return False
    if context.time_end is not None and reference_time > context.time_end:
        return False
    return True


def _context_relevance(memory: Memory, context: RetrievalContext) -> float:
    """
    Fraction of the *specified* soft-context checks this memory
    matches -- `1.0` when no soft-context field was given at all (no
    signal to penalize against, so this component stays neutral rather
    than arbitrarily dragging every unscoped query's scores down).
    """
    signals: List[float] = []
    if context.episode_id is not None:
        signals.append(1.0 if memory.episode_id == context.episode_id else 0.0)
    if context.task_id is not None:
        signals.append(1.0 if memory.task_id == context.task_id else 0.0)
    for key, value in context.metadata_filters.items():
        signals.append(1.0 if memory.metadata.get(key) == value else 0.0)
    if not signals:
        return 1.0
    return sum(signals) / len(signals)


def _recency_score(memory: Memory, now: float, half_life_seconds: float) -> float:
    """
    `2 ** (-age / half_life)` -- exponential decay reaching exactly
    `0.5` at one half-life, deterministic given `age`/`half_life`.
    Never negative, never mutates or removes the underlying memory
    (section 14: "recency should influence ranking, not erase
    history") -- an old memory always scores lower on this one
    component, never disappears from `list()`/storage.
    """
    reference_time = (
        memory.observed_at if memory.observed_at is not None else memory.created_at
    )
    age = max(0.0, now - reference_time)
    if half_life_seconds <= 0:
        return 0.0
    return 2.0 ** (-age / half_life_seconds)


# ---------------------------------------------------------------------
# Retrieval result
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryResult:
    """
    One ranked retrieval result -- section 12's "do not return raw
    database/vector-store records." `ranking_components` and
    `retrieval_metadata` together make every score fully explainable
    (section 18) without re-running retrieval: every number that went
    into `final_score` is recorded, not just the score itself.
    """

    memory: Memory
    similarity: float
    final_score: float
    ranking_components: Dict[str, float]
    retrieval_metadata: Dict[str, Any]

    def explain(self) -> str:
        """Human-readable rendering of this result, per section 18's example."""
        c = self.ranking_components
        lines = [
            f"Memory: {self.memory.content}",
            f"Similarity: {c.get('similarity', 0.0):.2f}",
            f"Confidence: {c.get('confidence', 0.0):.2f}",
            f"Recency: {c.get('recency', 0.0):.2f}",
            f"Provenance: {self.memory.provenance.value} "
            f"(score {c.get('provenance', 0.0):.2f})",
            f"Context relevance: {c.get('context', 0.0):.2f}",
            f"Final score: {self.final_score:.2f}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------
# Retrieval engine
# ---------------------------------------------------------------------


class RetrievalEngine:
    """
    Coordinates embedding, vector search, structured filtering, and
    ranking. Depends only on `MemoryManager` (Phase 6.1, unmodified),
    `memory.store.VectorStore` (interface), and `memory.embeddings.
    Embedder` (interface) -- never a concrete backend directly.
    """

    def __init__(
        self,
        manager: MemoryManager,
        vector_store: VectorStore,
        embedder: Embedder,
        weights: Optional[RankingWeights] = None,
    ) -> None:
        self._manager = manager
        self._vector_store = vector_store
        self._embedder = embedder
        self._weights = weights or RankingWeights()

    @property
    def manager(self) -> MemoryManager:
        """
        The underlying `MemoryManager` -- exposed (Phase 6.3 addition)
        for callers that need direct store/get/update access this
        engine's own methods don't cover (e.g. `memory.agent.
        MemoryAgent` running `conflicts.store_semantic_observation()`,
        which needs a `MemoryManager` to check existing memories
        against, then this same engine to index the result). Read-only
        -- callers must not reassign it; write access is still only
        ever through `MemoryManager`'s own API or this engine's
        `store_and_index`/`update_and_reindex`/`delete_and_deindex`.
        """
        return self._manager

    # -- indexing -------------------------------------------------

    def index_memory(self, memory: Memory) -> None:
        """Embeds `memory`'s canonical text and upserts it into the vector store."""
        vector = self._embedder.embed(canonical_text(memory))
        self._vector_store.upsert(
            memory.memory_id,
            vector,
            metadata={"memory_type": memory.memory_type.value},
        )

    def store_and_index(self, memory: Memory) -> Memory:
        """`MemoryManager.store()` + `index_memory()` in one call."""
        stored = self._manager.store(memory)
        self.index_memory(stored)
        return stored

    def update_and_reindex(self, memory: Memory) -> Memory:
        """`MemoryManager.update()` + re-embedding in one call."""
        updated = self._manager.update(memory)
        self.index_memory(updated)
        return updated

    def delete_and_deindex(self, memory_id: str) -> None:
        """`MemoryManager.delete()` + vector removal in one call."""
        self._manager.delete(memory_id)
        self._vector_store.delete(memory_id)

    def reindex_all(self) -> int:
        """
        Rebuilds the vector store from every memory currently in the
        structured store (active and archived) -- used after a bulk
        load, a vector-store migration, or in tests that seed
        `MemoryManager` directly. Returns the number of memories
        indexed.
        """
        memories = self._manager.list()
        for memory in memories:
            self.index_memory(memory)
        return len(memories)

    # -- retrieval --------------------------------------------------

    def retrieve(
        self,
        query: str,
        *,
        memory_types: Optional[Sequence[MemoryType]] = None,
        context: Optional[RetrievalContext] = None,
        top_k: int = 5,
        now: Optional[float] = None,
    ) -> List[MemoryResult]:
        """
        Retrieves up to `top_k` memories relevant to `query`. See this
        module's docstring for the full pipeline and the hard-filter /
        soft-context-signal split. `now` is an explicit parameter
        (defaulting to `time.time()`) specifically so recency scoring
        is testable/deterministic without monkeypatching the clock.
        """
        resolved_now = now if now is not None else time.time()
        resolved_context = context or RetrievalContext()
        allowed_types = set(memory_types) if memory_types else None

        query_vector = self._embedder.embed(query)
        pool_size = max(
            self._weights.min_candidate_pool,
            top_k * self._weights.candidate_pool_multiplier,
        )
        raw_candidates = self._vector_store.search(query_vector, top_k=pool_size)

        results: List[MemoryResult] = []
        for candidate in raw_candidates:
            if candidate.score < self._weights.similarity_threshold:
                continue
            memory = self._manager.get(candidate.memory_id)
            if memory is None:
                # Vector store and structured store have drifted (e.g.
                # a memory was deleted via the structured store
                # without going through `delete_and_deindex()`) --
                # skip rather than raise, since a stale vector-store
                # entry is not this call's fault to fix.
                continue
            if allowed_types is not None and memory.memory_type not in allowed_types:
                continue
            if not _passes_hard_filters(memory, resolved_context):
                continue

            score, components = self._score(
                memory, candidate.score, resolved_context, resolved_now
            )
            results.append(
                MemoryResult(
                    memory=memory,
                    similarity=candidate.score,
                    final_score=score,
                    ranking_components=components,
                    retrieval_metadata={
                        "query": query,
                        "retrieved_at": resolved_now,
                    },
                )
            )

        results.sort(
            key=lambda r: (-r.final_score, -r.memory.created_at, r.memory.memory_id)
        )
        top_results = results[:top_k]
        for rank, result in enumerate(top_results):
            result.retrieval_metadata["rank"] = rank
        return top_results

    def _score(
        self,
        memory: Memory,
        similarity: float,
        context: RetrievalContext,
        now: float,
    ) -> Tuple[float, Dict[str, float]]:
        weights = self._weights
        similarity_clipped = max(0.0, min(1.0, similarity))
        confidence = memory.confidence
        recency = _recency_score(memory, now, weights.recency_half_life_seconds)
        provenance_score = weights.provenance_scores.get(
            memory.provenance, weights.default_provenance_score
        )
        context_relevance = _context_relevance(memory, context)

        total_weight = (
            weights.similarity
            + weights.confidence
            + weights.recency
            + weights.provenance
            + weights.context
        )
        weighted_sum = (
            weights.similarity * similarity_clipped
            + weights.confidence * confidence
            + weights.recency * recency
            + weights.provenance * provenance_score
            + weights.context * context_relevance
        )
        final_score = (
            weighted_sum / total_weight if total_weight > 0 else similarity_clipped
        )

        components = {
            "similarity": similarity_clipped,
            "confidence": confidence,
            "recency": recency,
            "provenance": provenance_score,
            "context": context_relevance,
            "weight_similarity": weights.similarity,
            "weight_confidence": weights.confidence,
            "weight_recency": weights.recency,
            "weight_provenance": weights.provenance,
            "weight_context": weights.context,
        }
        return final_score, components


def build_retrieval_engine(
    memory_config: "MemoryConfig",
    embedding_config: Optional["EmbeddingConfig"] = None,
    weights: Optional[RankingWeights] = None,
) -> RetrievalEngine:
    """
    Production entry point wiring Phase 6.1's `MemoryConfig` (storage)
    together with Phase 6.2's `EmbeddingConfig`/`RankingWeights` --
    mirrors `MemoryManager.from_config()`'s role for storage alone.
    `memory_config.vector_store_path` was reserved, unused, in Phase
    6.1 specifically for this: it is used here (as a directory --
    `vectors.db` is created inside it) to construct the
    `SQLiteVectorStore`, so no Phase 6.1 file needs to change for this
    wiring to exist. `embedding_config` defaults to `EmbeddingConfig
    .from_env()`; `weights` defaults to `RankingWeights()` (code
    defaults, not `RankingWeights.from_env()` -- callers who want
    env-driven weights pass `RankingWeights.from_env()` explicitly, so
    "which weights a given engine uses" is always visible at the call
    site rather than implied by environment state).
    """
    # Imported here, not at module scope, to avoid a needless import
    # cycle risk (this is the only function in the module that needs
    # every concrete Phase 6.1 + 6.2 piece at once).
    from memory.embeddings import EmbeddingConfig, get_embedder
    from memory.sqlite_vector_store import SQLiteVectorStore

    resolved_embedding_config = embedding_config or EmbeddingConfig.from_env()
    embedder = get_embedder(resolved_embedding_config)
    manager = MemoryManager.from_config(memory_config)
    vector_store = SQLiteVectorStore(
        memory_config.vector_store_path / "vectors.db",
        dimension=embedder.dimension,
    )
    return RetrievalEngine(manager, vector_store, embedder, weights=weights)
