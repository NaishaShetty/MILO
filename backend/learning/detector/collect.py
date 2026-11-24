"""
collect.py (backend/learning/detector)

Collects labelled frames from the REAL AI2-THOR simulator for the lightweight
detector. For every scene it samples random reachable poses (position,
rotation, camera tilt) under several randomised lighting settings and saves
the RGB frame plus YOLO-format labels.

Labels come from the simulator's *ground-truth instance segmentation boxes*
(`instance_detections2D`), mapped to MILO's object classes -- exact, no
pseudo-label noise. Grounding DINO is used separately (`eval_detector.py`) as
the comparison baseline and as an independent check on a sample of frames.

    cd backend
    python -m learning.detector.collect --out data/frames --frames 24000 --seed 0

Resumable: a scene with a `.done` marker is skipped. Output layout:
    <out>/images/<scene>/<n>.jpg    <out>/labels/<scene>/<n>.txt
    <out>/meta.json                 class list, size, scene list
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import List, Optional

from learning.detector.classes import CLASSES, class_of

SCENES = (
    [f"FloorPlan{i}" for i in range(1, 31)]
    + [f"FloorPlan{200 + i}" for i in range(1, 31)]
    + [f"FloorPlan{300 + i}" for i in range(1, 31)]
    + [f"FloorPlan{400 + i}" for i in range(1, 31)]
)
WIDTH, HEIGHT = 640, 480
MIN_BOX_PX = 12  # ignore boxes smaller than this in either dimension


def yolo_line(cls: int, box: List[float]) -> Optional[str]:
    x1, y1, x2, y2 = (
        max(0.0, box[0]),
        max(0.0, box[1]),
        min(WIDTH, box[2]),
        min(HEIGHT, box[3]),
    )
    w, h = x2 - x1, y2 - y1
    if w < MIN_BOX_PX or h < MIN_BOX_PX:
        return None
    return f"{cls} {(x1 + w / 2) / WIDTH:.6f} {(y1 + h / 2) / HEIGHT:.6f} {w / WIDTH:.6f} {h / HEIGHT:.6f}"


def labels_from_event(event) -> List[str]:
    lines = []
    for object_id, box in (event.instance_detections2D or {}).items():
        name = class_of(object_id.split("|")[0])
        if name is None:
            continue
        line = yolo_line(CLASSES.index(name), [float(v) for v in box])
        if line:
            lines.append(line)
    return lines


def collect_scene(
    controller, scene: str, n: int, rng: random.Random, out: Path, start: int = 0
) -> int:
    from PIL import Image

    controller.reset(scene=scene)
    positions = (
        controller.step(action="GetReachablePositions").metadata["actionReturn"] or []
    )
    if not positions:
        return 0
    (out / "images" / scene).mkdir(parents=True, exist_ok=True)
    (out / "labels" / scene).mkdir(parents=True, exist_ok=True)
    saved, tries = 0, 0
    per_light = max(n // 4, 1)
    while saved < n and tries < n * 4:
        if saved % per_light == 0:
            controller.step(
                action="RandomizeLighting",
                brightness=(0.4, 1.6),
                randomizeColor=True,
                hue=(0, 0.15),
                saturation=(0.5, 1.0),
                synchronized=False,
            )
        tries += 1
        pos = rng.choice(positions)
        event = controller.step(
            action="TeleportFull",
            position=pos,
            rotation={"x": 0, "y": rng.choice(range(0, 360, 30)), "z": 0},
            horizon=rng.choice([-20, 0, 15, 30]),
            standing=True,
        )
        if not event.metadata["lastActionSuccess"]:
            continue
        lines = labels_from_event(event)
        if not lines:
            continue  # a frame with no target objects teaches nothing
        name = f"{start + saved:05d}"
        Image.fromarray(event.frame).save(
            out / "images" / scene / f"{name}.jpg", quality=92
        )
        (out / "labels" / scene / f"{name}.txt").write_text("\n".join(lines) + "\n")
        saved += 1
    (out / "images" / scene / ".done").write_text(str(saved))
    return saved


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=Path("data/frames"))
    parser.add_argument("--frames", type=int, default=24000)
    parser.add_argument("--scenes", type=int, default=len(SCENES))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--shard", type=int, default=0, help="this process's shard index"
    )
    parser.add_argument(
        "--shards", type=int, default=1, help="total processes splitting the scenes"
    )
    args = parser.parse_args(argv)

    from ai2thor.controller import Controller

    scenes = SCENES[: args.scenes]
    per_scene = max(args.frames // len(scenes), 1)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "meta.json").write_text(
        json.dumps(
            {
                "classes": CLASSES,
                "width": WIDTH,
                "height": HEIGHT,
                "scenes": scenes,
                "per_scene": per_scene,
            }
        )
    )
    controller = Controller(
        width=WIDTH,
        height=HEIGHT,
        renderInstanceSegmentation=True,
        gridSize=0.25,
        snapToGrid=False,
        fieldOfView=90,
    )
    started, total = time.time(), 0
    try:
        for i, scene in enumerate(scenes):
            if (
                i % args.shards != args.shard
                or (args.out / "images" / scene / ".done").exists()
            ):
                continue
            total += collect_scene(
                controller,
                scene,
                per_scene,
                random.Random(f"{args.seed}-{scene}"),
                args.out,
            )
            print(
                f"[shard {args.shard}] {scene} done; {total} frames, {time.time() - started:.0f}s",
                flush=True,
            )
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
