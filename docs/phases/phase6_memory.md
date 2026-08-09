# Phase 6 -- Memory

## Phase 6.1 -- Memory Foundation

Status: complete (foundation only -- see "Scope" below).

## Goal

Build the robust, persistent, storage-agnostic foundation on which the
robot's long-term memory system will be built in later Phase 6
milestones (Semantic Memory, Episodic Memory, Failure Memory, User
Memory, Retrieval, the Memory Agent, Planner <-> Memory integration).
Phase 6.1 establishes the contracts, schemas, persistence, storage
abstractions, configuration, and tests those milestones will depend
on. It does **not** implement memory intelligence.

## Scope

Implemented in 6.1:

- A typed `Memory` domain model with closed-vocabulary `MemoryType`,
  `MemoryProvenance`, and `MemoryStatus` enums, and a bounded/validated
  `Confidence` type.
- A backend-agnostic `MemoryStore` interface plus a `SQLiteMemoryStore`
  implementation (the authoritative structured persistence layer).
- A `VectorStore` interface for a future embedding-based retrieval
  backend -- no concrete implementation ships yet.
- `MemoryManager`, the single application-facing entry point
  coordinating a `MemoryStore` and an optional `VectorStore`.
- Environment-driven configuration (`MemoryConfig`), matching this
  project's existing `LLMRuntimeConfig.from_env()` pattern.
- A test suite covering domain-model validation, SQLite CRUD/
  persistence/filtering, storage-abstraction substitutability, manager
  lifecycle, and failure cases.

Explicitly **not** implemented in 6.1 (deferred to later milestones):
planner <-> memory integration, Memory Agent reasoning, semantic
retrieval ranking, a RAG pipeline, memory summarization, reflection,
automatic consolidation, memory decay, sophisticated conflict
resolution, failure-recovery planning, user personalization logic, a
frontend memory dashboard, and automatic memory formation from every
observation. No API routes and no `api/app.py` wiring exist yet either
-- nothing outside `backend/memory/` imports it as of this milestone.

## Architecture map

```
Application (future Memory Agent, Planner integration, ...)
        |
        v
MemoryManager (backend/memory/manager.py)
        |
        +----------------> MemoryStore (backend/memory/store.py, interface)
        |                       |
        |                       v
        |                  SQLiteMemoryStore (backend/memory/sqlite_store.py)
        |                       |
        |                       v
        |                    SQLite (backend/outputs/memory/memory.db)
        |
        +----------------> VectorStore (backend/memory/store.py, interface)
                                |
                                v
                        Future vector DB (Phase 6.2 -- no
                        concrete implementation ships in 6.1)
```

