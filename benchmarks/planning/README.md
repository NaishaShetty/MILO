# benchmarks/planning/

Pointer only — see `benchmarks/README.md`'s "Planning benchmark (Phase
E): implemented elsewhere" section for why. The actual dataset and
runner live at
[`backend/planning_evaluation/`](../../backend/planning_evaluation/):

- Dataset: `backend/planning_evaluation/dataset/v1.0/tasks.json` +
  its [dataset card](../../backend/planning_evaluation/dataset/v1.0/README.md)
  (`milo_benchmark v1.0` — the same file structure/card intended for
  publishing as a Hugging Face `datasets` repo).
- Runner: `backend/planning_evaluation/run_benchmark.py` (planner
  comparison: rule-based vs Behavior Tree vs real-AI2-THOR live
  goal-check scoring) and `run_memory_ablation.py`
  (memory-conditioned vs memory-off, across scene diversity).
- Findings write-up:
  [`experiments/reports/phase_e_milo_benchmark_report.md`](../../experiments/reports/phase_e_milo_benchmark_report.md).
