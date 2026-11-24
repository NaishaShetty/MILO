"""
train_detector.py (backend/learning/detector)

Fine-tunes a small YOLO detector (ultralytics YOLO11n, pretrained on COCO) on
the collected AI2-THOR frames, then exports it to ONNX.

    cd backend
    python -m learning.detector.train_detector --data data/frames --out artifacts/detector --epochs 12

Splits are by SCENE (never by frame): test scenes are whole held-out floor
plans (20%), validation scenes another 10%, the rest train. Writes
`<out>/detector.onnx`, `<out>/classes.json`, `<out>/split.json`, and
`<out>/train_report.json`.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from learning.build_dataset import split_scenes


def scene_split(scenes: List[str], seed: int = 0) -> Dict[str, List[str]]:
    rest, test = split_scenes(scenes, 0.2, seed)
    train, val = split_scenes(rest, 0.125, seed + 1)  # 12.5% of 80% = 10% of all
    return {"train": train, "val": val, "test": test}


def write_dataset(data: Path, out: Path, seed: int = 0) -> Path:
    meta = json.loads((data / "meta.json").read_text())
    done = sorted(p.parent.name for p in (data / "images").glob("*/.done"))
    split = scene_split(done, seed)
    out.mkdir(parents=True, exist_ok=True)
    for name, scenes in split.items():
        paths = [
            str(p.resolve())
            for s in scenes
            for p in sorted((data / "images" / s).glob("*.jpg"))
        ]
        (out / f"{name}.txt").write_text("\n".join(paths) + "\n")
    yaml = out / "data.yaml"
    names = "\n".join(f"  {i}: {c}" for i, c in enumerate(meta["classes"]))
    yaml.write_text(
        f"path: {out.resolve()}\ntrain: train.txt\nval: val.txt\ntest: test.txt\nnames:\n{names}\n"
    )
    (out / "split.json").write_text(json.dumps(split, indent=2))
    (out / "classes.json").write_text(
        json.dumps({"classes": meta["classes"], "imgsz": 480})
    )
    return yaml


def train(
    data: Path,
    out: Path,
    epochs: int = 12,
    batch: int = 32,
    imgsz: int = 480,
    device: Any = 0,
    seed: int = 0,
) -> Dict[str, Any]:
    from ultralytics import YOLO

    yaml = write_dataset(data, out, seed)
    model = YOLO("yolo11n.pt")
    model.train(
        data=str(yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        seed=seed,
        workers=4,
        project=str((out / "runs").resolve()),
        name="train",
        exist_ok=True,
        verbose=False,
        plots=False,
        fliplr=0.5,
        hsv_v=0.5,
        hsv_s=0.5,
        patience=0,
        amp=True,
    )
    best = out / "runs" / "train" / "weights" / "best.pt"
    exported = YOLO(str(best)).export(
        format="onnx", imgsz=imgsz, simplify=True, opset=17, dynamic=False
    )
    shutil.copy(exported, out / "detector.onnx")
    metrics = YOLO(str(best)).val(
        data=str(yaml), split="test", imgsz=imgsz, device=device, verbose=False
    )
    report = {
        "epochs": epochs,
        "imgsz": imgsz,
        "test_map50": float(metrics.box.map50),
        "test_map50_95": float(metrics.box.map),
        "test_recall": float(metrics.box.mr),
        "test_precision": float(metrics.box.mp),
        "split": {
            k: len(v)
            for k, v in scene_split(
                sorted(p.parent.name for p in (data / "images").glob("*/.done")), seed
            ).items()
        },
    }
    (out / "train_report.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=Path("data/frames"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/detector"))
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch", type=int, default=32)
    args = parser.parse_args(argv)
    print(json.dumps(train(args.data, args.out, args.epochs, args.batch), indent=2))


if __name__ == "__main__":
    main()
