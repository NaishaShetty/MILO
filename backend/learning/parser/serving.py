"""
serving.py (backend/learning/parser)

Adapter between the small parser and `InstructionInterpreter`. Off by default.

    MILO_LEARNED_PARSER=1            enable
    MILO_PARSER_DIR=artifacts/parser directory holding parser.pkl
    MILO_PARSER_THRESHOLD=0.7        minimum confidence to act on a parse

`build_learned_parser()` returns `None` (feature off, or the model cannot be loaded) or a
callable `text -> SingleTask | None`. The callable never raises and returns `None`
whenever it is unsure or a slot the goal needs is missing, so the interpreter simply
carries on with its phrasebook / the LLM.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from schemas.task import SingleTask

logger = logging.getLogger(__name__)
LearnedParser = Callable[[str], Optional[SingleTask]]


def enabled() -> bool:
    return os.environ.get("MILO_LEARNED_PARSER", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def build_learned_parser() -> Optional[LearnedParser]:
    if not enabled():
        return None
    from learning.parser.model import NEEDS_OBJ, NEEDS_TGT, SmallParser

    model = SmallParser.load(
        Path(os.environ.get("MILO_PARSER_DIR", "artifacts/parser")) / "parser.pkl"
    )
    if model is None:
        logger.warning("learned_parser.load_failed; using the phrasebook only")
        return None
    try:
        threshold = float(os.environ.get("MILO_PARSER_THRESHOLD", "0.7"))
    except ValueError:
        threshold = 0.7

    def parse(text: str) -> Optional[SingleTask]:
        try:
            p = model.parse(text)
            if p.confidence < threshold:
                return None
            if (p.goal in NEEDS_OBJ and not p.object) or (
                p.goal in NEEDS_TGT and not p.target
            ):
                return None
            if p.goal == "clear_table":
                return SingleTask(
                    goal=p.goal, source_location=p.object, target_location=p.target
                )
            return SingleTask(goal=p.goal, object=p.object, target=p.target)
        except Exception:
            logger.warning("learned_parser.parse_failed", exc_info=True)
            return None

    return parse
