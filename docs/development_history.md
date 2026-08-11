# Development History (Phase-by-Phase Narrative)

> Moved here from the README's old "Current Progress" section
> during the Phase 8.7 README restructure (2026-08-11) — a detailed,
> phase-by-phase account of how MILO was built (Phases 2 through 7).
> For current system status, see
> [`docs/phases/phase8_7_final_audit.md`](phases/phase8_7_final_audit.md).

The perception stack is complete end to end: given a simulator frame
and a text prompt, `VisionAgent` returns a `Scene` populated with
detections (Grounding DINO), pixel masks (SAM2), and spatial
relationships between detected objects (heuristic scene graph --
`LEFT_OF`, `INSIDE`, `OVERLAPS`, ...), routed through a
`PerceptionPipeline` that also has reserved (currently unconfigured)
slots for depth and tracking stages. The result can be rendered to an
annotated image via `SceneVisualizer`.

Phase 3.1-3.3 define and implement the Language Interface -- the data
contract between Language Understanding and every downstream module
(Planner, Execution, Memory, Reflection), plus the complete supporting
asset package for the parser that will produce it. The schema
(`backend/schemas/task.py`, `enums.py`, `metadata.py`, `validators.py`)
enforces its own invariants at validation time -- UUID-based task
identity, closed enum vocabularies, clarification-consistency and
subtask-count checks, and strict rejection of unrecognized fields --
verified by a 70-case unit test suite (`backend/tests/test_task.py`).
Phase 3.3 built the parser prompt itself (`backend/prompts/`, versioned
and configured independently of the schema) and a disjoint,
schema-verified dataset tree (`datasets/language/`) of 21 few-shot
examples, 10 anti-pattern examples, 14 edge cases, and three
evaluation benchmarks (correctness, robustness, ambiguity-detection)
designed to compare GPT, Qwen, Llama, and Phi fairly.

Phase 3.4 (`backend/language/`) builds the runtime that actually calls
an LLM: `LanguageAgent` orchestrates `PromptBuilder` (loads
`backend/prompts/`), a provider-independent `LLMClient`,
`ResponseParser` (raw text -> `dict`), and `SchemaValidator` (`dict` ->
validated `ParsedInstruction`) -- each independently testable, each
raising a shared exception vocabulary (`language.exceptions`) instead
of leaking a library-specific error.

Phase 3.5 (`backend/language/{failures,semantic_validator,repair,
recovery,gemini_client,provider_factory}.py`) hardens that runtime
against real-world LLM failures without changing `LanguageAgent`'s
public contract: a closed `FailureCategory` taxonomy, a bounded
per-category retry policy (`RecoveryEngine`), conservative syntactic
response repair (`SafeResponseRepairer` -- never rewrites field
content, only strips wrapper text), a lightweight semantic-plausibility
layer (`SemanticValidator`), and a second `LLMClient` implementation,
`GeminiLLMClient`, alongside the existing `OpenAICompatibleLLMClient` --
both selected purely through `LANGUAGE_LLM_PROVIDER` configuration
(`provider_factory.create_llm_client()`), never a code change. A
`LanguageAgent` built the exact way Phase 3.4's tests already build it
behaves identically to before; retries, repair, and semantic validation
are opt-in collaborators that `LanguageAgent.from_config()` enables by
default for production use. Verified by 209 unit + integration test
cases (`backend/tests/test_language_*.py`), every one running with the
LLM mocked -- no network access or API key required; an explicitly
opt-in real-API smoke test suite (`test_language_llm_smoke.py`) is
skipped unless `RUN_LLM_SMOKE_TESTS=true` and a credential is present.
See `backend/docs/language_interface_spec.md` section 27 for the full
Phase 3.4 runtime design and section 28 for the Phase 3.5 recovery
design.

