# Learned models in MILO

Every learned component sits behind a flag that defaults to **off**, falls back to MILO's original behaviour if its model is missing, slow, unsure or throws, and never blocks the orchestrator loop. Held-out splits are by scene (or by phrasing/object for the parser and memory model). All training data comes from the synthetic simulator unless noted.

## Baseline vs learned

| Model | Flag | Baseline | Learned | Verdict |
|---|---|---|---|---|
| [Step outcome predictor](outcome_predictor.md) (+ learned reflector) | `MILO_LEARNED_REFLECTOR=off\|shadow\|on` | rule reflector: mission success 0.717, 1.94 wasted steps/mission | 0.783, 1.22 wasted steps (replans 0.118 -> 0.160); AUROC 0.968 vs 0.661 for hand-written rules, ECE 0.005 | **Better.** The one clear mission-level win. |
| [Fast detector](fast_detector.md) (YOLO11n, real AI2-THOR frames) | `MILO_FAST_DETECTOR=1` | Grounding DINO: mAP@0.5 0.315, 547 ms; observe 1.37 s/mission | mAP@0.5 0.548 (0.567 on the same 300 frames), 5.9 ms GPU; observe 0.068 s/mission (20x less); mission success 0.90 both | **Better** (faster, and more accurate on this closed set of 41 classes). |
| [Memory embedder](memory_embedder.md) | `MEMORY_EMBEDDING_PROVIDER=learned` | hashing: recall@5 0.606 | 0.9997 (BGE off the shelf 0.769); 8.5 ms p50 at 50k memories | **Better on retrieval, no effect on missions** (0.72 success for both). Synthetic, template-overlapping benchmark. Reranker added nothing. |
| [Instruction parser](instruction_parser.md) | `MILO_LEARNED_PARSER=1` | phrasebook: exact 0.137 on novel phrasings (45% right when it answers) | 0.620 alone; learned-first 0.647 exact, 0.825 when answering | **Better on novel wording**, no regression on seen wording. Template data; `navigate_to`/`pick_up` weak. |
| [World model](world_model.md) | `MILO_WORLD_MODEL=1` (+ `MILO_PLAN_RANKING=1`) | static plan scoring | next-state accuracy beats "nothing changes" on all fields (reachable 0.90 vs 0.69); plan scores less degenerate (0 for 8% vs 67%) | **No mission gain** (identical 0.70). Planners never disagree in the simulator. Leave off. |

## What did not beat its baseline

- **World model**: mission success identical; plan-score-vs-outcome AUROC only 0.525 -> 0.552.
- **Memory reranker**: 0.9997 -> 0.9998 recall@5, i.e. nothing.
- **Memory embedder at mission level**: identical results to hashing, because the planner's hint depends on the parsed object name rather than on which memory ranks first.
- **MLP outcome model**: tied with the trees (AUROC 0.968) so the simpler trees are served.

## Caveats that apply across the board

- Synthetic data. The parser and memory benchmarks use our own templates; the simulator's planners are near-identical; faults are injected by us. Numbers are evidence the pipeline works, not predictions of real-world performance. Re-measure on real logs before turning anything on by default.
- The detector is the only model trained on real rendered frames (AI2-THOR ground-truth boxes), still from a limited set of scenes.

## Operations

- **Promotion**: `make promote-outcome` promotes a retrained outcome model only if it beats the current one on held-out scenes; the previous version is kept and `python -m learning.promote --rollback` restores it.
- **Drift**: the outcome predictor tracks how far live inputs are from its training data (rolling mean |z|); above 2.5 it is set aside and MILO uses the rules. The Lab's Models panel shows the drift value and every model's on/off state and headline number (`GET /api/v1/lab/models`).
- **Calibration**: reported as ECE for the outcome predictor and the parser.

Reproduce: `make data dataset train-outcome eval-outcome`, `make train-detector eval-detector`, `make train-embedder eval-retrieval eval-retrieval-missions`, `make eval-parser`, `make eval-worldmodel`.
