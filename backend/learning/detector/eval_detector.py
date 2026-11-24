"""
eval_detector.py (backend/learning/detector)

Compares the fine-tuned detector with Grounding DINO on the held-out TEST SCENES
(ground truth = the simulator's instance boxes): mAP@0.5, recall@0.5, and
per-frame latency (ONNX on GPU, ONNX on CPU, Grounding DINO).

    cd backend
    python -m learning.detector.eval_detector --data data/frames --model artifacts/detector --dino-frames 300

The fast detector runs on every test frame; Grounding DINO (about a thousand
times heavier) on the first `--dino-frames` of them, and the fast detector's
numbers on that same subset are reported too, so the comparison is like for like.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from learning.detector.fast_detector import FastDetector


def iou(a: List[float], b: List[float]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def load_gt(
    label_file: Path, classes: List[str], w: int = 640, h: int = 480
) -> List[Dict[str, Any]]:
    out = []
    for line in label_file.read_text().split("\n"):
        if not line.strip():
            continue
        c, rx, ry, rw, rh = line.split()
        cx, cy, bw, bh = float(rx) * w, float(ry) * h, float(rw) * w, float(rh) * h
        out.append(
            {
                "cls": classes[int(c)],
                "bbox": [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2],
            }
        )
    return out


def average_precision(preds: List[Tuple[float, bool]], n_gt: int) -> float:
    """VOC-style AP from (confidence, is_true_positive) pairs."""
    if n_gt == 0:
        return float("nan")
    preds = sorted(preds, key=lambda t: -t[0])
    tp = np.cumsum([p[1] for p in preds]) if preds else np.array([0])
    fp = np.cumsum([not p[1] for p in preds]) if preds else np.array([0])
    recall = tp / n_gt
    precision = tp / np.maximum(tp + fp, 1)
    mrec, mpre = np.concatenate([[0], recall, [1]]), np.concatenate(
        [[0], precision, [0]]
    )
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def score(
    frames: List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]],
    classes: List[str],
    thr: float = 0.5,
) -> Dict[str, float]:
    """frames: [(gt, preds)] with preds = {cls, confidence, bbox}. mAP@thr and recall@thr."""
    per_class: Dict[str, List[Tuple[float, bool]]] = {c: [] for c in classes}
    n_gt = {c: 0 for c in classes}
    matched_total = gt_total = 0
    for gt, preds in frames:
        used = set()
        for g in gt:
            n_gt[g["cls"]] += 1
        gt_total += len(gt)
        for p in sorted(preds, key=lambda x: -x["confidence"]):
            best, best_i = 0.0, -1
            for i, g in enumerate(gt):
                if g["cls"] == p["cls"] and i not in used:
                    o = iou(p["bbox"], g["bbox"])
                    if o > best:
                        best, best_i = o, i
            hit = best >= thr
            if hit:
                used.add(best_i)
            per_class[p["cls"]].append((p["confidence"], hit))
        matched_total += len(used)
    aps = [average_precision(per_class[c], n_gt[c]) for c in classes if n_gt[c] > 0]
    return {
        "map50": float(np.nanmean(aps)) if aps else 0.0,
        "recall50": matched_total / max(gt_total, 1),
        "gt_boxes": gt_total,
    }


def evaluate(data: Path, model: Path, dino_frames: int = 300) -> Dict[str, Any]:
    import cv2

    meta = json.loads((data / "meta.json").read_text())
    classes: List[str] = meta["classes"]
    split = json.loads((model / "split.json").read_text())
    images = [
        p for s in split["test"] for p in sorted((data / "images" / s).glob("*.jpg"))
    ]
    labels = lambda p: data / "labels" / p.parent.name / (p.stem + ".txt")  # noqa: E731

    gpu = FastDetector(
        model / "detector.onnx",
        classes,
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        conf=0.05,
    )
    cpu = FastDetector(
        model / "detector.onnx", classes, providers=["CPUExecutionProvider"], conf=0.05
    )
    fast_frames, cpu_ms, gpu_ms = [], [], []
    for p in images:
        img = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
        dets = gpu.detect(img)
        gpu_ms.append(gpu.last_latency_ms)
        fast_frames.append(
            (
                load_gt(labels(p), classes),
                [
                    {
                        "cls": classes[d["class_id"]],
                        "confidence": d["confidence"],
                        "bbox": d["bbox"],
                    }
                    for d in dets
                ],
            )
        )
    for p in images[:100]:
        cpu.detect(cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB))
        cpu_ms.append(cpu.last_latency_ms)

    # Grounding DINO on a subset of the same frames.
    from scene.metadata_keys import SceneMetadata
    from scene.scene import Scene
    from vision.detectors.grounding_dino_detector import GroundingDINODetector

    dino = GroundingDINODetector()
    prompt = ". ".join(classes) + "."
    dino_frames_scored, dino_ms = [], []
    subset = images[:: max(len(images) // dino_frames, 1)][:dino_frames]
    idx = {p: i for i, p in enumerate(images)}
    for p in subset:
        img = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
        scene = Scene()
        scene.metadata[SceneMetadata.DETECTION_PROMPT] = prompt
        started = time.perf_counter()
        dino.process(img, scene)
        dino_ms.append((time.perf_counter() - started) * 1000.0)
        preds = []
        for d in scene.detections:
            label = next(
                (
                    c
                    for c in sorted(classes, key=len, reverse=True)
                    if c == d.label.strip()
                ),
                None,
            ) or next((c for c in classes if c in d.label), None)
            if label:
                preds.append({"cls": label, "confidence": d.confidence, "bbox": d.bbox})
        dino_frames_scored.append((load_gt(labels(p), classes), preds))

    pct = lambda a, q: float(np.percentile(a, q)) if len(a) else 0.0  # noqa: E731
    report = {
        "test_scenes": split["test"],
        "test_frames": len(images),
        "dino_frames": len(subset),
        "fast_all_test_frames": score(fast_frames, classes),
        "fast_same_subset": score([fast_frames[idx[p]] for p in subset], classes),
        "grounding_dino": score(dino_frames_scored, classes),
        "latency_ms": {
            f"fast_onnx_{gpu.provider.replace('ExecutionProvider', '').lower()}_p50": pct(
                gpu_ms, 50
            ),
            "fast_onnx_p95": pct(gpu_ms, 95),
            "fast_onnx_cpu_p50": pct(cpu_ms, 50),
            "grounding_dino_p50": pct(dino_ms, 50),
            "grounding_dino_p95": pct(dino_ms, 95),
        },
    }
    report["speedup_vs_dino_p50"] = report["latency_ms"]["grounding_dino_p50"] / max(
        report["latency_ms"]["fast_onnx_cpu_p50"], 1e-6
    )
    return report


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=Path("data/frames"))
    parser.add_argument("--model", type=Path, default=Path("artifacts/detector"))
    parser.add_argument("--dino-frames", type=int, default=300)
    parser.add_argument(
        "--out", type=Path, default=Path("artifacts/detector/eval.json")
    )
    args = parser.parse_args(argv)
    report = evaluate(args.data, args.model, args.dino_frames)
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "test_scenes"}, indent=2))


if __name__ == "__main__":
    main()