Phase 3.6 (`backend/evaluation/`) is a separate evaluation framework
that treats `LanguageAgent` as the system under test: it never modifies
`backend/language/*`. `BenchmarkRunner` drives the Phase 3.3 benchmark
datasets (`datasets/language/evaluation/`) through a fresh
`LanguageAgent` per case (case isolation), `ResultEvaluator` scores
each result field-by-field against a dataset-aware notion of "correct"
(a `failure_cases` case that is correctly rejected is a success, not a
defect), and `MetricsCalculator` aggregates the results into defined,
versioned metrics -- task/goal/object/attribute/location/constraint/
multi-task/clarification accuracy, structural validity, recovery rate,
retry statistics, latency percentiles, and a failure-category
breakdown, reported per dataset category and as a micro/macro overall
rollup. `ProviderComparisonRunner`/`PromptVersionComparisonRunner` run
the identical benchmark against multiple providers or prompt versions
holding everything else constant, and `RecoveryEvaluator` analyzes
Phase 3.5's recovery system independently, broken down by
`FailureCategory`. Every run is persisted to
`results/language/benchmark_runs/<run_id>/`, versioned and never
overwritten. Normal tests never call a real LLM; real-provider
execution requires `RUN_LLM_BENCHMARK=true` explicitly, via
`run_benchmark.py`. See `backend/docs/language_interface_spec.md`
section 29 for the full design, including every metric's exact
definition.

Phase 3.7 (`backend/api/`, `frontend/`) exposes that completed
Language Understanding pipeline over HTTP: a FastAPI service
(`POST /api/v1/language/parse`) that calls the exact same
`LanguageAgent` -- no prompt construction, LLM call, parsing, or
validation logic is duplicated in the API layer -- and maps every
`LanguageRuntimeError` to a safe, credential-free HTTP response (never
a stack trace or raw provider error body). A `needs_clarification`
result is a normal `200` response, not an error, matching section 12's
"Ambiguity Handling" contract. A small React/TypeScript frontend
(`frontend/`) submits an instruction, shows a loading state, and
renders the structured result -- goal, object, attributes, locations,
constraints -- for both `SingleTask` and `MultiTask` responses, plus a
dedicated clarification banner and safe error states. The frontend
never receives an LLM API key; it only ever calls the backend over a
relative URL. See `backend/docs/language_interface_spec.md` section 30
for the complete design, including the error-mapping table and the
explicit production limitations (no auth/rate limiting yet).

Phase 3.x (`backend/vision/{depth,spatial,tracking,temporal}/`,
`backend/vision_evaluation/`, `backend/api/routes/vision.py`,
`frontend/src/components/Vision*.tsx`) extends that completed Phase 2
pipeline with spatial and temporal understanding, filling in fields the
Phase 2 freeze already reserved rather than changing any of them (see
[`docs/architecture/api_contracts.md`](architecture/api_contracts.md)'s
Phase 3.x note). `GroundTruthDepthEstimator` (AI2-THOR, metric meters)
and `DepthAnythingEstimator` (learned, relative) both implement
`BaseDepthEstimator`, filling `Detection.depth` with a robust
mask/bbox-median (never a single bbox-center pixel) and, via
`vision/spatial/localization.py`'s pinhole projection,
`Detection.position_3d` in camera-space meters. `IoUTracker` assigns
and maintains persistent `Detection.tracking_id`s across frames
(IoU + optional 3D-proximity matching, Hungarian assignment), with an
explicit `Track` lifecycle (`NEW -> TRACKED -> TEMPORARILY_LOST ->
REACQUIRED`/`LOST`) that tolerates brief occlusion without inventing a
new identity, while documenting that re-identification after a track
is declared `LOST` is out of scope without appearance features.
`TemporalScene` (deliberately outside the frozen pipeline, since
`Scene` is single-frame) diffs consecutive scenes into
new/removed/moved/occluded/reappeared events. `HeuristicSceneGraph`
gained an additive, depth-aware `NEAR` relationship, byte-for-byte
backward compatible when no depth stage is configured. All of this is
wired together by `vision/factory.py::build_vision_system()` and
exposed over HTTP via `POST /api/v1/vision/perceive`
(`backend/api/routes/vision.py`), which renders annotated camera/depth
images **server-side** so the frontend never touches a model or the
simulator directly, and returns a clean `503` when no simulator
connection exists (`VISION_ENABLE_SIMULATOR`, opt-in, off by default --
launching AI2-THOR can block indefinitely with no display available, so
this is never attempted automatically in CI). A dedicated,
synthetic-data perception benchmark (`backend/vision_evaluation/`,
distinct from the Phase 3.6 language benchmark) measures depth accuracy
(MAE/RMSE/relative error/threshold accuracy, with scale alignment for
relative depth) and tracking quality (ID switches, fragmentation,
recall, tracking success rate) by running the real project code against
deterministic synthetic cases. The frontend (`frontend/src/components/
Vision*.tsx`) gained a Vision panel -- annotated camera view, depth
colormap with an explicit legend, perception status, scene-change feed,
and an object inspector table -- alongside the unchanged Phase 3.7
Language panel; neither panel's result is combined with the other's.
See [`docs/architecture/spatial_perception.md`](architecture/spatial_perception.md)
for the complete design, including coordinate conventions, depth units,
and every documented limitation.

