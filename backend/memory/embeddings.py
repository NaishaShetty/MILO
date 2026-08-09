"""
embeddings.py (backend/memory)

Purpose
-------
The embedding layer for semantic memory retrieval: an `Embedder`
interface (`embed`/`embed_batch`/`dimension`), one concrete,
deterministic, fully-offline implementation (`HashingEmbedder`), and an
env-driven `EmbeddingConfig` + `get_embedder()` factory -- mirroring
`language/config.py` + `language/provider_factory.py`'s "config picks a
provider string, a factory maps it to a concrete client" pattern
exactly.

Why the default (and only, as of Phase 6.2) provider is a hashing
embedder, not a transformer/sentence-embedding model
------------------------------------------------------------------------
This project already depends on `transformers`/`torch` (Vision), so a
learned sentence-embedding model is not a hypothetical future
dependency -- it is a legitimate next provider. It is deliberately not
implemented yet: every retrieval test in this package must run
deterministically, offline, and fast (no model download, no GPU, no
network) exactly like every other test in this repository's suite (see
`test_language_*.py`'s "LLM mocked" convention and
`vision_evaluation`'s "synthetic, no GPU" convention) -- a network- or
weights-dependent embedder would silently break that invariant for the
entire memory test suite. `HashingEmbedder` is a real, self-consistent
embedding: it uses the classic
[feature-hashing](https://en.wikipedia.org/wiki/Feature-hashing) trick
(hash each token to a dimension index + sign, accumulate, L2-normalize)
over word tokens and character trigrams, which does capture
lexical/substring similarity (memories sharing words score higher) even
though it captures no semantic/synonym similarity a learned model
would. `Embedder` is the seam a future `SentenceTransformerEmbedder`
plugs into (one more `elif` in `get_embedder()`, matching
`provider_factory.create_llm_client()`'s own extension story) without
any change to `retrieval.py` or anything built on top of it.

Why hashing (`hashlib.blake2b`), not Python's builtin `hash()`
--------------------------------------------------------------------
`hash()` is randomized per-process for `str` (via `PYTHONHASHSEED`) --
the exact same text would embed to a *different* vector in two
different process runs, breaking "deterministic," "reproducible," and
persistence-across-restart all at once. `blake2b` is a fixed,
seedless, cross-process-stable digest, so the same text always
produces the same embedding, in this process or any other.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Sequence

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class Embedder(ABC):
    """
    The interface every embedding provider implements. `MemoryManager`/
    `RetrievalEngine` never depend on a concrete provider -- only on
    this interface, mirroring `memory.store.MemoryStore`'s role for
    persistence.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """The fixed length of every vector this embedder produces."""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Embeds one string. Deterministic: same text -> same vector."""

    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        """
        Embeds many strings. The default implementation simply maps
        `embed()` over `texts` -- correct for any provider, and the
        only option for `HashingEmbedder` (each text embeds
        independently, so there is no batching speedup to have). A
        future provider backed by a real batched model (e.g. a
        transformer run through a single forward pass over the whole
        batch) overrides this method for actual throughput gains;
        `retrieval.py` always calls `embed_batch()` for multi-text
        work so that speedup is transparent whenever it exists.
        """
        return [self.embed(text) for text in texts]


def _tokenize(text: str) -> List[str]:
    """
    Lowercases and extracts alphanumeric word tokens, per the
    docstring's "word tokens" half of the hashing scheme.
    """
    return _TOKEN_PATTERN.findall(text.lower())


def _char_trigrams(token: str) -> List[str]:
    """
    Character trigrams of one token (padded with boundary markers so
    short tokens still produce at least one trigram) -- the "character
    trigrams" half of the hashing scheme, giving the embedder partial
    credit for substring/typo-level overlap a pure word-token scheme
    would miss entirely (e.g. "mug"/"mugs").
    """
    padded = f"^{token}$"
    if len(padded) < 3:
        return [padded]
    return [padded[i : i + 3] for i in range(len(padded) - 2)]


def _hashed_index_and_sign(feature: str, dimension: int) -> tuple:
    """
    Maps one feature string to `(index, sign)` via `blake2b` --
    signed hashing (Weinberger et al., 2009) so colliding features
    partially cancel instead of purely accumulating, keeping the
    resulting vector's variance closer to what an unhashed
    bag-of-features vector would have.
    """
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, byteorder="big")
    index = value % dimension
    sign = 1.0 if (value >> 63) & 1 == 0 else -1.0
    return index, sign


class HashingEmbedder(Embedder):
    """
    Deterministic, offline, dependency-free `Embedder` -- see this
    module's docstring for the full rationale. `dimension` is fixed at
    construction; every vector this embedder produces has exactly that
    length and unit L2 norm (so cosine similarity between two of its
    vectors reduces to a plain dot product -- `sqlite_vector_store.py`
    relies on this).

    Default `dimension=512`: measured empirically against
    `backend/memory_evaluation/dataset.py` (`run_evaluation.py`'s
    dimension ablation) -- 256 dimensions produced visibly more
    hash-collision noise for this project's longer failure/episodic
    texts (more tokens hashed into the same vector -> more incidental
    overlap with an unrelated query), lowering Recall@1; 512 reduces
    that noise substantially for a negligible speed cost at this
    project's memory-count scale. Not re-tuned per deployment --
    override via `MEMORY_EMBEDDING_DIMENSION` if a specific
    corpus/query mix benefits from a different value.
    """

    def __init__(self, dimension: int = 512) -> None:
        if dimension <= 0:
            raise ValueError(f"dimension must be positive, got {dimension}")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> List[float]:
        vector = [0.0] * self._dimension
        tokens = _tokenize(text)
        features: List[str] = list(tokens)
        for token in tokens:
            features.extend(_char_trigrams(token))

        for feature in features:
            index, sign = _hashed_index_and_sign(feature, self._dimension)
            vector[index] += sign

        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0.0:
            # Empty/whitespace-only text (or, astronomically unlikely,
            # perfect cancellation) -- return the zero vector rather
            # than dividing by zero. A zero vector has zero cosine
            # similarity with everything, which is the correct
            # behavior for "nothing to embed."
            return vector
        return [component / norm for component in vector]


@dataclass(frozen=True)
class EmbeddingConfig:
    """
    Deployment-level embedding configuration -- matches `memory.
    config.MemoryConfig`'s frozen-dataclass-with-`from_env()`
    convention. `model_name`/`device` are read and validated now (so a
    future transformer-backed provider needs no config-layer change)
    even though `HashingEmbedder` (the only provider implemented in
    Phase 6.2) ignores both.
    """

    #: Provider identifier -- `"hashing"` is the only value
    #: `get_embedder()` currently accepts. A plain string (not a closed
    #: enum), matching `LLMRuntimeConfig.provider`'s own precedent, so
    #: adding a provider is a `get_embedder()`/`.env.example` change,
    #: not a schema migration.
    provider: str
    #: Vector length every `Embedder` call produces. Must match
    #: whatever `SQLiteVectorStore` was created with -- `retrieval.py`
    #: is responsible for constructing both from the same config so
    #: they can never disagree.
    dimension: int
    #: Reserved for a future model-backed provider (e.g. a Hugging
    #: Face sentence-embedding model name/path, following `config.
    #: model_config.ModelConfig`'s "never the global HF cache, always
    #: project-local" convention). Unused by `HashingEmbedder`.
    model_name: str
    #: Reserved for a future model-backed provider -- `"cpu"` or
    #: `"cuda"`, matching `config.model_config.get_device()`'s
    #: vocabulary. Unused by `HashingEmbedder`.
    device: str

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        return cls(
            provider=os.environ.get("MEMORY_EMBEDDING_PROVIDER", "hashing"),
            dimension=int(os.environ.get("MEMORY_EMBEDDING_DIMENSION", "512")),
            model_name=os.environ.get("MEMORY_EMBEDDING_MODEL_NAME", ""),
            device=os.environ.get("MEMORY_EMBEDDING_DEVICE", "cpu"),
        )


_SUPPORTED_PROVIDERS = ("hashing",)


def get_embedder(config: EmbeddingConfig) -> Embedder:
    """
    Constructs the `Embedder` implementation matching `config.
    provider` -- the single place that knows the mapping, matching
    `provider_factory.create_llm_client()`. Raises `ValueError` for an
    unrecognized provider name rather than silently falling back to
    hashing, since a deployment that thinks it configured a different
    embedding provider must never silently retrieve against vectors
    from the wrong one.
    """
    if config.provider == "hashing":
        return HashingEmbedder(dimension=config.dimension)
    raise ValueError(
        f"Unsupported embedding provider {config.provider!r} (configured via "
        f"MEMORY_EMBEDDING_PROVIDER). Supported providers: "
        f"{', '.join(_SUPPORTED_PROVIDERS)}."
    )
