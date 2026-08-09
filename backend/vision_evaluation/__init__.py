"""
vision_evaluation

Purpose
-------
Phase 3.x.9 -- Depth/Tracking Benchmarking. A dedicated perception
evaluation framework, deliberately separate from `backend/evaluation/`
(the Phase 3.6 *language* benchmark). `backend/evaluation/`'s own
module docstrings scope it to `LanguageAgent` internals specifically;
mirroring its layered structure here (raw-case running -> metrics
computation -> versioned, non-overwriting result persistence) without
importing anything from it keeps the two domains independent, per this
project's "keep it separate from the Phase 3.6 language benchmark"
requirement.

Scope: synthetic, not a curated labeled dataset
------------------------------------------------------
Unlike the language benchmark (fixed, versioned JSON datasets under
`datasets/language/evaluation/`), no labeled ground-truth dataset for
AI2-THOR depth/tracking exists in this project. This framework
therefore generates small, deterministic (seeded) synthetic depth maps
and detection sequences at run time (`synthetic_data.py`) rather than
loading a dataset file -- an explicitly quantitative, but synthetic,
evaluation. This is documented, not hidden: every result this framework
produces is scoped to "how well do the depth-extraction/tracking
*algorithms* behave under known, controlled conditions," not "how
accurate is this model on real AI2-THOR scenes" (the latter would need
a real labeled dataset, out of scope for this phase -- see
`docs/architecture/spatial_perception.md`'s limitations section).

Why this still exercises real project code, not just metric math
------------------------------------------------------------------------
`benchmark_runner.py` runs the actual `BaseDepthEstimator` object-depth
extraction and the actual `IoUTracker` against synthetic inputs, rather
than hand-computing "predicted" values -- so a regression in either
module's real logic shows up here, not just a regression in
hand-written test fixtures that happen to mirror it.

Modules
-------
- `models.py`: shared dataclasses (`MetricValue`, run metadata).
- `synthetic_data.py`: deterministic synthetic depth/tracking cases.
- `depth_metrics.py`: MAE/RMSE/RelAbsErr/threshold-accuracy, plus a
  scale-alignment step for relative (Depth Anything) predictions.
- `tracking_metrics.py`: ID switches, fragmentation, precision/recall,
  tracking success rate.
- `benchmark_runner.py`: runs the real depth-extraction/tracking code
  against synthetic cases and computes both metric sets.
- `result_store.py`: persists a run to
  `results/perception/benchmark_runs/<run_id>/`, refusing to overwrite.
- `run_benchmark.py`: CLI entry point.
"""
