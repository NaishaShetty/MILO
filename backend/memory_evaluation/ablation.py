"""
ablation.py (backend/memory_evaluation)

Purpose
-------
The four `RankingWeights` configurations the phase spec's section 21
asks for -- "A. vector similarity only," "B. + confidence," "C. + +
recency," "D. full hybrid" -- expressed by zeroing out the weights not
yet "added" at each stage, keeping every other `RankingWeights` field
(recency half-life, provenance scores, similarity threshold, candidate
pool sizing) identical across configs so latency/quality differences
are attributable to the ranking formula alone, not incidental
configuration drift between ablation arms.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict

from memory.retrieval import RankingWeights

_BASE = RankingWeights()

#: A: vector similarity only -- every other weight zeroed, so
#: `final_score` reduces to `similarity` alone (see `RetrievalEngine
#: ._score`'s `total_weight` normalization).
VECTOR_ONLY = replace(_BASE, confidence=0.0, recency=0.0, provenance=0.0, context=0.0)

#: B: + confidence.
SIMILARITY_CONFIDENCE = replace(_BASE, recency=0.0, provenance=0.0, context=0.0)

#: C: + recency.
SIMILARITY_CONFIDENCE_RECENCY = replace(_BASE, provenance=0.0, context=0.0)

#: D: full hybrid -- every component `RetrievalEngine` supports,
#: unmodified defaults.
FULL_HYBRID = _BASE

ABLATION_CONFIGS: Dict[str, RankingWeights] = {
    "A_vector_only": VECTOR_ONLY,
    "B_similarity_confidence": SIMILARITY_CONFIDENCE,
    "C_similarity_confidence_recency": SIMILARITY_CONFIDENCE_RECENCY,
    "D_full_hybrid": FULL_HYBRID,
}
