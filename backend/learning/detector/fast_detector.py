"""
fast_detector.py (backend/learning/detector)

`FastDetector` runs the fine-tuned small detector (ONNX, onnxruntime on the GPU
if available, else CPU) behind the same `BaseDetector` interface as Grounding
DINO. `FallbackDetector` is what the cheap observe path uses:

    fast detector first  ->  Grounding DINO only when
        - the fast detector's best confidence is low, or
        - a *named* target (from the detection prompt, e.g. "apple.") was not found.

Missing/broken model file -> `build_fast_detector()` returns `None` and the
caller keeps Grounding DINO everywhere (today's behaviour). The Vision panel
always uses the full pipeline.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import cv2
import numpy as np

from scene.detection import Detection
from scene.metadata_keys import SceneMetadata
from vision.detectors.base_detector import BaseDetector

logger = logging.getLogger(__name__)


def letterbox(image: np.ndarray, size: int) -> tuple:
    """Resize keeping aspect ratio and pad to a `size` x `size` square.
    Returns (tensor CHW float32 0..1, scale, pad_x, pad_y)."""
    h, w = image.shape[:2]
    scale = size / max(h, w)
    nh, nw = round(h * scale), round(w * scale)
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_y, pad_x = (size - nh) // 2, (size - nw) // 2
    canvas[pad_y : pad_y + nh, pad_x : pad_x + nw] = resized
    tensor = canvas.transpose(2, 0, 1).astype(np.float32)[None] / 255.0
    return tensor, scale, pad_x, pad_y


def decode(
    output: np.ndarray,
    scale: float,
    pad_x: int,
    pad_y: int,
    shape: tuple,
    conf: float,
    iou: float = 0.5,
) -> List[Dict[str, Any]]:
    """YOLO ONNX output (1, 4+nc, N) -> NMS'd detections in original pixels."""
    preds = output[0].T  # (N, 4+nc)
    scores = preds[:, 4:]
    cls = scores.argmax(1)
    best = scores[np.arange(len(scores)), cls]
    keep = best >= conf
    if not keep.any():
        return []
    preds, cls, best = preds[keep], cls[keep], best[keep]
    cx, cy, w, h = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    x1 = (cx - w / 2 - pad_x) / scale
    y1 = (cy - h / 2 - pad_y) / scale
    x2 = (cx + w / 2 - pad_x) / scale
    y2 = (cy + h / 2 - pad_y) / scale
    H, W = shape[:2]
    boxes = np.stack(
        [np.clip(x1, 0, W), np.clip(y1, 0, H), np.clip(x2, 0, W), np.clip(y2, 0, H)], 1
    )
    idx = cv2.dnn.NMSBoxes(
        [
            [float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])]
            for b in boxes
        ],
        best.astype(float).tolist(),
        conf,
        iou,
    )
    return [
        {
            "class_id": int(cls[i]),
            "confidence": float(best[i]),
            "bbox": boxes[i].tolist(),
        }
        for i in (np.array(idx).flatten() if len(idx) else [])
    ]


class FastDetector(BaseDetector):
    def __init__(
        self,
        onnx_path: Path,
        classes: List[str],
        imgsz: int = 480,
        conf: float = 0.25,
        providers: Optional[List[str]] = None,
    ):
        try:
            import torch  # noqa: F401  -- loads the CUDA libraries onnxruntime-gpu needs
        except ImportError:
            pass
        import onnxruntime as ort

        self.classes = classes
        self.imgsz = imgsz
        self.conf = conf
        wanted = providers or ["CUDAExecutionProvider", "CPUExecutionProvider"]
        available = ort.get_available_providers()
        self._session = ort.InferenceSession(
            str(onnx_path),
            providers=[p for p in wanted if p in available] or ["CPUExecutionProvider"],
        )
        self._input = self._session.get_inputs()[0].name
        self.provider = self._session.get_providers()[0]
        self.last_latency_ms = 0.0
        self.detect(np.zeros((480, 640, 3), dtype=np.uint8))  # warm-up

    def detect(
        self, image: np.ndarray, conf: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        started = time.perf_counter()
        tensor, scale, pad_x, pad_y = letterbox(image, self.imgsz)
        out = self._session.run(None, {self._input: tensor})[0]
        result = decode(out, scale, pad_x, pad_y, image.shape, conf or self.conf)
        self.last_latency_ms = (time.perf_counter() - started) * 1000.0
        return result

    def process(self, image, scene):
        for d in self.detect(image):
            scene.add_detection(
                Detection(
                    label=self.classes[d["class_id"]],
                    confidence=d["confidence"],
                    bbox=d["bbox"],
                )
            )
        return scene


#: Everyday words in prompts -> detector class names.
_ALIAS = {
    "fridge": "refrigerator",
    "tv": "television",
    "light": "light switch",
    "lights": "light switch",
    "tap": "faucet",
    "counter": "countertop",
    "keychain": "keys",
}


def _canon(name: str) -> str:
    return _ALIAS.get(name, name)


def _targets(prompt: Optional[str]) -> List[str]:
    return [t.strip().lower() for t in (prompt or "").split(".") if t.strip()]


class FallbackDetector(BaseDetector):
    """Fast detector first; Grounding DINO only when the fast one is unsure or
    misses a named target. Counts how often each ran (`stats`)."""

    def __init__(
        self,
        fast: FastDetector,
        slow: BaseDetector,
        min_confidence: float = 0.45,
        fallback_on_missing: bool = True,
    ):
        self._fast, self._slow = fast, slow
        #: True: also fall back when a named target is not found (default). False:
        #: only when the fast detector is unsure -- cheaper, but a target the fast
        #: detector misses is then not double-checked.
        self._on_missing = fallback_on_missing
        self._min = min_confidence
        self.stats = {"frames": 0, "fallbacks": 0}

    def process(self, image, scene):
        self.stats["frames"] += 1
        prompt = scene.metadata.get(SceneMetadata.DETECTION_PROMPT)
        found = self._fast.detect(image)
        labels = {self._fast.classes[d["class_id"]] for d in found}
        missing = (
            [t for t in (_canon(t) for t in _targets(prompt)) if t not in labels]
            if self._on_missing
            else []
        )
        unsure = not found or max(d["confidence"] for d in found) < self._min
        if missing or unsure:
            self.stats["fallbacks"] += 1
            return self._slow.process(image, scene)
        for d in found:
            scene.add_detection(
                Detection(
                    label=self._fast.classes[d["class_id"]],
                    confidence=d["confidence"],
                    bbox=d["bbox"],
                )
            )
        return scene


def build_fast_detector(
    model_dir: Path, slow: BaseDetector, env_flag: bool = True
) -> Optional[FallbackDetector]:
    """`FallbackDetector` from `<model_dir>/detector.onnx` + `classes.json`, or
    `None` (never raises) if the model is missing or fails to load."""
    try:
        if not env_flag:
            return None
        onnx = Path(model_dir) / "detector.onnx"
        meta = json.loads((Path(model_dir) / "classes.json").read_text())
        import os

        on_missing = (
            os.environ.get("MILO_DETECTOR_FALLBACK", "confidence").strip().lower()
            != "confidence"
        )
        return FallbackDetector(
            FastDetector(onnx, meta["classes"], meta.get("imgsz", 480)),
            slow,
            fallback_on_missing=on_missing,
        )
    except Exception:
        logger.warning(
            "fast_detector.unavailable -- using Grounding DINO", exc_info=True
        )
        return None


_ = Callable
