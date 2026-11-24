"""
config.py (backend/learning)

Flags for every learned component. All default to OFF, and every one falls
back to today's rule-based behaviour if its model is missing or fails.

    MILO_LEARNED_REFLECTOR = off | shadow | on     (default off)
    MILO_PLAN_RANKING      = 0 | 1                  (default 0)
    MILO_WORLD_MODEL       = 0 | 1                  (default 0; needs MILO_PLAN_RANKING=1:
                             score plans by rolling a learned transition model forward)
    MILO_WORLD_MODEL_PATH  = artifacts/worldmodel/world.pkl
    MILO_MODEL_DIR         = directory of trained outcome-predictor versions
                             (default: artifacts/outcome)

`learning_kwargs()` returns the extra `Orchestrator(...)` keyword arguments.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from agents.reflection_agent import ReflectionAgent
from learning.ranker import PlanRanker
from learning.reflector import LearnedReflector
from learning.serving import load_predictor

logger = logging.getLogger(__name__)

REFLECTOR_MODES = ("off", "shadow", "on")


def reflector_mode(env: Optional[Mapping[str, str]] = None) -> str:
    value = (env or os.environ).get("MILO_LEARNED_REFLECTOR", "off").strip().lower()
    return value if value in REFLECTOR_MODES else "off"


def ranking_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    return (env or os.environ).get("MILO_PLAN_RANKING", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def model_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return Path((env or os.environ).get("MILO_MODEL_DIR", "artifacts/outcome"))


def learning_kwargs(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Orchestrator kwargs for the enabled learned components (`{}` when none)."""
    mode, ranking = reflector_mode(env), ranking_enabled(env)
    if mode == "off" and not ranking:
        return {}
    predictor = load_predictor(model_dir(env))
    if predictor is None:
        logger.warning("learning.model_missing -- falling back to rule-based behaviour")
        return {}
    kwargs: Dict[str, Any] = {"outcome_predictor": predictor}
    if mode != "off":
        kwargs["reflection_agent"] = LearnedReflector(
            ReflectionAgent(), predictor, mode=mode
        )
    if ranking:
        world = None
        if os.environ.get("MILO_WORLD_MODEL", "0").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            from learning.worldmodel import WorldModel

            world = WorldModel.load(
                Path(
                    os.environ.get(
                        "MILO_WORLD_MODEL_PATH", "artifacts/worldmodel/world.pkl"
                    )
                )
            )
        kwargs["plan_ranker"] = PlanRanker(predictor, world_model=world)
    return kwargs


def set_reflector_mode(
    orchestrator: Any, mode: str, env: Optional[Mapping[str, str]] = None
) -> Dict[str, Any]:
    """Switch the learned reflector at runtime (the Lab toggle). `off` restores the
    plain rule-based reflector; the model is loaded on demand and, if missing, the
    mode stays `off` with a plain reason."""
    if mode not in REFLECTOR_MODES:
        raise ValueError(f"mode must be one of {REFLECTOR_MODES}")
    current = orchestrator._reflection
    if mode == "off":
        if isinstance(current, LearnedReflector):
            orchestrator._reflection = current._base
        return {"mode": "off", "reason": None}
    if isinstance(current, LearnedReflector):
        current.mode = mode
        return {"mode": mode, "reason": None}
    predictor = orchestrator._predictor or load_predictor(model_dir(env))
    if predictor is None:
        return {
            "mode": "off",
            "reason": "No trained model found, so MILO keeps using its built-in rules.",
        }
    orchestrator._predictor = predictor
    orchestrator._reflection = LearnedReflector(current, predictor, mode=mode)
    return {"mode": mode, "reason": None}


def models_status(
    orchestrator: Any, env: Optional[Mapping[str, str]] = None
) -> Dict[str, Any]:
    """What the Lab's Models panel shows."""
    import json

    registry = model_dir(env).parent / "registry.json"
    entries = json.loads(registry.read_text())["models"] if registry.exists() else []
    latest = entries[-1] if entries else None
    reflector = (
        getattr(orchestrator, "_reflection", None) if orchestrator is not None else None
    )
    predictor = (
        getattr(orchestrator, "_predictor", None) if orchestrator is not None else None
    )
    return {
        "models": [
            {
                "name": "outcome_predictor",
                "title": "Step outcome predictor",
                "available": latest is not None,
                "version": (
                    predictor.version if predictor else (latest or {}).get("version")
                ),
                "mode": (
                    reflector.mode if isinstance(reflector, LearnedReflector) else "off"
                ),
                "metrics": (latest or {}).get("metrics"),
                "trained_on": (latest or {}).get("train_steps"),
                "date": (latest or {}).get("date"),
                "shadow": (
                    reflector.stats if isinstance(reflector, LearnedReflector) else None
                ),
                "latency": predictor.latency_summary() if predictor else None,
                "drift_score": predictor.drift_score if predictor else None,
                "healthy": predictor.usable if predictor else None,
                "problem": (
                    (
                        predictor.disabled_reason
                        or (
                            "inputs look different from the training data"
                            if predictor.drifted
                            else None
                        )
                    )
                    if predictor
                    else None
                ),
                "explains": "Off: MILO uses its built-in rules. Shadow: the model watches and logs what it would do. On: the model chooses retry, replan or stop; if it is missing, slow, unsure or the inputs drift, MILO falls back to the rules.",
            }
        ]
    }
