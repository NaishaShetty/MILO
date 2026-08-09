"""
test_memory_embeddings.py

Purpose
-------
Tests for `memory.embeddings` -- Phase 6.2 spec section 19's
"Embedding tests": deterministic representation, correct dimensions,
batch embedding, configuration, and failure handling.
"""

from __future__ import annotations

import pytest

from memory.embeddings import Embedder, EmbeddingConfig, HashingEmbedder, get_embedder


class TestDeterminism:
    def test_same_text_embeds_identically_across_instances(self):
        a = HashingEmbedder(dimension=64).embed("red mug on the table")
        b = HashingEmbedder(dimension=64).embed("red mug on the table")
        assert a == b

    def test_different_text_embeds_differently(self):
        embedder = HashingEmbedder(dimension=64)
        a = embedder.embed("red mug on the table")
        b = embedder.embed("refrigerator in the kitchen")
        assert a != b

    def test_embedding_is_deterministic_regardless_of_call_order(self):
        embedder = HashingEmbedder(dimension=64)
        first = embedder.embed("apple")
        embedder.embed("some other unrelated text")
        second = embedder.embed("apple")
        assert first == second


class TestDimensions:
    @pytest.mark.parametrize("dimension", [8, 64, 256, 512])
    def test_embed_returns_exactly_dimension_components(self, dimension):
        embedder = HashingEmbedder(dimension=dimension)
        vector = embedder.embed("some text")
        assert len(vector) == dimension
        assert embedder.dimension == dimension

    def test_zero_dimension_rejected(self):
        with pytest.raises(ValueError):
            HashingEmbedder(dimension=0)

    def test_negative_dimension_rejected(self):
        with pytest.raises(ValueError):
            HashingEmbedder(dimension=-8)


class TestNormalization:
    def test_nonempty_text_embeds_to_unit_norm(self):
        embedder = HashingEmbedder(dimension=64)
        vector = embedder.embed("red mug on the dining table")
        norm = sum(c * c for c in vector) ** 0.5
        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_empty_text_embeds_to_zero_vector(self):
        embedder = HashingEmbedder(dimension=32)
        vector = embedder.embed("")
        assert vector == [0.0] * 32

    def test_whitespace_only_text_embeds_to_zero_vector(self):
        embedder = HashingEmbedder(dimension=32)
        vector = embedder.embed("   \t  ")
        assert vector == [0.0] * 32


class TestBatch:
    def test_embed_batch_matches_individual_embed_calls(self):
        embedder = HashingEmbedder(dimension=64)
        texts = ["red mug", "refrigerator", "apple in cabinet"]
        batch = embedder.embed_batch(texts)
        individual = [embedder.embed(t) for t in texts]
        assert batch == individual

    def test_embed_batch_empty_list(self):
        embedder = HashingEmbedder(dimension=64)
        assert embedder.embed_batch([]) == []


class TestConfiguration:
    def test_from_env_defaults(self, monkeypatch):
        monkeypatch.delenv("MEMORY_EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("MEMORY_EMBEDDING_DIMENSION", raising=False)
        config = EmbeddingConfig.from_env()
        assert config.provider == "hashing"
        assert config.dimension == 512

    def test_from_env_overrides(self, monkeypatch):
        monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "hashing")
        monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSION", "128")
        config = EmbeddingConfig.from_env()
        assert config.dimension == 128

    def test_get_embedder_returns_hashing_embedder_for_hashing_provider(self):
        config = EmbeddingConfig(
            provider="hashing", dimension=64, model_name="", device="cpu"
        )
        embedder = get_embedder(config)
        assert isinstance(embedder, HashingEmbedder)
        assert isinstance(embedder, Embedder)
        assert embedder.dimension == 64


class TestFailureHandling:
    def test_unsupported_provider_raises(self):
        config = EmbeddingConfig(
            provider="nonexistent_provider", dimension=64, model_name="", device="cpu"
        )
        with pytest.raises(ValueError):
            get_embedder(config)

    def test_embedder_cannot_be_instantiated_directly(self):
        with pytest.raises(TypeError):
            Embedder()  # type: ignore[abstract]
