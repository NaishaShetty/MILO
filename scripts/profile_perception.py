"""Time each perception stage on real AI2-THOR frames, on this machine's GPU.

    python scripts/profile_perception.py [--frames 40] [--out results/perception/profile.json]
                                        (make profile-perception)

Stages, each timed on its own with the GPU synchronised before the clock stops:

- Grounding DINO (the default detector), prompted with a fixed 8-object prompt;
- the learned fast detector (ONNX, `artifacts/detector`), if it is there;
- SAM2 on Grounding DINO's boxes, as MILO runs it (all of a frame's boxes in one
  call, so the image is encoded once);
- SAM2 one call per box, as MILO ran it until 2026-11-26 (the image encoded again
  for every box), with its masks compared to the one-call masks;
- Depth Anything (the learned depth option; ground-truth depth costs nothing);
- the heuristic scene graph.

Also: model load time and peak VRAM (`torch.cuda.max_memory_allocated`) per model.
Frames are the detector's held-out TEST split (`artifacts/detector/test.txt`),
sampled evenly; the first `--warmup` frames are run but not counted.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

PROMPT = "apple. mug. refrigerator. cabinet. table. bowl. sink. drawer."


def _sync() -> None:
    import torch

    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _timed(fn: Callable[[], Any]) -> tuple:
    _sync()
    started = time.perf_counter()
    out = fn()
    _sync()
    return out, (time.perf_counter() - started) * 1000.0


def _stats(ms: List[float]) -> Dict[str, Any]:
    if not ms:
        return {"n": 0}
    s = sorted(ms)
    return {
        "n": len(s),
        "mean_ms": round(statistics.mean(s), 1),
        "p50_ms": round(s[len(s) // 2], 1),
        "p95_ms": round(s[min(len(s) - 1, int(0.95 * len(s)))], 1),
    }


def _vram_mib() -> float:
    import torch

    if not torch.cuda.is_available():
        return 0.0
    return round(torch.cuda.max_memory_allocated() / 2**20, 1)


def _reset_peak() -> None:
    import torch

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


def frames(split: Path, n: int) -> List[Path]:
    paths = [Path(p) for p in split.read_text().split() if p.strip()]
    step = max(1, len(paths) // n)
    return paths[::step][:n]


def _scene(prompt: str) -> Any:
    from scene.metadata_keys import SceneMetadata
    from scene.scene import Scene

    s = Scene()
    s.metadata[SceneMetadata.DETECTION_PROMPT] = prompt
    return s


def _sam2_one_box_each(
    seg: Any, image: np.ndarray, boxes: List[Any]
) -> List[np.ndarray]:
    """How `SAM2Segmenter` worked until 2026-11-26: one SAM2 call per box, so the
    image is encoded again for every box. Kept here as the comparison."""
    import torch

    out = []
    pil = Image.fromarray(image)
    for b in boxes:
        inputs = seg.processor(
            images=pil, input_boxes=[[list(b)]], return_tensors="pt"
        ).to(seg.device)
        with torch.no_grad():
            outputs = seg.model(**inputs, multimask_output=False)
        masks = seg.processor.post_process_masks(
            outputs.pred_masks, inputs["original_sizes"]
        )
        out.append(masks[0][0, 0].cpu().numpy().astype(bool))
    return out


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 1.0


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--frames", type=int, default=40)
    p.add_argument("--warmup", type=int, default=3)
    p.add_argument("--split", type=Path,
                   default=ROOT / "backend" / "artifacts" / "detector" / "test.txt")  # fmt: skip
    p.add_argument("--detector-dir", type=Path,
                   default=ROOT / "backend" / "artifacts" / "detector")  # fmt: skip
    p.add_argument("--no-depth", action="store_true", help="skip Depth Anything")
    p.add_argument("--out", type=Path,
                   default=ROOT / "results" / "perception" / "profile.json")  # fmt: skip
    a = p.parse_args()

    import torch

    paths = frames(a.split, a.frames + a.warmup)
    images = [np.array(Image.open(f).convert("RGB")) for f in paths]
    report: Dict[str, Any] = {
        "date": time.strftime("%Y-%m-%d"),
        "gpu": (
            torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none (CPU)"
        ),
        "torch": torch.__version__,
        "python": platform.python_version(),
        "frames": len(images) - a.warmup,
        "warmup_frames": a.warmup,
        "frame_size": list(images[0].shape[:2]),
        "split": str(a.split),
        "prompt": PROMPT,
        "load": {},
        "stages": {},
    }

    # -- Grounding DINO ------------------------------------------------------------
    from vision.detectors.grounding_dino_detector import GroundingDINODetector

    _reset_peak()
    dino, load_ms = _timed(GroundingDINODetector)
    report["load"]["grounding_dino"] = {
        "ms": round(load_ms),
        "peak_vram_mib": _vram_mib(),
    }
    dino_ms, scenes = [], []
    for i, img in enumerate(images):
        scene, ms = _timed(lambda: dino.process(img, _scene(PROMPT)))
        if i >= a.warmup:
            dino_ms.append(ms)
        scenes.append(scene)
    report["stages"]["grounding_dino"] = {
        **_stats(dino_ms),
        "peak_vram_mib": _vram_mib(),
    }
    counted = [len(sc.detections) for sc in scenes[a.warmup :]]
    report["detections_per_frame"] = {"mean": round(statistics.mean(counted), 2),
                                      "max": max(counted)}  # fmt: skip
    dino = None  # free its VRAM before the next model

    # -- fast detector (ONNX) ------------------------------------------------------
    onnx = a.detector_dir / "detector.onnx"
    if onnx.exists():
        from learning.detector.fast_detector import FastDetector

        meta = json.loads((a.detector_dir / "classes.json").read_text())
        fast, load_ms = _timed(
            lambda: FastDetector(onnx, meta["classes"], meta.get("imgsz", 480))
        )
        report["load"]["fast_detector"] = {
            "ms": round(load_ms),
            "provider": fast.provider,
        }
        fast_ms = []
        for i, img in enumerate(images):
            _, ms = _timed(lambda: fast.detect(img))
            if i >= a.warmup:
                fast_ms.append(ms)
        report["stages"]["fast_detector"] = {
            **_stats(fast_ms),
            "provider": fast.provider,
        }
    else:
        report["stages"]["fast_detector"] = {"skipped": f"no model at {onnx}"}

    # -- SAM2 as MILO runs it (all boxes, one call) vs one call per box -------------
    from vision.segmenters.sam2_segmenter import SAM2Segmenter

    _reset_peak()
    seg, load_ms = _timed(SAM2Segmenter)
    report["load"]["sam2"] = {"ms": round(load_ms), "peak_vram_mib": _vram_mib()}
    milo_ms, one_each_ms, ious = [], [], []
    for i, (img, scene) in enumerate(zip(images, scenes)):
        if not scene.detections:
            continue
        boxes = [d.bbox for d in scene.detections]
        _, ms = _timed(lambda: seg.process(img, scene))
        together = [d.mask.binary for d in scene.detections]
        one_each, ms_each = _timed(lambda: _sam2_one_box_each(seg, img, boxes))
        if i >= a.warmup:
            milo_ms.append(ms)
            one_each_ms.append(ms_each)
            ious += [_iou(x, y) for x, y in zip(together, one_each)]
    report["stages"]["sam2"] = {**_stats(milo_ms), "peak_vram_mib": _vram_mib()}
    report["stages"]["sam2_one_call_per_box (before 2026-11-26)"] = {
        **_stats(one_each_ms),
        "mask_iou_vs_sam2": {
            "mean": round(statistics.mean(ious), 4) if ious else None,
            "min": round(min(ious), 4) if ious else None,
        },
    }
    seg = None  # free its VRAM before the next model

    # -- Depth Anything ------------------------------------------------------------
    if not a.no_depth:
        from vision.depth.depth_anything_estimator import DepthAnythingEstimator

        _reset_peak()
        depth, load_ms = _timed(DepthAnythingEstimator)
        report["load"]["depth_anything"] = {
            "ms": round(load_ms),
            "peak_vram_mib": _vram_mib(),
        }
        depth_ms = []
        for i, img in enumerate(images):
            _, ms = _timed(lambda: depth.process(img, _scene(PROMPT)))
            if i >= a.warmup:
                depth_ms.append(ms)
        report["stages"]["depth_anything"] = {
            **_stats(depth_ms),
            "peak_vram_mib": _vram_mib(),
        }
        depth = None  # free its VRAM before the next model

    # -- scene graph (CPU) ---------------------------------------------------------
    from vision.scene_graph.heuristic_scene_graph import HeuristicSceneGraph

    graph = HeuristicSceneGraph()
    graph_ms = []
    for i, (img, scene) in enumerate(zip(images, scenes)):
        _, ms = _timed(lambda: graph.process(img, scene))
        if i >= a.warmup:
            graph_ms.append(ms)
    report["stages"]["scene_graph"] = _stats(graph_ms)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
