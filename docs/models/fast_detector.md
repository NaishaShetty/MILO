# Model card: lightweight detector

**What it does.** A fine-tuned YOLO11n (ONNX, onnxruntime on the GPU, CPU fallback) that detects the 41 object classes MILO's tasks name (items, receptacles, switches). It runs on the **cheap observe path** (the planning loop) instead of Grounding DINO, which stays as the fallback and as the detector for the Vision panel's full pipeline.

**Data.** 21,777 frames (640x480) from 119 real AI2-THOR scenes (kitchens, living rooms, bedrooms, bathrooms), random reachable poses and camera tilts under randomised lighting (brightness, colour, hue), collected 2026-11-24 with `make frames`. **Labels are the simulator's ground-truth instance boxes**, not Grounding DINO pseudo-labels, so they are exact; Grounding DINO is used as the comparison baseline. Splits are by whole scene: 83 train, 12 val, 24 test scenes (4,392 test frames, 36,256 boxes).

**Training.** `make train-detector`: YOLO11n pretrained on COCO, 10 epochs, 480 px, about 10 minutes on an RTX 4050.

**Held-out-scene results** (`make eval-detector`; boxes matched at IoU 0.5):

| | mAP@0.5 | recall@0.5 | latency p50 |
|---|---|---|---|
| fine-tuned detector, all 4,392 test frames | 0.548 | 0.745 | 5.9 ms (GPU), 18 ms (CPU) |
| fine-tuned detector, same 300-frame subset | 0.567 | 0.739 | |
| Grounding DINO, same 300 frames | 0.315 | 0.366 | 547 ms |

The comparison favours the fine-tuned model: it is trained on this simulator's classes, while Grounding DINO is zero-shot here with one 41-class prompt and a text-to-class mapping. In MILO's own use DINO gets a single-object prompt, which is cheaper and more accurate than this benchmark setting.

**Effect on real AI2-THOR missions** (`make eval-detector-missions`: 30 missions per mode on held-out scenes, same tasks and seeds; success judged from simulator metadata, not from any detector):

| cheap-observe detector | mission success | observe time / mission | mission time |
|---|---|---|---|
| Grounding DINO (before) | 0.90 | 1.37 s | 2.63 s |
| fast, falls back to DINO if unsure **or** the named target is not found | 0.90 | 1.03 s (44 of 60 frames fell back) | 2.24 s |
| fast, falls back to DINO only if unsure (**default**) | 0.90 | 0.068 s (**20x** less) | 1.25 s |

The "target not found" rule sends most frames back to DINO, because the robot usually starts without the target in view, so it is available (`MILO_DETECTOR_FALLBACK=target`) but not the default. With the default, per-frame detector latency is about 90x lower than DINO and observe time per mission about 20x lower with equal success. **Only 30 missions per mode**, so a 2-point success difference would not be detectable.

**Known limits.** mAP@0.5 of 0.55 and recall 0.74 mean the detector misses about a quarter of visible objects; small objects and heavy occlusion are the weak spots. Trained on AI2-THOR iTHOR scenes only. With the default policy a target the fast detector misses is not double-checked. Missing or unloadable model file: MILO keeps using Grounding DINO everywhere.

**Flags.** `MILO_FAST_DETECTOR=1` (default off), `MILO_DETECTOR_DIR` (default `artifacts/detector`), `MILO_DETECTOR_FALLBACK=confidence|target`. GPU inference needs `onnxruntime-gpu` and the CUDA 12 libraries on the library path (PyTorch's bundled ones work); otherwise it runs on CPU.
