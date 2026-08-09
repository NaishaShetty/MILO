"""
memory_evaluation (backend/memory_evaluation)

Purpose
-------
Phase 6.2's retrieval-quality evaluation harness -- a deterministic
dataset (`dataset.py`), Recall@K/Precision@K/MRR metrics (`metrics.py`),
ablation ranking configurations (`ablation.py`), and a CLI report
(`run_evaluation.py`), mirroring `backend/vision_evaluation/`'s role
for Vision and `backend/evaluation/`'s role for the Language Interface:
a benchmark package that measures `backend/memory/` without modifying
it. See `docs/phases/phase6_memory.md`'s "Evaluation" section for
measured results and `run_evaluation.py`'s module docstring for how to
run it yourself.
"""
