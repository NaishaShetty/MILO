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

.PHONY: train-outcome eval-outcome promote-outcome
## Train + offline-evaluate the step outcome predictor (writes a new version)
train-outcome:
	cd backend && $(PY) -m learning.train_outcome --data data/dataset --out artifacts/outcome

## Online comparison: rule-based vs shadow vs learned reflector, 600 episodes, held-out scenes
eval-outcome:
	cd backend && $(PY) -m learning.eval_online --episodes 600 --model artifacts/outcome

## Retrain; promote only if it beats the model in service (keeps the previous for rollback)
promote-outcome:
	cd backend && $(PY) -m learning.promote

.PHONY: frames train-detector eval-detector eval-detector-missions
## Collect labelled AI2-THOR frames (ground-truth boxes), one simulator window
frames:
	cd backend && $(PY) -m learning.detector.collect --out data/frames --frames 22000 --shard 0 --shards 1

## Fine-tune the small detector and export ONNX
train-detector:
	cd backend && $(PY) -m learning.detector.train_detector --data data/frames --out artifacts/detector

## Held-out-scene mAP/recall/latency vs Grounding DINO
eval-detector:
	cd backend && $(PY) -m learning.detector.eval_detector --data data/frames --model artifacts/detector

## Real-simulator missions: Grounding DINO vs fast detector (both fallback policies)
eval-detector-missions:
	cd backend && $(PY) -m learning.detector.eval_missions --model artifacts/detector --episodes 30
