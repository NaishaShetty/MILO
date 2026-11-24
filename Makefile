# Learned-model entry points (run from the repo root). PY can be overridden.
PY ?= python
SEED ?= 0

.PHONY: data dataset
## Generate episodes (resumable): 50 scenes, 6000 episodes, 4 workers
data:
	cd backend && $(PY) -m learning.generate --out data/episodes --episodes 6000 --scenes 50 --seed $(SEED) --workers 4

## Build train/val/test tables + report from the episode logs
dataset:
	cd backend && $(PY) -m learning.build_dataset --db-dir data/episodes --out data/dataset --seed $(SEED)
