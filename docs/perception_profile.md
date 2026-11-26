# Perception profile (2026-11-26)

How long each perception stage takes on this project's laptop, measured by `scripts/profile_perception.py` (`make profile-perception`). Raw numbers: `results/perception/profile.json`.

**Setup:** NVIDIA GeForce RTX 4050 Laptop GPU (6 GB), PyTorch 2.5.1 + CUDA 12.4, Python 3.9. 40 frames (640×480) sampled evenly from the fast detector's held-out TEST scenes, plus 3 warm-up frames not counted. Grounding DINO prompt: "apple. mug. refrigerator. cabinet. table. bowl. sink. drawer." It found 3.8 objects per frame on average, 14 at most. Every time is measured with the GPU synchronised before the clock stops. One run.

| Stage | Mean | p50 | p95 | Peak VRAM while running |
|---|---|---|---|---|
| Grounding DINO (default detector) | 498 ms | 497 ms | 509 ms | 2.0 GB |
| Fast detector (YOLO11n, ONNX on CUDA) | 5.4 ms | 5.3 ms | 6.0 ms | – |
| **SAM2 masks, all boxes in one call (now)** | **127 ms** | **121 ms** | **160 ms** | 0.86 GB |
| SAM2 masks, one call per box (before) | 487 ms | 339 ms | 1,411 ms | – |
| Depth Anything (optional learned depth) | 54 ms | 54 ms | 55 ms | 0.31 GB |
| Heuristic scene graph (CPU) | 1.5 ms | 0.4 ms | 7.8 ms | – |

Model load times: Grounding DINO 0.7 s, fast detector 0.9 s, SAM2 0.1 s, Depth Anything 0.2 s (9 s the first time, when the file isn't in the OS cache yet).

## What changed because of it

**SAM2 was encoding the same image once for every object.** `SAM2Segmenter` ran one model call per detection box, and each call ran SAM2's image encoder on the full frame again. Now all of a frame's boxes go into one call: the image is encoded once and one mask is decoded per box.

- Per frame: 487 → **127 ms** on average, and 1,411 → **160 ms** at p95 (the busiest frames, where the old cost grew with every object).
- Same masks: IoU between the old and new mask of each object is 1.0 on average and at least 0.998 (the 36 frames with detections).
- `backend/tests/test_sam2_segmenter_batching.py` checks that a frame makes one model call and that each detection gets its own mask, in order.

This is the full pipeline the Vision panel uses. The planning loop already skips SAM2 (`include_masks=False`), so mission timings don't change.

## Reading the rest

- **Grounding DINO dominates** at about 0.5 s a frame. The fast detector is about 90× quicker, which is why the planning loop uses it first and only falls back to Grounding DINO when unsure ([fast detector card](models/fast_detector.md)).
- **Depth Anything is cheap** (54 ms). Ground-truth depth from AI2-THOR, the default, costs nothing.
- **VRAM:** each model was measured alone here. Running Grounding DINO, SAM2 and a local language model together peaked at 5.77-5.87 GB of 6.14 GB in the smoke test ([local_model.md](local_model.md)).