Phase 4 (`backend/planner/`, `backend/api/routes/planner.py`,
`frontend/src/components/Planner*.tsx`) completes the "Plan" stage of
this project's core research question: a validated Phase 3 `SingleTask`
goes in, an ordered sequence of abstract, simulator-independent
`PlanStep`s comes out, checked against a symbolic `WorldState` that
never touches AI2-THOR. Three interchangeable strategies implement the
same `Planner.plan(task, state) -> PlanningResult` interface -- a
deterministic `RuleBasedPlanner` (the baseline every other strategy is
compared against or falls back to), an LLM-driven `ReActPlanner` that
proposes one structured, precondition-checked action per iteration and
reuses the existing Phase 3.4 `LLMClient` abstraction rather than a new
one, and a `BehaviorTreePlanner` that expands the same goal templates
into `Sequence`/`Selector`/`Condition`/`Action`/`Retry` nodes for
Phase 5's future reactive failure handling. A dedicated
`PlanValidator` replays every step against a cloned `WorldState`,
catching out-of-order actions (place before pickup, close before open)
and unmet preconditions as structured, machine-readable issues, and
confirming the final state actually satisfies the task's goal. A
`PlannerEvaluator` runs every strategy against the same task and
reports real, measured success/validity/latency/step-count metrics --
never fabricated. All three strategies, validation, and cross-strategy
comparison are exposed over HTTP (`POST /api/v1/planner/{plan,validate,
evaluate}`) and visualized live in the frontend's Planner panel,
rendered directly beneath a parsed task in the existing Language
result view. See [Task Planning (Phase 4, complete)](#task-planning-phase-4-complete)
above for the complete design.

Phase 5 (`backend/execution/`, `backend/api/routes/execution.py`,
`frontend/src/components/Execution*.tsx`) closes the "Execute" stage:
a validated Phase 4 `Plan` is driven through AI2-THOR step by step by
`ExecutionController`, with every action's preconditions checked
against the same symbolic `WorldState`/`ActionSpec` registry the
Planner already validated against, every simulator result checked
against ground truth rather than trusted blindly, bounded retries and
timeouts, cooperative cancellation, and a structured, replayable
`ExecutionRecord` (per-step results + a timestamped event log) exposed
over HTTP and visualized live in the frontend. See
[Execution (Phase 5, complete)](#execution-phase-5-complete) above and
[`docs/phases/phase5_execution.md`](phases/phase5_execution.md)
for the complete design.

Phase 6.1 (`backend/memory/`) laid the storage foundation Phase 6.2
builds on: a typed `Memory` domain model (closed `MemoryType`/
`MemoryProvenance`/`MemoryStatus` vocabularies, a bounded/validated
`Confidence`), a backend-agnostic `MemoryStore` interface backed by
`SQLiteMemoryStore` (indexed, transactional, survives process
restarts), and `MemoryManager` as the one application-facing entry
point. Phase 6.2 (`backend/memory/semantics.py`, `embeddings.py`,
`sqlite_vector_store.py`, `retrieval.py`, `conflicts.py`) turns that
foundation into a real, standalone retrieval subsystem: type-specific
structure for semantic/episodic/failure/user memories, a deterministic
offline `HashingEmbedder`, `SQLiteVectorStore` (the Phase 6.1
`VectorStore` interface's first concrete implementation -- `sqlite3` +
`numpy` brute-force cosine search, no ChromaDB dependency added), and
`RetrievalEngine.retrieve()`: hybrid vector + structured-filter
retrieval, configurable similarity/confidence/recency/provenance/
context ranking, and explainable `MemoryResult`s. `backend/
memory_evaluation/` measures Recall@K/Precision@K/MRR/latency against
a fixed dataset across four ranking ablations (vector-only through
full hybrid).

Phase 6.3 (`backend/memory/agent.py`, `backend/orchestration/
task_runner.py`) closes the loop: `MemoryAgent` is the application-
facing boundary Planner/Execution now depend on (never `MemoryManager`/
`RetrievalEngine`/SQLite directly), `Planner.plan()` gained an optional
`memory_context` parameter every pre-6.3 call site is unaffected by,
and `RuleBasedPlanner` actually reasons over it -- inserting a
memory-suggested `locate`/`navigate` pair before an object's own
search steps when current perception (`WorldState.is_located`) doesn't
already know where it is, never replacing the object's own final
`locate`/`navigate`, never overriding an explicit user-given
destination. `TaskRunner.run()` is the full retrieve -> plan -> execute
-> remember loop: a successful `ExecutionRecord` becomes one episodic
memory (plus, when AI2-THOR's own `parentReceptacle` ground truth
supports it, exactly one semantic observation); a failed one becomes
one failure memory built only from the actual `ExecutionError` (never
a fabricated cause); a later successful retry of the same task links
back to the earlier failure via `MemoryAgent.link_recovery()`. A
deterministic four-run "golden memory test"
(`tests/test_orchestration_task_runner.py::TestGoldenMemoryTest`)
proves the loop causally, against `FakeSimulator`, across a simulated
process restart: a plan generated after a restart measurably changes
(its first step targets the remembered location) compared to the same
task planned with no prior memory. Memory failures (empty database, a
retrieval exception, a corrupted record, an unconstructible backend)
all degrade to normal planning, never a crash. Still no FastAPI
exposure, no Reflection module, and `ReActPlanner`/`BehaviorTreePlanner`
accept but do not yet reason over retrieved memory -- by design; see
[`docs/phases/phase6_memory.md`](phases/phase6_memory.md) for the
full design, the golden test walkthrough, measured latencies, and
explicit scope boundary, and [Future Phases](#future-phases) below for
what's still ahead. (The speech interface mentioned here as future work
was subsequently built in Phase 7 -- see below.)

Phase 6.4 (`backend/memory_evaluation/{scenarios,experiment,
memory_size,pollution,task_ablation,run_benchmark}.py`) answers, with
controlled experiments rather than architecture diagrams, whether
persistent memory actually helps: a five-category, version-controlled
benchmark suite (object recall, episodic experience, failure recovery,
stale memory, conflicting memory) run through `TaskRunner`'s existing
`memory_enabled` on/off switch -- both conditions run the identical
task/scene/planner/simulator otherwise. **Demonstrated, not
implemented-but-unverified:** on this benchmark, memory reduced task
success 90% -> 80% and increased mean actions 2.10 -> 3.10, because
`RuleBasedPlanner`'s memory hint adds a step rather than replacing one,
and because `TaskRunner` never populates `WorldState` from live
perception -- so the "current perception overrides stale memory"
safeguard (real, unit-tested code) does not fire end-to-end, letting a
stale memory-hinted location that no longer exists in the scene block
the whole plan. The task-level ranking ablation shows confidence
weighting is the specific mechanism that keeps a conflicting-memory
scenario from resolving to the wrong fact by an uninformative
similarity tie. Full methodology, every metric the phase spec
requires, and the complete honest verdict:
[`docs/phases/phase6_memory.md`](phases/phase6_memory.md)'s
Phase 6.4 section and
[`experiments/reports/phase6_4_report.md`](../experiments/reports/phase6_4_report.md).
This milestone is a research evaluation -- it measured the existing
system, it did not change planner/execution runtime behavior.

**Phase 7 -- Agent Architecture, Speech, and the MILO Frontend.**
Session 2 replaced the Phase 6 `TaskRunner` with a full multi-agent
`Orchestrator` (`backend/orchestration/orchestrator.py`,
`backend/agents/`): Vision/Memory/Planner/Navigation/Execution/Reflection
agents behind one `AgentRegistry`, a structured failure taxonomy, dynamic
replanning, a task-scoped event system, and a Whisper-backed
`SpeechAgent`, all exposed over `POST/GET /api/v1/tasks`, `GET
/api/v1/agents`, and `POST /api/v1/speech/transcribe`. Session 3 built the
functional frontend on top of that API: a seven-page **MILO** (Memory
Integrated Language Oriented Robot) application -- Home, Mission Control,
Memory, Activity, About MILO, MILO Lab, Settings -- with real task
creation (text and speech), live polling of task/agent/event state, and
memory/activity/metrics views assembled from real per-task data (no
fabricated numbers). The only backend addition this required was one
additive endpoint, `GET /api/v1/tasks` (list), since none of the Phase 7
API existed to enumerate past tasks. See
[`frontend/README.md`](../frontend/README.md) for the frontend's
architecture and
[`docs/testing/manual_e2e_checklist.md`](testing/manual_e2e_checklist.md)
for the end-to-end scenarios that require a live simulator/microphone and
so aren't part of the automated suite.

