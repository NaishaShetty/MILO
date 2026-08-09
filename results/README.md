# results/

Purpose
-------
Home for the output artifacts of `benchmarks/` runs -- scores, logs,
generated plots/tables -- kept separate from the code that produced
them so a benchmark script's own directory stays clean and results
from different runs/commits can be compared side by side.

Why contents are gitignored
--------------------------------
Like `backend/outputs/` (annotated frames from perception runs),
`results/` holds generated, regenerable artifacts, not source. Per the
project `.gitignore`, files under `results/` are excluded from version
control except this `README.md` and a `.gitkeep`, so the directory
structure is preserved in a fresh checkout without committing binary
run outputs.

Suggested organization
---------------------------
One subdirectory per benchmark run, named by date and benchmark suite
(e.g. `results/2026-08-07_perception_benchmark/`), containing whatever
that suite produces (a scores file, plots, raw per-scene output).

Phase 3.6 (Testing & Benchmarking): implemented
------------------------------------------------------
`backend/evaluation/result_store.py` writes every language-parsing
benchmark run to:

```
results/language/benchmark_runs/<run_id>/
    metadata.json    RunMetadata -- provider, model, prompt/schema/benchmark
                      version, dataset versions, recovery config, decoding
                      params, case counts, run_mode (mocked|real). No API
                      keys or credentials are ever written here.
    raw_results.json Every RawBenchmarkRecord (one per benchmark case)
    metrics.json      The full MetricsReport (per-category + overall,
                       micro/macro task accuracy, retry/latency/failure
                       distribution) -- see backend/docs/language_interface_spec.md
                       section 29.6 for every metric's exact definition.
    summary.json      A small, human-scannable digest of the two above
    recovery.json      The RecoveryReport (Phase 3.6.6), when computed
```

`run_id` is time-sortable and collision-resistant
(`evaluation.models.generate_run_id`); a run is never overwritten --
each run gets its own directory. See
`backend/docs/language_interface_spec.md` section 29.9 for the full
reproducibility/versioning design, and the root `README.md`'s "Optional:
a real Phase 3.6 benchmark run" section for how to produce one.

Phase 3.x (Depth/Tracking Benchmarking): implemented
------------------------------------------------------------
`backend/vision_evaluation/result_store.py` writes every perception
benchmark run to:

```
results/perception/benchmark_runs/<run_id>/
    metadata.json           RunMetadata -- evaluation version, dataset
                             version (always "synthetic-v1" today), depth
                             source, camera intrinsics, tracker config,
                             sample/frame counts. No secrets.
    depth_metrics.json       MAE/RMSE/relative-absolute-error/threshold
                              accuracy, pixel- and object-level, each with
                              its own units and interpretation.
    tracking_metrics.json    ID switches, track fragmentation, recall,
                              tracking success rate.
    summary.json              A small, human-scannable digest of the two above
```

Same non-overwrite guarantee as the language benchmark
(`generate_run_id`-named directories). See
`docs/architecture/spatial_perception.md`'s "Benchmarking" section for
the full design, including why this suite is synthetic rather than
based on a curated labeled dataset.

Everything else in this directory remains not implemented yet -- this
file establishes the directory's purpose ahead of that work.