`MemoryManager` and the domain layer (`Memory`) depend only on
`MemoryStore`/`VectorStore` -- abstract interfaces, never on `sqlite3`
or any embedding library. `sqlite_store.py` is the only module in
`backend/memory/` that imports `sqlite3`; nothing imports ChromaDB (it
is not a project dependency as of Phase 6.1 -- see "Vector-store
boundary" below). This mirrors `backend/execution/`'s boundary around
`simulator.simulator.Simulator`.

## Repository audit -- what was reused

Before writing any code, the existing backend architecture
(`backend/config/`, `backend/execution/`, `backend/planner/`,
`backend/schemas/`, `backend/language/config.py`,
`backend/evaluation/result_store.py`) was inspected for conventions
and reusable pieces. `backend/memory/` existed as an empty directory
(no prior memory code). Findings:

- **Domain modeling convention**: Pydantic `BaseModel` with
  `model_config = ConfigDict(extra="forbid", validate_assignment=True)`
  (`execution/models.py`, `planner/models.py`). `Memory` follows this
  exactly.
- **Enum convention**: `str, Enum` subclasses for every closed
  vocabulary (`schemas/enums.py`, `execution/models.ActionType`), so a
  member compares equal to and serializes as its plain string value.
  `MemoryType`/`MemoryProvenance`/`MemoryStatus` follow this.
- **Configuration convention**: frozen `@dataclass` with a
  `from_env()` classmethod reading `os.environ` directly, no `.env`
  parsing of its own (`language/config.py`'s `LLMRuntimeConfig`).
  `MemoryConfig` follows this exactly, including the `backend/.env`
  loading staying centralized in `api/app.py` (nothing new added
  there, since nothing yet constructs a `MemoryManager` at startup).
- **Episode/task association**: `execution.models.ExecutionRecord`
  already carries `execution_id`/`plan_id`/`task_id` and is explicitly
  documented (in that module's own docstring) as "exactly the shape a
  future Phase 6 Memory Agent is expected to persist." `Memory.
  episode_id`/`Memory.task_id` are designed to reference
  `ExecutionRecord.execution_id`/`task_id` directly, once a later
  milestone starts writing episodic memories from execution results.
- **Output directory convention**: `backend/outputs/` already exists
  (gitignored scratch space for generated runtime artifacts) --
  reused as `MemoryConfig`'s default database location
  (`backend/outputs/memory/memory.db`) rather than inventing a second
  "local data" directory.
- **No duplicate abstraction created**: there was no existing
  database/storage abstraction, vector-store interface, or
  memory-shaped domain model anywhere in the repository to reuse or
  collide with.

## Data model

```
Memory
  memory_id:    str   (UUID, generated by default)
  memory_type:  MemoryType   {semantic, episodic, failure, user}
  content:      str          -- primary, always-present payload
  provenance:   MemoryProvenance
                {observation, execution, user_input, inference,
                 reflection, system}
  status:       MemoryStatus {active, archived}
  confidence:   float, bounded [0.0, 1.0], validated at construction

  created_at:   float (Unix seconds) -- when the record was created
  observed_at:  float | None         -- when the underlying event
                                        happened, if applicable
  updated_at:   float (Unix seconds) -- last modification

  episode_id:   str | None  -- e.g. an ExecutionRecord.execution_id
  task_id:      str | None  -- e.g. a SingleTask.task_id

  metadata:     dict[str, Any]  -- open, type-specific auxiliary data
```

`content` is deliberately a string, not a dict -- the phase spec warns
against an unstructured `dict[str, Any]` as the *primary* domain
representation. Fields that genuinely need structure (a `FailureRecord`
error code, a semantic subject/predicate/object triple, ...) live in
`metadata` until a future milestone's usage pattern justifies promoting
one to a first-class field -- the same escalation path
`ConstraintType.CUSTOM` documents in `schemas/enums.py`.

## Storage

### Structured store (SQLite)

`SQLiteMemoryStore` (`backend/memory/sqlite_store.py`) is the Phase
6.1 authoritative persistence layer. Every field needed to reconstruct
a `Memory` exactly is a first-class, typed, indexed SQL column --
`metadata` is the only JSON-serialized blob, since it is genuinely
open-ended. Indexes exist on `memory_type`, `status`, `provenance`,
`episode_id`, `task_id`, and `created_at` -- every column `list()` can
filter or order by.

A fresh `sqlite3` connection is opened per operation (matching
`evaluation/result_store.py`'s "no state cached across calls"
simplicity) and always explicitly closed via `contextlib.closing`;
writes commit or roll back explicitly. Schema initialization
(`CREATE TABLE IF NOT EXISTS` + indexes) runs on every
`SQLiteMemoryStore(...)` construction, so opening the same database
file again (a new process, a restarted server) is safe and picks up
existing data unchanged.

### Vector-store boundary

`VectorStore` (`backend/memory/store.py`) defines the interface a
future embedding-based retrieval backend will implement
(`upsert`/`delete`/`search`). **No concrete implementation ships in
Phase 6.1.** ChromaDB is not currently a dependency of this project
(`backend/requirements.txt`), and the phase spec explicitly permits
deferring the concrete adapter to Phase 6.2 in exactly that situation
rather than adding a new, unused runtime dependency on speculation.
`MemoryManager` accepts an optional `VectorStore` collaborator so a
Phase 6.2 concrete adapter can be plugged in later without changing
`MemoryManager`'s own code.

## Configuration

`MemoryConfig` (`backend/memory/config.py`), read via `MemoryConfig.
from_env()`:

| Variable                    | Default                                | Meaning |
|------------------------------|-----------------------------------------|---------|
| `MEMORY_ENABLED`             | `true`                                  | Master enable/disable switch for a future caller (not read by `MemoryManager` itself). |
| `MEMORY_DATABASE_PATH`       | `backend/outputs/memory/memory.db`      | SQLite database file. |
| `MEMORY_VECTOR_STORE_PATH`   | `backend/outputs/memory/vector_store`   | Reserved for a future Phase 6.2 concrete `VectorStore` adapter. |

Documented (commented out, matching every other section's convention)
in `backend/.env.example`.

## How future Phase 6 milestones are expected to consume this layer

1. Construct `MemoryManager.from_config(MemoryConfig.from_env())` once
   (mirrors `LanguageAgent.from_config()` in `api/app.py`'s lifespan).
2. Call `manager.store(Memory(...))`/`manager.get(...)`/
   `manager.update(...)`/`manager.delete(...)`/`manager.list(...)` --
   never construct or import `SQLiteMemoryStore` directly outside this
   package.
3. A future Episodic Memory milestone builds `Memory(memory_type=
   MemoryType.EPISODIC, provenance=MemoryProvenance.EXECUTION,
   episode_id=execution_record.execution_id, task_id=
   execution_record.task_id, ...)` from an `execution.models.
   ExecutionRecord`.
4. A future Failure Memory milestone builds `Memory(memory_type=
   MemoryType.FAILURE, ...)` from an `execution.errors.ExecutionError`.
5. A future retrieval milestone adds ranking/scoring *on top of*
   `MemoryManager.list()`'s filter-only query surface -- it does not
   modify `MemoryStore`/`SQLiteMemoryStore`.
6. A future Phase 6.2 milestone implements a concrete `VectorStore`
   (e.g. backed by ChromaDB) and passes it into
   `MemoryManager(store=..., vector_store=concrete_vector_store)`.

## Tests

`backend/tests/test_memory_models.py`,
`test_memory_store.py`, `test_memory_sqlite_store.py`,
`test_memory_manager.py`, `test_memory_config.py` -- 59 tests covering:

- Domain model validation (valid construction, invalid `MemoryType`/
  `MemoryProvenance`, out-of-range `Confidence`, unknown-field
  rejection, timestamp defaults, metadata, serialization round-trips).
- Storage-abstraction substitutability (`MemoryStore`/`VectorStore`
  cannot be instantiated without implementing every abstract method;
  `MemoryManager` works identically against `SQLiteMemoryStore` and a
  dependency-free in-memory fake).
- SQLite CRUD, persistence across store re-open (simulating a process
  restart), multiple memory types, nested metadata, every `list()`
  filter individually and combined, and failure cases (duplicate id,
  missing memory on update/delete, corrupted on-disk records,
  transaction rollback leaving no partial row, database
  initialization failure).
- `MemoryManager` store -> retrieve -> update -> delete lifecycle,
  `updated_at` bookkeeping, persistence across manager recreation, and
  `MemoryConfig.from_env()`.

Run with:

```bash
cd backend && python -m pytest tests/test_memory_*.py -v
```

---

## Phase 6.2 -- Memory Intelligence

Status: complete (standalone retrieval subsystem -- see "Scope" below;
**not** integrated into the planner or any agent).

### Goal

Make the Phase 6.1 storage foundation capable of representing
meaningful semantic/episodic/failure/user memories, embedding and
indexing them, and retrieving the most relevant ones for a
natural-language query plus optional structured context -- returning
results with enough provenance/confidence/ranking metadata for a
future planner/Memory Agent to reason over, and explainable enough to
answer "why was this memory retrieved?" programmatically.

### Scope

Implemented in 6.2:

- Type-specific structure for all four `MemoryType`s
  (`backend/memory/semantics.py`): `SemanticTriple`/`UserFact`
  (subject/predicate/object), `EpisodicDetails`, `FailureDetails`, each
  with a `build_*_memory()` factory deriving both `Memory.content` and
  `Memory.metadata` from the same structured input.
- A deterministic, documented, embedding-input representation
  (`backend/memory/representation.py`) -- `canonical_text(memory)`.
- A configurable embedding pipeline (`backend/memory/embeddings.py`):
  `Embedder` interface, `HashingEmbedder` (deterministic, offline,
  dependency-free default), `EmbeddingConfig.from_env()`.
- A concrete `VectorStore` (`backend/memory/sqlite_vector_store.py`):
  SQLite + `numpy` brute-force cosine similarity search.
- A hybrid retrieval + ranking engine
  (`backend/memory/retrieval.py`): `RetrievalEngine.retrieve()`,
  `RetrievalContext` (structured filters/soft signals),
  `RankingWeights` (configurable scoring), `MemoryResult`
  (explainable, structured results).
- Basic, structural duplicate/conflict detection and tagging
  (`backend/memory/conflicts.py`) -- never destructive.
- A deterministic evaluation harness (`backend/memory_evaluation/`):
  a fixed dataset, Recall@K/Precision@K/MRR/latency metrics, and four
  ranking ablation configs.
- 166 new tests (see "Tests" below).

Explicitly **not** implemented in 6.2 (deferred to Phase 6.3+):
planner <-> memory integration, Memory Agent autonomous reasoning,
execution -> memory integration, reflection, automatic post-task
memory generation, navigation/AI2-THOR control, a frontend memory UI,
full personalization, autonomous task replanning, sophisticated
belief revision/knowledge-graph consolidation, and memory decay/
deletion. Nothing in this repository outside `backend/memory/` and
`backend/memory_evaluation/` imports either package as of this
milestone -- the retrieval engine is a complete, standalone subsystem
a future milestone integrates, not something already wired in.

### Repository audit for 6.2

Phase 6.1's `Memory.metadata` field was explicitly documented (in its
own docstring) as "the escalation path" for type-specific structured
fields before a first-class schema field is justified -- 6.2's four
memory types are built entirely on that escalation path
(`semantics.py`), requiring **zero changes** to `models.py`,
`store.py`, `sqlite_store.py`, `config.py`, or `manager.py`. No
Phase 6.1 design decision was found to be a blocker; no redesign was
performed. The only Phase 6.1 file consumed (not modified) in a new
way is `MemoryConfig.vector_store_path`, which Phase 6.1 reserved,
unused, "for a future Phase 6.2 concrete vector-store adapter" --
`retrieval.build_retrieval_engine()` is exactly that consumer.

### Architecture

```
Memory (semantics.build_*_memory)
   |
   v
canonical_text()  (representation.py)
   |
   v
Embedder.embed()  (embeddings.py -- HashingEmbedder, deterministic/offline)
   |
   v
VectorStore.upsert()  (sqlite_vector_store.py)

--------------------------------------------------------------

Query
   |
   v
Embedder.embed()
   |
   v
VectorStore.search()  --> candidate pool (top_k * pool_multiplier)
   |
   v
Structured/hard filter (memory_types, status, time window)
   |
   v
Ranker (similarity, confidence, recency, provenance, context)
   |
   v
MemoryResult[]  (sorted, explainable, top_k)
```

`RetrievalEngine` is the only module combining `MemoryManager`
(Phase 6.1, unmodified), `VectorStore`, and `Embedder` -- each of
those three remains swappable behind its own interface.
`memory_evaluation/` depends on `memory/` but not vice versa.

### Memory types

- **Semantic** (`SemanticTriple`): subject/predicate/object, e.g.
  `refrigerator located_in kitchen`. Not assumed permanently true --
  carries `confidence`/`provenance`/`observed_at`/`status` like every
  `Memory`.
- **Episodic** (`EpisodicDetails`): `task_summary`, `outcome`,
  `location`, `duration_seconds`, `relevant_objects`; linked via
  `Memory.episode_id`/`task_id` (no duplicate task/session model --
  these are expected to be `execution.models.ExecutionRecord.
  execution_id`/`task_id` once a future milestone wires that in).
- **Failure** (`FailureDetails`): `task`, `action`, `failure_reason`,
  `cause`, `context`, `recovery`, `outcome`, optional `error_code`.
- **User** (`UserFact`): same triple shape as semantic, `subject`
  defaults to `"user"`, provenance defaults to `USER_INPUT`.

Each factory derives `Memory.content` (the canonical embedding input)
and `Memory.metadata` (the structured fields, round-trippable back
into the typed model via `SemanticTriple.from_metadata()` etc.) from
the *same* structured input, so they cannot drift apart.

### Embedding architecture

`canonical_text(memory)` returns `memory.content` -- never a JSON dump
(see `representation.py`'s docstring for why label-scaffolded formats
like `"Subject: X | Predicate: Y"` were tried and rejected: the labels
are identical noise across every record and measurably hurt retrieval
precision for the deterministic hashing embedder; plain
`"{subject} {predicate} {object}"` and light `"Field: value | ..."`
labeling for the longer episodic/failure sentences were kept only
where empirically harmless).

`HashingEmbedder` (default and only Phase 6.2 provider) is a
deterministic, offline, dependency-free feature-hashing embedder:
word tokens + character trigrams, hashed via `blake2b` (not Python's
randomized `hash()`) to a signed index in a fixed-dimension vector,
L2-normalized. It captures lexical/substring similarity, not
synonym/semantic similarity -- a documented limitation (see
"Evaluation" below), not an oversight; `Embedder` is the seam a future
transformer-based provider plugs into with zero change to
`retrieval.py`.

### Retrieval architecture

`RetrievalEngine.retrieve(query, memory_types=None, context=None,
top_k=5, now=None)`:

1. Embed `query`.
2. `VectorStore.search()` over a candidate pool
   (`max(min_candidate_pool, top_k * candidate_pool_multiplier)`) --
   vector search runs first because `VectorStore.search()` has no
   filter parameter.
3. **Hard filters** (exclude entirely): `memory_types`, lifecycle/
   `status` (`ARCHIVED` excluded by default, per Phase 6.1's own
   documented intent), `time_start`/`time_end`.
4. **Soft context signal** (`context_relevance`, a ranking component,
   never a filter): `episode_id`, `task_id`, `metadata_filters` --
   deliberately soft so cross-episode/cross-task knowledge (semantic,
   user memory) stays retrievable when scoped context doesn't apply to
   it.
5. Score and sort (`(-final_score, -created_at, memory_id)` -- fully
   deterministic tie-breaking).

### Ranking formula

```
final_score = ( w_similarity * similarity
              + w_confidence * confidence
              + w_recency    * recency
              + w_provenance * provenance_score
              + w_context    * context_relevance ) / (sum of weights)
```

Default weights (`RankingWeights`, all configurable via
`MEMORY_RETRIEVAL_WEIGHT_*` env vars): `similarity=0.45`,
`confidence=0.20`, `recency=0.15`, `provenance=0.10`, `context=0.10`.
Rationale: similarity is the only signal that measures "does this
memory answer the query" at all, so it dominates; confidence is
weighted second-highest per the phase spec's explicit example (a
highly similar but untrustworthy memory should not automatically
outrank a less similar but reliable one); recency/provenance are
modest tie-breakers; context is smallest because it already narrows
the candidate pool via the hard filters above before scoring begins.

- `similarity`: raw cosine similarity, clipped to `[0, 1]`.
- `confidence`: `Memory.confidence`, used as-is.
- `recency`: `2 ** (-age / half_life_seconds)` (default half-life: 7
  days) -- influences rank only, never deletes or excludes old
  memories.
- `provenance`: a per-`MemoryProvenance` trust score (`OBSERVATION`/
  `USER_INPUT`=1.0, `EXECUTION`=0.9, `SYSTEM`=0.7, `INFERENCE`=0.6,
  `REFLECTION`=0.5) -- documented rationale in `retrieval.py`, fully
  overridable via a custom `RankingWeights(provenance_scores={...})`.
- `context`: fraction of specified `RetrievalContext` soft-signal
  checks the memory matches; `1.0` (neutral) when no context given.

Every `MemoryResult.ranking_components` dict carries all five raw
components plus the weights used, and `.explain()` renders them
human-readably -- retrieval is fully explainable without re-running
anything.

### Conflict handling

`conflicts.detect_relationship()` compares two `SEMANTIC`/`USER`
memories structurally (never a similarity heuristic): same
subject+predicate+object -> `"duplicate_of"`; same subject+predicate,
different object -> `"conflicts_with"`; anything else -> unrelated.
`store_semantic_observation()` tags the **new** memory's `metadata
["related_memories"]` with any detected relationships to existing
`ACTIVE` memories of the same type -- it never mutates, archives, or
deletes the prior memory. Both `red_mug located_on dining_table` and a
later `red_mug located_on kitchen_cabinet` remain independently
retrievable, each carrying its own confidence/provenance/timestamp, so
a future reasoning layer can decide which (if either) is currently
true. This is deliberately shallow (no knowledge-graph consolidation,
no automatic belief revision) per the phase spec's explicit scope
limit.

### Evaluation

`backend/memory_evaluation/` -- 9 memories (3 semantic, 2 episodic, 2
failure, 2 user), 6 natural-language queries, measured against four
ranking ablations (`ABLATION_CONFIGS`: vector-only ->
+confidence -> +recency -> full hybrid). Run with:

```bash
cd backend && python -m memory_evaluation.run_evaluation
```

Measured results (`HashingEmbedder`, dimension 512, this repository's
dev machine):

| Config | R@1 | R@3 | R@5 | P@1 | MRR | mean latency |
|---|---|---|---|---|---|---|
| A: vector-only | 0.58 | 0.92 | 1.00 | 0.83 | 0.89 | ~0.8 ms |
| B: + confidence | 0.58 | 0.92 | 1.00 | 0.83 | 0.89 | ~0.7 ms |
| C: + recency | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | ~0.9 ms |
| D: full hybrid | 0.67 | 1.00 | 1.00 | 0.83 | 0.92 | ~0.8 ms |

Recall@5 is perfect across every ablation on this dataset (small
enough that the candidate pool always contains every expected memory);
the ablations mainly differentiate on R@1/MRR, i.e. ranking quality,
not recall. Recency helped the most on this dataset (config C);
provenance/context add no further discriminative signal here because
none of the six queries carry a `RetrievalContext` and every dataset
memory's provenance is similarly trustworthy -- both still matter for
queries/deployments that do use them (see the ranking tests in
`test_memory_retrieval.py` for isolated, controlled cases proving each
component's individual effect). `HashingEmbedder`'s lexical-only
nature is the main source of imperfect R@1 (e.g. it cannot connect
"beverage"/"drink" to "tea" without shared word/trigram overlap) --
the honest baseline the phase spec's "first establish a correct
baseline, do not prematurely optimize" principle asks for, not a
tuned or cherry-picked result.

### Configuration

New in 6.2 (`backend/.env.example`, `backend/memory/embeddings.py` +
`retrieval.py`):

| Variable | Default | Meaning |
|---|---|---|
| `MEMORY_EMBEDDING_PROVIDER` | `hashing` | Only provider implemented. |
| `MEMORY_EMBEDDING_DIMENSION` | `512` | Vector length (tuned via `memory_evaluation`; see `embeddings.py`). |
| `MEMORY_EMBEDDING_MODEL_NAME` / `_DEVICE` | unset / `cpu` | Reserved for a future model-backed provider. |
| `MEMORY_RETRIEVAL_WEIGHT_{SIMILARITY,CONFIDENCE,RECENCY,PROVENANCE,CONTEXT}` | `0.45/0.20/0.15/0.10/0.10` | Ranking weights. |
| `MEMORY_RETRIEVAL_RECENCY_HALF_LIFE_SECONDS` | `604800` (7 days) | Recency decay half-life. |
| `MEMORY_RETRIEVAL_SIMILARITY_THRESHOLD` | `0.0` | Minimum raw similarity to consider a candidate. |
| `MEMORY_RETRIEVAL_CANDIDATE_POOL_MULTIPLIER` / `_MIN_CANDIDATE_POOL` | `5` / `20` | Candidate-pool sizing before filtering/ranking. |

### Tests

`test_memory_embeddings.py`, `test_memory_representation.py`,
`test_memory_semantics.py`, `test_memory_sqlite_vector_store.py`,
`test_memory_retrieval.py`, `test_memory_conflicts.py`,
`test_memory_evaluation.py` -- 166 new tests covering determinism,
dimensions, batching, embedding config/failure handling; canonical-
representation equivalence; per-type factory correctness; vector
store CRUD/search/persistence/failure cases; hybrid retrieval (type
filter, confidence/provenance/recency/context ranking in isolation,
archived exclusion, time windows, explainability, determinism,
persistence across restart, reindex/update/delete); conflict
detection/tagging; and evaluation metric correctness + dataset
consistency + ablation sanity checks.

Run with:

```bash
cd backend && python -m pytest tests/test_memory_*.py -v
```

### Limitations (remaining for Phase 6.3+)

No planner/Memory Agent integration, no execution -> memory
integration (nothing auto-forms memories from `ExecutionRecord`/
`ExecutionError` yet -- the factories exist, wiring them to Phase 5
output does not), no reflection, no autonomous replanning from
failure memories, no sophisticated belief revision/knowledge-graph
consolidation (conflicts are tagged, not resolved), no memory decay/
deletion, no frontend, and no learned/semantic embedding provider
(only the deterministic lexical `HashingEmbedder`).

---

## Phase 6.3 -- Memory <-> Robot Integration

Status: complete -- the closed causal loop (retrieve -> plan -> execute
-> remember -> retrieve again) is implemented, tested end to end
against `FakeSimulator`, and demonstrated to survive a simulated
process restart. **Not** wired into any FastAPI route or the frontend.

### Goal

Turn the standalone Phase 6.2 retrieval subsystem into a functional
part of the robot's decision loop, and prove -- not merely assert --
that past experience changes present planning, and present experience
becomes persistent future knowledge:

```
User -> Task -> MemoryAgent.retrieve -> Planner (memory-conditioned)
     -> ExecutionController -> AI2-THOR -> ExecutionRecord
     -> MemoryAgent.remember -> Persistent Memory -> (future Task)
```

### Repository audit -- what was reused

- **`schemas.task.SingleTask`** -- `MemoryQueryContext` is built from
  its existing `goal`/`object`/`target`/`task_id` fields; no duplicate
  task model.
- **`planner.models.Plan.metadata`** -- already documented in Phase 6.1
  as reserved for "a future memory-conditioned planner's retrieved
  context"; used as-is to attach a memory-query summary to every plan,
  no new `Plan` field.
- **`planner.state.WorldState`** -- `is_located` (already the
  mechanism `validator.PlanValidator` uses for ground truth) is the
  exact signal that lets current perception override stale memory,
  with zero new state.
- **`execution.models.ExecutionRecord`/`StepExecutionRecord`/
  `execution.errors.ExecutionError`** -- read directly (by
  `orchestration/task_runner.py`, never by `memory/`) to build
  `EpisodicDetails`/`FailureDetails`; no second execution-history
  system.
- **`execution.resolver.ObjectResolver`** -- reused as-is by
  `TaskRunner._form_observation()` to resolve a task's object name to
  a live `objectId` before reading its `parentReceptacle`.
- **`tests/_execution_test_helpers.FakeSimulator`** -- reused for every
  new test in this phase (zero AI2-THOR dependency, matching every
  existing Phase 5 test).

No Phase 6.1/6.2 file was redesigned. Two small, additive corrections
were made where Phase 6.2 had no concrete caller yet to reveal the
gap: `RetrievalEngine.manager` (a read-only property, so `MemoryAgent`
can run `conflicts.store_semantic_observation()` without reaching past
it into a private attribute) and a bug fix in `MemoryAgent.
remember_episode()` (the object it returned did not reflect a
`recovered_from` tag `link_recovery()` had just written to storage --
fixed by mutating the returned object to match).

### Architecture

```
Planner / TaskRunner
        |
        v
  MemoryAgent (memory/agent.py)
        |
        v
  RetrievalEngine (Phase 6.2)
        |
  MemoryManager (Phase 6.1) + Embedder + VectorStore
```

```
backend/orchestration/task_runner.py  (the only module depending on
                                        BOTH execution/ and memory/)
        |
        +--> Planner.plan(task, state, memory_context)
        +--> ExecutionController.execute_plan(...)
        +--> MemoryAgent.remember_episode/remember_failure/
             remember_observation/link_recovery
```

`backend/planner/` still never imports `sqlite3`/`memory.retrieval`/
`memory.manager` -- only the one opaque `memory.agent.
PlannerMemoryContext` type. `backend/execution/` is completely
untouched (still never writes to a database itself, per its own
docstring). `backend/memory/` still knows nothing about `Plan`/
`ExecutionRecord`. `backend/orchestration/` is the one new package
that legitimately depends on all three -- see each module's own
docstring for the full rationale.

### Memory Agent API

```python
MemoryAgent.from_config(memory_config, embedding_config=None, weights=None) -> MemoryAgent
agent.is_available() -> bool
agent.retrieve_relevant_memories(context: MemoryQueryContext, *, memory_types=None, top_k=5, now=None) -> PlannerMemoryContext
agent.remember_episode(details: EpisodicDetails, *, episode_id, task_id=None, provenance=EXECUTION, confidence=1.0, recovered_failure_ids=None) -> Optional[Memory]
agent.remember_failure(details: FailureDetails, *, episode_id, task_id=None, provenance=EXECUTION, confidence=1.0) -> Optional[Memory]
agent.remember_observation(subject, predicate, object_, *, provenance, confidence=1.0, episode_id=None, task_id=None) -> Optional[Memory]
agent.link_recovery(episode_memory_id, failure_memory_ids) -> None
```

Every method above either returns a value or `None`/an empty
`PlannerMemoryContext` -- **none of them raise** for an ordinary memory
failure (empty database, retrieval exception, corrupted record,
unavailable backend). `MemoryAgent.from_config()` applies the same
policy to construction itself.

### Planner integration -- exactly how memory reaches the planner

`Planner.plan(task, state, memory_context=None)` -- a new, optional,
default-`None` third parameter on the existing method (every one of
the 18 pre-6.3 call sites in this repository's own test suite, plus
`api/routes/planner.py`, is unaffected). `RuleBasedPlanner` is the one
strategy that reasons over it as of 6.3: when a goal needs to locate
an object it has no explicit location for, and `state.object(obj).
is_located` is not already `True` (current perception, once wired to
Vision, wins), it looks for the highest-ranked `SEMANTIC`/`USER`
memory whose triple's `subject` matches the object and whose
`predicate` is in a small, generic "names a location" whitelist
(`located_on`, `located_in`, `typically_stored_in`, `stored_in`,
`observed_on`, `observed_in`) and whose `confidence >= 0.4`. If found,
it inserts a `locate`+`navigate` pair for that location *before* the
object's own `locate`/`navigate` steps, tagged `parameters={"source":
"memory", "memory_id": ..., "confidence": ...}`. The plan still always
ends by locating/navigating to the object itself -- memory reorders
search, it never replaces the final action, and an explicit
`task.target`/`task.target_location` (a user-specified deposit
destination) is never touched by this mechanism. `BehaviorTreePlanner`/
`ReActPlanner` accept and forward `memory_context` for interface
consistency but do not yet reason over it themselves (documented as a
Phase 6.4+ limitation in each module).

Every plan built with a `memory_context` carries `Plan.
metadata["memory_context"] = {"query": ..., "count": ..., "memory_ids":
[...]}` -- explainable without re-running retrieval.

### Execution integration

`orchestration.task_runner.TaskRunner.run(task)`:

1. `MemoryAgent.retrieve_relevant_memories()` (skipped if memory
   disabled/unavailable).
2. `Planner.plan(task, state, memory_context)`.
3. If planning failed: one `FAILURE` memory (`cause=None`, nothing to
   attribute a cause to yet) -- no `ExecutionRecord` is ever built.
4. Otherwise `ExecutionController.execute_plan()`.
5. `ExecutionStatus.SUCCESS` -> one `EPISODIC` memory, always; a prior
   unresolved `FAILURE` memory for the same task is linked via
   `link_recovery()` if found; **at most one** `SEMANTIC` observation
   is formed (see below).
6. Any other status -> one `FAILURE` memory built only from the first
   `FAILED` step's actual `ExecutionError` -- `cause=None` whenever no
   step recorded one. **Never** invented by an LLM or otherwise.

### Semantic memory policy -- exactly what becomes persistent

`TaskRunner._form_observation()` is the only path from a live
observation to a `SEMANTIC` memory, and it fires only when **all**
of: the task named a primary object; the task just completed
`SUCCESS`; that object resolves (via the existing `ObjectResolver`) to
a live simulator object; and that object's real AI2-THOR
`parentReceptacle` metadata names another live object. At most one
observation per successful run, for the task's primary object only --
never a scene dump, never per-frame, never per-detection. Everything
else in the final scene is untouched.

### Golden memory test (`tests/test_orchestration_task_runner.py::
TestGoldenMemoryTest`)

- **Run 1** -- "find mug" (empty memory) succeeds; creates one episodic
  memory and one semantic observation (`mug located_on table`, from
  `parentReceptacle` ground truth).
- **Restart** -- a brand-new `MemoryAgent`/`RetrievalEngine`/
  `SQLiteMemoryStore`/`SQLiteVectorStore` are constructed against the
  same on-disk paths.
- **Run 2** -- "find mug" again: `memory_context` is non-empty, and the
  resulting plan's *first* step now targets `"table"` (`targets[0] ==
  "table"`) -- a measurable, asserted difference from Run 1's plan
  (which targeted `"mug"` first). Task succeeds.
- **Run 3** -- "find fridge" with a controlled obstacle
  (`FakeSimulator(fail_actions={"navigate"})`, deterministic, no real
  AI2-THOR): execution fails; one failure memory is created with a real
  cause (`"object not reachable"`, from the simulator's own error).
- **Restart again, obstacle removed** -- **Run 4** retries the *same*
  `task_id`: succeeds; the new episodic memory's `metadata
  ["recovered_from"]` names Run 3's failure memory id, and that failure
  memory's `metadata["recovered_by"]` names the new episode -- both
  directions verified against a freshly re-fetched record, not the
  in-process object.

This is causal, not cosmetic: the assertions check plan *content*
(`targets[0]`), not merely that a log line was emitted.

### Failure handling verified

Empty database, retrieval raising an exception (monkeypatched), a
corrupted on-disk metadata row (`UPDATE memories SET metadata =
'not valid json'`), and an entirely unconstructible memory subsystem
(`SQLiteMemoryStore` pointed at an unwritable path) are all covered in
`tests/test_orchestration_task_runner.py::TestMemoryOptionalAndSafe` --
every case still completes the task normally, with a warning logged
(`memory_agent.*` structured log events), never a crash.

### Metrics (measured on this repository's dev machine, `FakeSimulator`, `RuleBasedPlanner`)

| Stage | Run 1 (empty memory) | Run 2 (memory retrieved) | No `MemoryAgent` |
|---|---|---|---|
| `memory_retrieval_ms` | 0.36 | 0.49 | n/a |
| `planning_ms` | 0.31 | 0.11 | 0.07 |
| `execution_ms` | 0.18 | 0.18 | 0.09 |
| `memory_write_ms` | 1.37 | 1.54 | n/a |

A correct, unoptimized baseline against an in-memory `HashingEmbedder`
and local SQLite -- not yet measured against real AI2-THOR (where
`execution_ms` would dominate by orders of magnitude) or a
learned-embedding provider.

### Observability

`memory_agent.retrieved` (`task_id`, `episode_id`, `memory_query`,
`number_of_memories_retrieved`, `memory_ids`, `retrieval_latency_ms`),
`memory_agent.memory_created` (`memory_type`, `memory_id`,
`episode_id`, `task_id`), `memory_agent.write_failed`/
`retrieval_failed`/`unavailable` (warning + `exc_info`),
`planner.plan.start` (now includes `memory_context_count`). No raw
`Memory.content`/`metadata` payloads are logged.

### Limitations (remaining for Phase 6.4+)

No FastAPI route exposure (by design -- internal integration only). No
Reflection module. `BehaviorTreePlanner`/`ReActPlanner` do not yet
reason over retrieved memory (only accept/forward it). No learned
embedding provider. No sophisticated belief revision beyond structural
duplicate/conflict tagging (unchanged from 6.2). No Vision integration
(`WorldState` is always `WorldState.initial()` in `TaskRunner` today --
the "current perception overrides stale memory" mechanism is real and
tested, but nothing yet populates `WorldState` from a live Vision scene
graph). No multi-agent memory sharing. Not validated against real
AI2-THOR (`FakeSimulator` only, matching every other Phase 5 test in
this repository).

---

## Phase 6.4 -- Evaluation, Hardening & Research Validation

Status: **complete** (as a research evaluation -- see verdict below;
this milestone does not itself change runtime behavior, only measures
it). Full report:
[`experiments/reports/phase6_4_report.md`](../../experiments/reports/phase6_4_report.md).
Raw, machine-readable results:
[`experiments/results/`](../../experiments/results/).

### Goal

Determine, with reproducible evidence, whether the memory system built
in 6.1-6.3 actually improves the robot's ability to perform tasks --
not assert it from architecture diagrams or logs. Central question:
does enabling persistent memory improve task performance, efficiency,
and failure recovery compared with an otherwise identical
memory-disabled agent?

### Repository audit -- what was reused, what was found

`orchestration.task_runner.TaskRunner.run(task, memory_enabled: bool)`
already *is* the clean MEMORY_ON/MEMORY_OFF experimental interface the
phase spec's section 2 asks for -- Phase 6.4 built a benchmark and
runner around it, not a new switch. Active planner: `RuleBasedPlanner`
(the only planner that reasons over `memory_context`, per 6.3's own
limitation). Simulator: `FakeSimulator`, matching every existing Phase
5/6 test -- no real AI2-THOR run was attempted. `memory_evaluation/`
already contained Phase 6.2's retrieval-only evaluation harness
(`dataset.py`, `metrics.py`, `ablation.py`, `run_evaluation.py`) --
reused unmodified, not rebuilt.

### What was built

- `backend/memory_evaluation/scenarios.py` -- five version-controlled
  `BenchmarkScenario`s, one per phase-spec category (A: object
  location recall, B: episodic experience, C: failure recovery, D:
  stale memory -- soft + hard cases, E: conflicting memory), each a
  sequence of `EpisodeSpec`s (task + `FakeSimulator` scene + optional
  controlled failure).
- `backend/memory_evaluation/experiment.py` -- `run_scenario()` drives
  one scenario's episodes through `TaskRunner` under one condition,
  collecting `EpisodeResult` (success, action count, plan targets,
  every latency stage, memory-influence signal, recovery linkage) --
  the metrics section 7/8/9 of the phase spec require.
- `backend/memory_evaluation/memory_size.py` -- distractor-memory
  generation (explicitly tagged `metadata["synthetic"]=True`, built
  through the same `semantics.build_semantic_memory` factory
  production code uses) at 10/100/1000 scale, measuring retrieval
  latency/quality and task success as the store grows.
- `backend/memory_evaluation/pollution.py` -- counts semantic memories
  actually persisted against successful, object-naming episodes across
  the whole suite, verifying growth stays controlled.
- `backend/memory_evaluation/task_ablation.py` -- runs the Phase 6.2
  `ABLATION_CONFIGS` (vector-only -> +confidence -> +recency -> full
  hybrid) at the *task* level, against both a control scenario
  (Category A, one candidate memory) and a genuinely competing-memories
  scenario (Category E).
- `backend/memory_evaluation/run_benchmark.py` -- the CLI:
  `cd backend && python -m memory_evaluation.run_benchmark`. Runs
  every sub-experiment above, writes one timestamped JSON (raw
  per-episode results + reproducibility metadata) and one CSV per run
  to `experiments/results/`, prints a human-readable summary.
- `backend/tests/test_memory_evaluation_benchmark.py` -- 18 new
  regression tests, including two that lock in this milestone's
  negative findings (`test_hard_stale_causes_task_failure_under_
  memory_on`, `test_memory_on_uses_more_actions_than_memory_off_here`)
  so a future change to `RuleBasedPlanner`/`TaskRunner` that silently
  alters this behavior fails CI rather than going unnoticed.

### Headline findings (measured, not assumed -- full detail in the report)

- On this benchmark, `RuleBasedPlanner`'s memory integration **adds** a
  preliminary locate+navigate step ahead of an object's own direct
  grounding step, rather than replacing it -- so memory *increases*
  action count on every scenario where it fires, never decreases it.
- **Stale memory can cause outright task failure.** When a
  memory-hinted location no longer exists in the scene, the inserted
  step cannot resolve, blocking the whole plan -- even though the
  target object itself was perfectly reachable. This happens because
  `TaskRunner` always constructs an empty `WorldState.initial()`;
  Vision is not wired into it, so `RuleBasedPlanner`'s "current
  perception overrides stale memory" branch never fires end-to-end,
  despite being real, unit-tested code.
- The task-level ablation shows *why* this matters for ranking
  configuration specifically: with similarity as the only ranking
  signal, two conflicting memories score identically and the choice
  falls to an uninformative tie-break, which selected the stale,
  lower-confidence memory in this run. Every config with confidence
  weighting selected the correct one instead.
- Net result over the full benchmark: memory_on vs memory_off, success
  rate **90.0% -> 80.0%** (-10pp), mean actions **2.10 -> 3.10**.
- Memory growth stayed controlled (not per-frame); persistence across
  restart, already proven in 6.3, was reused, not re-demonstrated.

### Reproducibility

Fully deterministic (`RuleBasedPlanner` + `FakeSimulator`, no LLM, no
randomness) -- repeated runs are byte-identical, which the report
states explicitly is a *descriptive*, not inferential, comparison (no
p-values or confidence intervals are computed or implied anywhere in
this milestone's output). `git_commit` is recorded as `None` when run
outside a git repository, never fabricated.

### Verdict

```
COMPLETE
```

as an evaluation: every item in the Phase 6.4 acceptance checklist was
built and exercised with real, un-cherry-picked evidence, 756/756
tests pass (18 new, 0 regressions), and all quality gates
(black/ruff/mypy) are green. The memory *system's* own answer to "does
it help," measured honestly, is a qualified **no** for the current
`RuleBasedPlanner`/`TaskRunner` integration -- reported as such, with
the causal mechanism identified and locked into regression tests, per
this phase's explicit "a negative result is acceptable; invalid
evidence is not" principle. See the full report for the complete
breakdown, limitations, and what remains unproven (real-AI2THOR
behavior, LLM/ReAct/Behavior-Tree planners, and genuinely large
organically-accumulated memory stores were all out of scope here).
