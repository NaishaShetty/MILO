"""
validate_detection_threshold.py

Purpose
-------
Real precision/recall validation of `GroundingDINODetector`'s
box_threshold, across a proper validation set (true positives AND
true negatives, multiple scenes/object types) -- not a re-test of the
same single mug example that originally surfaced the sim-to-real
detection-confidence gap (`docs/roadmap.md`). That original finding
measured recall only (0.35 misses real, ground-truth-visible objects;
0.15 recovers most of them) and explicitly never checked the
false-positive side -- this script closes that gap.

Design
------
One real AI2-THOR frame per scene (all 9 `milo_benchmark v1.1`
scenes), navigated toward that scene's own two `tier1_locate` target
objects so they're genuinely in view (matching how the real benchmark
captures a frame, not a synthetic image). Each frame is queried with a
SINGLE joint prompt containing:
  - This scene's own 2 tier1_locate objects (true positives, IF
    AI2-THOR's own `visible` metadata confirms them in view from this
    exact vantage -- not just "present in the scene").
  - 2 objects native to a DIFFERENT scene, confirmed ABSENT from this
    scene's live metadata (true negatives) -- this is the part the
    original finding never measured.

One real forward pass per scene, at a very low threshold (0.05) to
capture every candidate box GroundingDINO considers at all; every
higher threshold (0.15, 0.20, 0.25, 0.35) is then evaluated by
re-filtering that SAME raw output -- real data, not four separate
(and four times slower) re-runs.

A detection "hits" an object name if any returned box's `text_labels`
entry matches that name at or above the threshold being evaluated.
True positive = a ground-truth-visible object's name is hit. False
positive = a confirmed-absent object's name is hit. False negative = a
ground-truth-visible object's name is NOT hit.

How to run
-----------
    cd backend
    PYTHONPATH=. python planning_evaluation/validate_detection_threshold.py
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import torch
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

from config.model_config import GROUNDING_DINO, get_device
from config.model_manager import ModelManager
from planning_evaluation.loader import load_tasks
from simulator.simulator import Simulator

RAW_THRESHOLD = 0.05
EVAL_THRESHOLDS = [0.15, 0.20, 0.25, 0.30, 0.35]


@dataclass
class SceneCase:
    scene: str
    positive_objects: List[str]
    negative_objects: List[str]


@dataclass
class RawHit:
    label: str
    score: float


@dataclass
class SceneResult:
    scene: str
    ground_truth_visible: List[str]
    ground_truth_absent_confirmed: List[str]
    raw_hits: List[RawHit] = field(default_factory=list)


def _build_scene_cases() -> List[SceneCase]:
    tasks = load_tasks(version="1.1")
    by_scene: Dict[str, List[str]] = {}
    for t in tasks:
        if t.difficulty_tier == "tier1_locate" and t.object:
            by_scene.setdefault(t.scene, []).append(t.object)

    scenes = list(by_scene.keys())
    cases = []
    for i, scene in enumerate(scenes):
        # Cyclic pairing: this scene's negatives are the NEXT scene's
        # own tier1_locate objects (confirmed absent below, at capture
        # time, from live metadata -- not just assumed from authoring).
        other_scene = scenes[(i + 1) % len(scenes)]
        cases.append(
            SceneCase(
                scene=scene,
                positive_objects=by_scene[scene],
                negative_objects=by_scene[other_scene],
            )
        )
    return cases


def _object_id_for_type(metadata, object_type: str) -> Optional[str]:
    normalized = object_type.strip().lower()
    for obj in metadata["objects"]:
        if obj["objectType"].strip().lower() == normalized:
            return obj["objectId"]
    return None


def _is_visible(metadata, object_type: str) -> bool:
    normalized = object_type.strip().lower()
    return any(
        obj["objectType"].strip().lower() == normalized and obj.get("visible")
        for obj in metadata["objects"]
    )


def _is_present(metadata, object_type: str) -> bool:
    normalized = object_type.strip().lower()
    return any(
        obj["objectType"].strip().lower() == normalized for obj in metadata["objects"]
    )


def _capture_scene(case: SceneCase, processor, model, device) -> Optional[SceneResult]:
    simulator = Simulator(scene=case.scene)
    simulator.start()
    try:
        metadata = simulator.get_metadata()
        # Try each of this scene's positive objects in turn until one
        # actually ends up visible from the resulting vantage -- the
        # first candidate's `navigate_to` pose doesn't always put a
        # *different* object in frame too, so don't give up on the
        # whole scene just because the first choice's vantage missed.
        ground_truth_visible: List[str] = []
        for candidate in case.positive_objects:
            target_id = _object_id_for_type(metadata, candidate)
            if target_id is not None:
                simulator.navigate_to(target_id)
            metadata = simulator.get_metadata()
            ground_truth_visible = [
                obj for obj in case.positive_objects if _is_visible(metadata, obj)
            ]
            if ground_truth_visible:
                break
        confirmed_absent = [
            obj for obj in case.negative_objects if not _is_present(metadata, obj)
        ]
        if not ground_truth_visible:
            print(
                f"  [skip] {case.scene}: no positive object confirmed visible "
                f"from this vantage (candidates: {case.positive_objects})"
            )
            return None
        if not confirmed_absent:
            print(
                f"  [skip] {case.scene}: no negative object confirmed absent "
                f"(candidates: {case.negative_objects} unexpectedly present)"
            )
            return None

        image = simulator.get_rgb().copy()
        all_names = ground_truth_visible + confirmed_absent
        prompt = ". ".join(all_names) + "."

        inputs = processor(images=image, text=prompt, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        results = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=RAW_THRESHOLD,
            text_threshold=RAW_THRESHOLD,
            target_sizes=[image.shape[:2]],
        )[0]

        raw_hits = [
            RawHit(label=label.strip().lower(), score=float(score))
            for score, label in zip(results["scores"], results["text_labels"])
        ]
        return SceneResult(
            scene=case.scene,
            ground_truth_visible=ground_truth_visible,
            ground_truth_absent_confirmed=confirmed_absent,
            raw_hits=raw_hits,
        )
    finally:
        simulator.stop()


def _normalize_label(label: str) -> str:
    """Strips whitespace and WordPiece `##` continuation markers so a
    raw label like `"laptopclock"` or `"##clock cellphone"` becomes a
    plain concatenated string safe for substring matching. See
    `_hit_at_threshold`'s docstring for why this, not exact equality,
    is the right comparison here."""
    return label.replace("##", "").replace(" ", "")


def _hit_at_threshold(raw_hits: List[RawHit], name: str, threshold: float) -> bool:
    """
    `name` counts as hit if it appears as a substring of a
    (whitespace/`##`-stripped) raw label -- NOT exact string equality.
    Grounding DINO's `post_process_grounded_object_detection`
    sometimes merges two adjacent short phrases from a `". "`-joined
    prompt into one returned span (e.g. `"bowl laptop"` for a single
    box when both are in the prompt), or splits one word across a
    WordPiece boundary (e.g. `"##clock"` for part of "alarmclock") --
    exact-match would silently miss all of those, undercounting both
    TPs and FPs. Substring containment on the normalized label catches
    the real signal (`"laptop" in "bowllaptop"`) while still correctly
    rejecting a weak partial fragment as evidence for a *longer* name
    it can't contain (`"alarmclock" not in "clock"` -- the fragment is
    shorter than the name being checked, so it can never be a
    substring match).
    """
    normalized = name.strip().lower()
    return any(
        normalized in _normalize_label(h.label) and h.score >= threshold
        for h in raw_hits
    )


def main():
    manager = ModelManager(GROUNDING_DINO)
    device = get_device()
    processor, model = manager.load(
        AutoProcessor, AutoModelForZeroShotObjectDetection, device=device
    )

    cases = _build_scene_cases()
    results: List[SceneResult] = []
    for case in cases:
        print(f"\n--- {case.scene} ---")
        result = _capture_scene(case, processor, model, device)
        if result is not None:
            print(
                f"  ground_truth_visible={result.ground_truth_visible} "
                f"confirmed_absent={result.ground_truth_absent_confirmed}"
            )
            print(f"  raw_hits(>= {RAW_THRESHOLD})={result.raw_hits}")
            results.append(result)

    print(
        f"\n{'=' * 70}\nPrecision/recall by threshold ({len(results)} scenes)\n{'=' * 70}"
    )
    for threshold in EVAL_THRESHOLDS:
        tp = fn = fp = tn = 0
        for r in results:
            for name in r.ground_truth_visible:
                if _hit_at_threshold(r.raw_hits, name, threshold):
                    tp += 1
                else:
                    fn += 1
            for name in r.ground_truth_absent_confirmed:
                if _hit_at_threshold(r.raw_hits, name, threshold):
                    fp += 1
                else:
                    tn += 1

        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        print(
            f"threshold={threshold:.2f}  TP={tp} FN={fn} FP={fp} TN={tn}  "
            f"precision={precision:.3f} recall={recall:.3f}"
        )


if __name__ == "__main__":
    main()
