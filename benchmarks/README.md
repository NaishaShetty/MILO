# benchmarks/

Purpose
-------
Home for reproducible evaluation suites that measure this project
against itself over time and against external baselines -- e.g.
detection precision/recall on a fixed set of AI2-THOR scenes,
segmentation IoU, scene-graph relationship accuracy, or end-to-end
task success rate once the planner exists.

Why it's separate from `backend/vision/*/test_*.py`
--------------------------------------------------------
The existing `test_*.py` scripts (e.g.
`backend/vision/scene_graph/test_scene_graph.py`) are integration
smoke tests: "does the pipeline run end to end without error." A
benchmark is a different kind of artifact -- it runs against a fixed,
versioned set of scenes/prompts, produces a numeric score, and is
meant to be compared across commits/model swaps. Keeping them apart
means changing a benchmark's scoring logic never risks breaking the
smoke tests that gate basic correctness, and vice versa.

Planned contents
-----------------
- `benchmarks/perception/` -- detection/segmentation/scene-graph
  accuracy suites.
- `benchmarks/planning/` -- task success rate once a planner exists.
- A runner script per suite that writes its output into `results/`
  (see `results/README.md`) rather than printing only to stdout, so
  runs are comparable later.

Language benchmark (Phase 3.6): implemented elsewhere
-----------------------------------------------------------
The Language Parsing Runtime's benchmark suite is implemented, but
lives in [`backend/evaluation/`](../backend/evaluation/), not here --
it needs to import `LanguageAgent` and its collaborators directly
(`backend/language/`), so keeping it under `backend/` avoids a
cross-tree import and a second, disconnected implementation of the
same scoring logic. Run it via
`python -m evaluation.run_benchmark` (see the root `README.md`'s
"Optional: a real Phase 3.6 benchmark run" section); results still land
under this directory's sibling, `results/language/benchmark_runs/` (see
`results/README.md`). `backend/docs/language_interface_spec.md` section
29 has the full design.

Perception benchmark (Phase 3.x): implemented elsewhere, same reason
------------------------------------------------------------------------------
The depth/tracking benchmark suite is implemented, but lives in
[`backend/vision_evaluation/`](../backend/vision_evaluation/), not
`benchmarks/perception/` -- same rationale as the language benchmark
above: it imports `vision/depth`/`vision/tracking` internals directly.
It is synthetic/deterministic (no labeled AI2-THOR dataset exists yet --
see that package's `__init__.py`) and, unlike the language benchmark,
needs no opt-in gate (no network/GPU/cost), so it also runs as a normal
test (`backend/tests/test_vision_evaluation.py`). Run it standalone via
`python -m vision_evaluation.run_benchmark`; results land under
`results/perception/benchmark_runs/` (see `results/README.md`). See
[`docs/architecture/spatial_perception.md`](../docs/architecture/spatial_perception.md)'s
"Benchmarking" section for the full design.

Everything else in this directory remains not implemented yet -- this
file establishes the directory's purpose ahead of that work.
