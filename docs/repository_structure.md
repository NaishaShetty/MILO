# Repository Structure (Detailed)

> Full module-by-module map of the backend/frontend source tree.
> The root README keeps only a short top-level tree; this is the
> complete version, moved here during the Phase 8.7 README
> restructure (2026-08-11). Note: written at the Phase 7 mark, so it
> predates `backend/agents/`, `backend/voice/`, and the Phase 8.x
> frontend pages/routes documented in
> [`docs/application/architecture.md`](application/architecture.md)
> and [`docs/application/tech_stack.md`](application/tech_stack.md).

```
backend/
    simulator/        AI2-THOR wrapper (Simulator, actions, ground-truth depth)
    scene/             Scene / Detection / Mask / Relationship data model
    config/            Model registry + download/load lifecycle
    vision/
        vision_agent.py        Image acquisition entry point
        factory.py               build_vision_system() -- wires the full Phase 3.x pipeline
        pipeline/               PerceptionPipeline orchestration
        detectors/              Grounding DINO (+ future detectors)
        segmenters/             SAM2 (+ future segmenters)
        depth/                  BaseDepthEstimator, GroundTruth + DepthAnything estimators
        spatial/                CameraIntrinsics, 2D->3D localization (pure functions)
        tracking/                BaseTracker, IoUTracker, Track / TrackStatus
        temporal/                TemporalScene, scene diffing (new/removed/moved/occluded/reappeared)
        scene_graph/            Heuristic (2D + depth-aware NEAR) scene graph
        visualization/          Scene + depth colormap rendering (OpenCV only, no inference)
    vision_evaluation/          Phase 3.x perception benchmark -- synthetic depth/tracking metrics
        models.py, synthetic_data.py, depth_metrics.py, tracking_metrics.py,
        benchmark_runner.py, result_store.py, run_benchmark.py
    prompts/                    Runtime parser assets -- loaded by language/prompt_builder.py
        parser_prompt.txt          LLM system prompt: instruction -> structured JSON (v1.1.0)
        prompt_config.yaml          Decoding params, strictness mode, model compatibility
        prompt_version.md           Prompt changelog, independent of schema versioning
        README.md                   Directory map + runtime-vs-dataset split rationale
    schemas/
        task.py                 Task / SingleTask / MultiTask Language Interface (Pydantic)
        enums.py                 TaskType / TaskPriority / ConstraintType vocabularies
        metadata.py              TaskMetadata (provenance + schema versioning)
        validators.py            Reusable validation/normalization logic for task.py
    language/                   Language Parsing Runtime (Phase 3.4)
        agent.py                    LanguageAgent -- orchestrator: parse(instruction) -> ParsedInstruction
        prompt_builder.py           Loads prompts/ assets, builds an LLMRequest
        llm_client.py                LLMClient protocol + OpenAICompatibleLLMClient
        response_parser.py           Raw LLM text -> Python dict
        schema_validator.py          dict -> validated ParsedInstruction (via schemas/task.py)
        config.py                    Env-driven runtime/deployment configuration
        exceptions.py                 Shared exception vocabulary
    evaluation/                 Phase 3.6 evaluation framework -- benchmarks LanguageAgent, never modifies it
        models.py                    Shared dataclasses/enums for every stage below
        exceptions.py                 Shared exception vocabulary
        dataset_loader.py             Loads datasets/language/evaluation/*.json -> BenchmarkCase
        benchmark_runner.py           Drives cases through a fresh LanguageAgent -> RawBenchmarkRecord
        evaluator.py                  Field-level comparison + outcome classification -> CaseEvaluation
        metrics.py                    Accuracy/latency/retry/failure-distribution aggregation
        provider_comparison.py        Same dataset/rules across multiple LLM providers
        prompt_comparison.py          Same dataset/rules across multiple prompt versions
        recovery_evaluation.py        Phase 3.5 recovery system analyzed independently
        result_store.py                Writes results/language/benchmark_runs/<run_id>/
        run_benchmark.py               CLI; real execution gated behind RUN_LLM_BENCHMARK=true
    planner/                     Task Planning subsystem (Phase 4) -- never imports simulator/, never calls AI2-THOR
        __init__.py                  Module map + the "abstract PlanStep, not simulator action" architectural rule
        models.py                    PlanStep / Plan / PlanStatus / StepStatus / ValidationResult / PlanningResult (Pydantic)
        actions.py                   ActionSpec registry -- preconditions + effects per abstract action
        state.py                     WorldState -- symbolic state simulation, no AI2-THOR required
        validator.py                 PlanValidator -- replays a Plan against a WorldState, reports structured issues
        planner.py                   Planner ABC -- shared plan()/_finalize() template method
        rule_based.py                RuleBasedPlanner -- deterministic baseline
        react.py                     ReActPlanner -- LLM-driven, structured-output-validated, rule-based fallback
        behavior_tree.py             Sequence/Selector/Condition/Action/Retry nodes + BehaviorTreePlanner
        factory.py                   create_planner() / PlannerType -- single planner-selection point
        evaluation.py                 PlannerEvaluator -- cross-strategy metrics, never fabricated
        exceptions.py                 Closed PlanningError hierarchy
    execution/                   Execution & Action Control subsystem (Phase 5) -- the only package allowed to translate a PlanStep into a simulator call
        __init__.py                  Module map + the Planner/Execution/Simulator layering rule
        models.py                    ActionType / Action / ActionResult / ExecutionEvent / ExecutionStatus / ExecutionRecord (Pydantic)
        errors.py                     ExecutionErrorCode (closed taxonomy) + ExecutionError
        resolver.py                   ObjectResolver -- PlanStep target name -> live AI2-THOR objectId
        dispatcher.py                 ActionDispatcher -- centralized Action -> Simulator method translation
        preconditions.py              PreconditionChecker -- reuses planner.actions/planner.state + grounded existence checks
        validator.py                  ResultValidator -- never trusts lastActionSuccess alone, checks ground-truth postconditions
        controller.py                 ExecutionController -- sequential executor: retries, timeouts, cancellation
        exceptions.py                 Closed ExecutionRuntimeError hierarchy
    memory/                       Memory Foundation + Intelligence + Integration (Phase 6.1/6.2/6.3)
        __init__.py                  Module map + the "domain layer never depends on SQLite/ChromaDB directly" rule
        models.py                    Memory / MemoryType / MemoryProvenance / MemoryStatus / Confidence (Pydantic)
        exceptions.py                 Closed MemoryError hierarchy (MemoryNotFoundError, DuplicateMemoryError, MemoryStoreError)
        store.py                     MemoryStore + VectorStore interfaces -- the only abstractions callers depend on
        sqlite_store.py               SQLiteMemoryStore -- authoritative structured persistence (stdlib sqlite3)
        config.py                    MemoryConfig -- env-driven database/vector-store paths, enable flag
        manager.py                    MemoryManager -- single application-facing store/get/update/delete/list API
        semantics.py                  Phase 6.2: SemanticTriple / EpisodicDetails / FailureDetails / UserFact + build_*_memory factories
        representation.py             Phase 6.2: canonical_text() -- deterministic embedding-input builder
        embeddings.py                 Phase 6.2: Embedder interface, HashingEmbedder (deterministic, offline), EmbeddingConfig
        sqlite_vector_store.py        Phase 6.2: SQLiteVectorStore -- concrete VectorStore (sqlite3 + numpy brute-force cosine search)
        retrieval.py                   Phase 6.2: RetrievalEngine, RetrievalContext, RankingWeights, MemoryResult -- hybrid retrieval + ranking
        conflicts.py                   Phase 6.2: detect_relationship / store_semantic_observation -- non-destructive duplicate/conflict tagging
        agent.py                       Phase 6.3: MemoryAgent, MemoryQueryContext, PlannerMemoryContext -- the application-facing boundary Planner/Execution depend on
    memory_evaluation/            Phase 6.2 retrieval-quality eval + Phase 6.4 memory-vs-no-memory benchmark
        dataset.py                    Fixed, deterministic memories + natural-language EVAL_QUERIES
        metrics.py                    Recall@K, Precision@K, MRR
        ablation.py                    Four RankingWeights configs (vector-only -> full hybrid)
        run_evaluation.py              Phase 6.2 CLI report -- python -m memory_evaluation.run_evaluation
        scenarios.py                   Phase 6.4: 5 version-controlled BenchmarkScenarios (categories A-E)
        experiment.py                   Phase 6.4: run_scenario() -- drives TaskRunner under memory_on/off
        memory_size.py                  Phase 6.4: synthetic-distractor memory-size experiment (10/100/1000)
        pollution.py                    Phase 6.4: semantic-memory growth vs successful-episode count
        task_ablation.py                Phase 6.4: RankingWeights ablation at task (not just retrieval) level
        run_benchmark.py                Phase 6.4 CLI -- python -m memory_evaluation.run_benchmark
    orchestration/                Phase 6.3: the only package depending on both execution/ and memory/
        __init__.py                  Why the Planner<->Memory<->Execution translation lives here, not inside any of the three
        task_runner.py                 TaskRunner -- retrieve -> plan (memory-conditioned) -> execute -> remember, one episode_id per run
    tests/
        test_task.py               Language Interface unit tests (70 cases, pytest)
        test_language_*.py          Language Parsing Runtime unit + integration tests (74 cases, pytest, LLM mocked)
        test_evaluation_*.py        Language evaluation framework unit tests (pytest, LLM always faked)
        test_api_language.py         POST /api/v1/language/parse tests (pytest, LanguageAgent mocked)
        test_api_health.py           GET /health tests (pytest, no LLM call)
        test_vision_depth.py, test_vision_localization.py,
        test_vision_tracking.py, test_vision_temporal_scene.py,
        test_vision_scene_graph_spatial.py, test_vision_visualization.py,
        test_vision_factory.py, test_vision_evaluation.py    Phase 3.x unit tests (pytest, synthetic inputs, no AI2-THOR/GPU)
        test_api_vision.py           POST /api/v1/vision/perceive tests (pytest, VisionSystem mocked)
        test_planner_models.py, test_planner_state_actions.py,
        test_planner_rule_based.py, test_planner_validator.py,
        test_planner_react.py, test_planner_behavior_tree.py,
        test_planner_factory.py, test_planner_evaluation.py,
        test_planner_e2e.py    Phase 4 unit + integration tests (70 cases, pytest, zero AI2-THOR/LLM dependency)
        test_api_planner.py          POST /api/v1/planner/{plan,validate,evaluate} tests (pytest, no AI2-THOR/LLM)
        test_execution_models.py, test_execution_dispatcher.py,
        test_execution_preconditions.py, test_execution_validator.py,
        test_execution_controller.py    Phase 5 unit + integration tests (pytest, FakeSimulator, zero AI2-THOR dependency)
        test_api_execution.py        POST/GET /api/v1/execution/* tests (pytest, FakeSimulator via dependency_overrides)
        _execution_test_helpers.py   Shared FakeSimulator/FakeEvent fakes for the Phase 5 test suite (not collected as tests)
        test_memory_models.py, test_memory_store.py, test_memory_sqlite_store.py,
        test_memory_manager.py, test_memory_config.py    Phase 6.1 unit + integration tests (59 cases, pytest, tmp_path-isolated SQLite)
        test_memory_embeddings.py, test_memory_representation.py, test_memory_semantics.py,
        test_memory_sqlite_vector_store.py, test_memory_retrieval.py, test_memory_conflicts.py,
        test_memory_evaluation.py    Phase 6.2 unit + integration tests (166 cases, pytest, deterministic offline embedder)
        test_memory_agent.py, test_planner_memory_context.py,
        test_orchestration_task_runner.py    Phase 6.3 unit + integration + golden end-to-end tests (55 cases, pytest, FakeSimulator, zero AI2-THOR/LLM dependency)
        test_memory_evaluation_benchmark.py    Phase 6.4 benchmark regression tests (18 cases, pytest, FakeSimulator) -- locks in the measured memory-vs-no-memory findings, including the stale-memory task-failure case
    simulator/
        test_execution_e2e.py        Real AI2-THOR end-to-end tests (Phase 5) -- opt-in via RUN_SIMULATOR_TESTS=true, never run in CI
    api/                         Thin HTTP interface -- wraps LanguageAgent, VisionSystem, Planner, and ExecutionController, never duplicates their logic
        app.py                       FastAPI app, CORS, LanguageAgent + Simulator lifecycle (lifespan)
        routes/
            health.py                    GET /health (no LLM call)
            language.py                   POST /api/v1/language/parse + error mapping
            vision.py                     POST /api/v1/vision/perceive + error mapping (Phase 3.x)
            planner.py                     POST /api/v1/planner/{plan,validate,evaluate} (Phase 4)
            execution.py                    POST /api/v1/execution/start, GET/{id}, POST /{id}/cancel, GET /{id}/steps, GET /{id}/events (Phase 5)
        models/
            language.py                   ParseRequest / ParseResponse / ParseDiagnostics / ErrorResponse
            vision.py                      PerceiveRequest / PerceiveResponse / SpatialObject / PerceptionStatus (Phase 3.x)
            planner.py                     PlanRequest / ValidateRequest / EvaluateRequest / EvaluateResponse (Phase 4)
            execution.py                    StartExecutionRequest (Phase 5)
    docs/
        language_interface_spec.md   Language Interface design spec (Phase 3.1-3.7)
    outputs/
        memory/                       SQLiteMemoryStore's default database file + SQLiteVectorStore's vectors.db (backend/outputs/, gitignored)
    agents/                       Reserved for future phases (the Phase 6 Memory Agent, once built on top of memory/)
docs/
    architecture/      Cross-cutting design docs (perception_pipeline.md, spatial_perception.md, api_contracts.md)
    phases/            Per-phase implementation notes (phase1_navigation.md, phase2_vision.md, phase5_execution.md,
                       phase6_memory.md, ...)
datasets/
    language/                   Research/benchmark assets -- NOT loaded by any runtime code
        prompts/
            examples.json           21 few-shot examples, disjoint from parser_prompt.txt's inline ones
            negative_examples.json  10 anti-pattern examples, each traced to the rule it violates
            edge_cases.json          14 structurally tricky-but-valid inputs
        evaluation/
            success_cases.json      15-case correctness benchmark
            failure_cases.json      12-case robustness / hallucination-resistance benchmark
            ambiguity_cases.json    10-case clarification-detection benchmark (precision + recall)
models/                Project-local model weights (gitignored)
frontend/              Vision-Language Robotics dashboard (React + TypeScript + Vite)
    src/
        api/               language.ts / types.ts (Language API), vision.ts / visionTypes.ts (Vision API, Phase 3.x),
                            planner.ts / plannerTypes.ts (Planner API, Phase 4), execution.ts / executionTypes.ts (Execution API, Phase 5)
        components/        InstructionForm, TaskCard, ResultView, ClarificationBanner, ErrorBanner, DiagnosticsPanel (Language);
                            VisionPanel, VisionPromptForm, CameraPanel, DepthPanel, PerceptionStatusPanel,
                            SceneChangesList, ObjectInspectorTable, VisionErrorBanner (Vision, Phase 3.x);
                            PlannerPanel, PlanStepsList, ValidationPanel, PlannerComparisonTable (Planner, Phase 4);
                            ExecutionPanel, ExecutionStepsList, ExecutionLog (Execution, Phase 5)
        App.tsx, main.tsx   Composes the Vision panel + Language panel side by side; PlannerPanel renders inside
                            ResultView beneath a parsed task; ExecutionPanel renders inside PlannerPanel beneath a
                            generated plan, entry point
    README.md               Frontend-specific setup/dev/test/build instructions
benchmarks/            Reproducible evaluation suites; the Phase 3.6 language benchmark lives in
                        backend/evaluation/, the Phase 3.x perception benchmark in backend/vision_evaluation/,
                        and the Phase 4 planner comparison lives in backend/planner/evaluation.py
                        (via POST /api/v1/planner/evaluate) -- each run via its own entry point
experiments/           Exploratory / one-off research work
deployment/            Environment/target-specific deployment config
docker/                Dockerfile for a reproducible backend environment
results/               Benchmark/experiment run outputs (gitignored)
    language/benchmark_runs/<run_id>/     One Phase 3.6 benchmark run's metadata/raw results/metrics/summary
    perception/benchmark_runs/<run_id>/   One Phase 3.x benchmark run's metadata/depth metrics/tracking metrics/summary
.github/
    workflows/ci.yml   CI: format/lint/type-check/test on every push and PR
pyproject.toml         Shared black/ruff/mypy configuration
```

