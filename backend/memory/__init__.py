"""
memory (backend/memory)

Purpose
-------
Phase 6.1 (Memory Foundation) + Phase 6.2 (Memory Intelligence). Phase
6.1 established the contracts, schemas, persistence, storage
abstractions, and configuration for a `Memory` domain type -- no
retrieval, no ranking, no embeddings. Phase 6.2 builds the intelligence
layer on top of that foundation, unmodified: type-specific structure
for the four `MemoryType`s (`semantics.py`), a deterministic embedding
pipeline (`embeddings.py`), a concrete `VectorStore` (`sqlite_vector_
store.py`), and a hybrid retrieval + ranking engine (`retrieval.py`)
that returns explainable `MemoryResult`s. Still no planner integration,
no Memory Agent, no execution-> memory wiring, no reflection, no
autonomous memory formation -- those remain Phase 6.3+.

```
Application (future Memory Agent, Planner integration -- Phase 6.3+)
        |
        v
RetrievalEngine (retrieval.py)          MemoryManager (manager.py)
   |         |                                |
   |         +--------------------------------+
   |                          |
   |                          +----------------> MemoryStore (store.py, interface)
   |                                                  |
   |                                                  v
   |                                          SQLiteMemoryStore (sqlite_store.py) -> SQLite
   |
   +--> Embedder (embeddings.py, interface)
   |        |
   |        v
   |   HashingEmbedder (deterministic, offline)
   |
   +--> VectorStore (store.py, interface)
            |
            v
    SQLiteVectorStore (sqlite_vector_store.py) -> SQLite (brute-force cosine search)
```

Query path: `query --embed--> vector --VectorStore.search--> candidates
--hard filter (type/status/time)--> --score (similarity, confidence,
recency, provenance, context)--> MemoryResult[]`. See `retrieval.py`'s
own docstring for the full pipeline and `docs/phases/phase6_memory.md`
for the diagram + rationale.

Why the domain layer still never depends on SQLite/a vector backend
directly
--------------------------------------------------------------------------
Unchanged from Phase 6.1: `models.Memory` and `manager.MemoryManager`
depend only on `store.MemoryStore`; `retrieval.RetrievalEngine` depends
only on `store.VectorStore` and `embeddings.Embedder` -- never on
`sqlite3`/`numpy`-specific details directly. `sqlite_store.py` and
`sqlite_vector_store.py` are the only modules that import `sqlite3`.

Module map
----------
Phase 6.1 (unchanged):
- `models.py`        -- `Memory`, `MemoryType`, `MemoryProvenance`,
                         `MemoryStatus`, `Confidence`.
- `exceptions.py`    -- `MemoryNotFoundError`, `DuplicateMemoryError`,
                         `MemoryStoreError`.
- `store.py`         -- `MemoryStore` + `VectorStore` interfaces.
- `sqlite_store.py`  -- `SQLiteMemoryStore`, the structured persistence
                         layer.
- `config.py`        -- `MemoryConfig` (database/vector-store paths,
                         enable flag).
- `manager.py`       -- `MemoryManager`, store/get/update/delete/list.

Phase 6.2 (new):
- `semantics.py`         -- `SemanticTriple`/`EpisodicDetails`/
                             `FailureDetails`/`UserFact` + one
                             `build_*_memory` factory per `MemoryType`,
                             each deriving `Memory.content` and
                             `Memory.metadata` from the same structured
                             input.
- `representation.py`    -- `canonical_text(memory)`, the deterministic
                             embedding-input builder every embedder
                             call goes through.
- `embeddings.py`        -- `Embedder` interface, `HashingEmbedder`
                             (deterministic, offline default),
                             `EmbeddingConfig.from_env()`,
                             `get_embedder()`.
- `sqlite_vector_store.py` -- `SQLiteVectorStore`, the Phase 6.2
                             concrete `VectorStore` (SQLite + `numpy`
                             brute-force cosine search).
- `retrieval.py`         -- `RetrievalContext`, `RankingWeights`,
                             `MemoryResult`, `RetrievalEngine`
                             (indexing + hybrid retrieval + ranking),
                             `build_retrieval_engine()` (production
                             wiring).
- `conflicts.py`         -- `detect_relationship`/
                             `store_semantic_observation` -- basic,
                             structural duplicate/conflict tagging for
                             semantic and user memories; never deletes
                             or mutates existing evidence.

Consumers
---------
`backend/memory_evaluation/` (a deterministic retrieval-quality
dataset + Recall@K/Precision@K/MRR/latency measurement, mirroring
`backend/vision_evaluation/`'s role) is the first consumer of this
package's Phase 6.2 API. No other package in this repository imports
`backend/memory/` yet -- still by design (this phase's own scope
boundary: no planner integration, no Memory Agent, no execution/
reflection wiring, no API routes). A future Phase 6.3 Memory Agent /
Planner integration milestone is expected to call `RetrievalEngine.
retrieve()` and `semantics.build_*_memory()`/`conflicts.
store_semantic_observation()` directly, never `SQLiteMemoryStore`/
`SQLiteVectorStore` themselves.
"""
