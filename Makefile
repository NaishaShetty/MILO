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

## Contrastively fine-tune the memory embedder (from the Phase A logs)
train-embedder:
	cd backend && $(PY) -m learning.retrieval.train_embedder --db-dir data/episodes --out artifacts/memory_embedder

## Held-out recall@k/MRR + latency: hashing vs BGE vs fine-tuned (+ reranker)
eval-retrieval:
	cd backend && $(PY) -m learning.retrieval.eval_retrieval --db-dir data/episodes --model artifacts/memory_embedder

## Missions with memory in the loop: hashing vs learned embedder
eval-retrieval-missions:
	cd backend && MEMORY_LEARNED_EMBEDDER_DIR=artifacts/memory_embedder $(PY) -m learning.retrieval.eval_missions --episodes 200

## Small instruction parser: train, then held-out-phrasing evaluation vs the rule phrasebook
eval-parser:
	cd backend && $(PY) -m learning.parser.eval_parser --out artifacts/parser

## World model: transition accuracy vs "nothing changes", rollout plan scoring, missions
eval-worldmodel:
	cd backend && $(PY) -m learning.eval_worldmodel --data data/dataset --model artifacts/outcome --out artifacts/worldmodel --episodes 400

## World model on the competing-route tier: failures caught before acting
eval-worldmodel-routes:
	cd backend && $(PY) -m learning.eval_worldmodel_routes --artifacts artifacts

## How often a "success" is contradicted by the world (goal predicates), and trace cost
eval-goal-check:
	cd backend && $(PY) -m verification.eval_goal_check --episodes 300

## Novel tasks: 60 held-out commands (baseline / offline / reference plans; add --claude with credentials)
eval-novel:
	cd backend && $(PY) -m novel.eval_novel

## Memory poisoning red-team (defence off vs on) and repeat failures with failure memory
eval-trust:
	cd backend && $(PY) -m memory.eval_trust

## Fixed benchmark: every planner, ablations, fault recovery -> benchmarks/latest.{json,md}
benchmark:
	cd backend && $(PY) -m benchmark.run --subset full

## The CI regression gate (fast subset vs benchmarks/ci_baseline.json)
benchmark-ci:
	cd backend && $(PY) -m benchmark.ci

## Re-record the demo missions the hosted UI replays (frontend/public/demo)
demo:
	cd backend && $(PY) -m demo.record

## README screenshots into docs/images/ (dev server on $BASE with the real backend behind it;
## DEMO_ONLY=1 for just the demo-mode pages, no backend needed)
screenshots:
	cd frontend && node scripts/screenshots.mjs

# ---- Local language model (Ollama) and real AI2-THOR runs; see docs/local_model.md ----
# Every target below is resumable: re-run the same command after an interruption.
OLLAMA_URL ?= http://localhost:11434
MODEL ?= qwen2.5:7b
BAKEOFF_MODELS ?= qwen2.5:7b qwen3.5:4b llama3.1:8b gemma4:e2b-it-qat

.PHONY: model-bakeoff novel-eval benchmark-thor collect-thor train-real profile-perception parser-phrasings
## Messier parser phrasings from the local model, then parser before/after (about 5 min)
parser-phrasings:
	cd backend && MILO_OLLAMA_URL=$(OLLAMA_URL) $(PY) -m learning.parser.llm_phrasings --model $(MODEL)

## Time each perception stage (Grounding DINO, fast detector, SAM2, depth) on this GPU
profile-perception:
	$(PY) scripts/profile_perception.py --frames 40

## Pick the local model on the 40-command DEV set (3 runs per model)
model-bakeoff:
	@echo "Expect about 15-30 min per model per run on an RTX 4050 laptop (resumable)."
	$(PY) scripts/model_bakeoff.py --url $(OLLAMA_URL) --runs 3 --models $(BAKEOFF_MODELS)

## The 60 held-out TEST commands + skill learning with the local model (3 runs)
novel-eval:
	@echo "Expect about 1-2 hours for 3 runs of $(MODEL) (resumable per run)."
	cd backend && MILO_OLLAMA_URL=$(OLLAMA_URL) $(PY) -m novel.eval_novel --ollama $(MODEL) --runs 3

## Real AI2-THOR benchmark (milo_benchmark v1.1, 54 tasks x 3 planners)
benchmark-thor:
	@echo "Expect about 1 hour per planner (fresh Unity per episode). Resumable; CHUNK=20 to stop early."
	cd backend && $(PY) -m benchmark.thor --version 1.1 $(if $(CHUNK),--chunk $(CHUNK),)

## Real AI2-THOR episodes for the outcome predictor (300 in held-out scenes)
collect-thor:
	@echo "Expect about 5-10 hours for 600 episodes. Run it overnight (tmux or nohup); resumable."
	cd backend && $(PY) -m learning.collect_thor --episodes 600

## Retrain the outcome predictor on synthetic + real episodes; test = held-out real scenes
train-real:
	cd backend && $(PY) -m learning.build_dataset --db-dir data/episodes data/episodes_thor --out data/dataset_real --seed $(SEED) \
	  --test-scenes $$($(PY) -c "from learning.collect_thor import HELD_OUT_SCENES; print(','.join(HELD_OUT_SCENES))")
	cd backend && $(PY) -m learning.train_outcome --data data/dataset_real --out artifacts/outcome_real
