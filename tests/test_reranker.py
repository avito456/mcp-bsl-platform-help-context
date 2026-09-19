"""Tests for Reranker abstraction and factory."""

import httpx
import pytest

from mcp_bsl_context.config import RerankerConfig
from mcp_bsl_context.infrastructure.embeddings.reranker import (
    LocalReranker,
    OpenAICompatibleReranker,
    RankedResult,
    Reranker,
    create_reranker,
)


class TestRerankerInterface:
    def test_abc_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            Reranker()


class TestRankedResult:
    def test_frozen_dataclass(self):
        r = RankedResult(index=0, score=0.95, text="test")
        assert r.index == 0
        assert r.score == 0.95
        assert r.text == "test"
        with pytest.raises(AttributeError):
            r.score = 0.5


class TestOpenAICompatibleReranker:
    def test_stores_config(self):
        reranker = OpenAICompatibleReranker(
            api_url="http://localhost:8080/v1",
            model="test-reranker",
            api_key="key123",
        )
        assert reranker._api_url == "http://localhost:8080/v1"
        assert reranker._model == "test-reranker"
        assert reranker._api_key == "key123"

    def test_empty_documents_returns_empty(self):
        reranker = OpenAICompatibleReranker(
            api_url="http://localhost:8080/v1",
            model="test",
        )
        result = reranker.rerank("query", [], top_k=5)
        assert result == []

    def test_malformed_items_are_skipped(self):
        """Items missing 'index' or out of range must not crash the reranker."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"relevance_score": 0.9},  # no index -> skipped
                        {"index": 5, "relevance_score": 0.8},  # out of range -> skipped
                        {"index": 1, "relevance_score": 0.7},
                        {"index": 0, "score": 0.6},  # legacy 'score' field
                    ]
                },
            )

        transport = httpx.MockTransport(handler)
        reranker = OpenAICompatibleReranker(
            api_url="http://localhost:8080/v1", model="test"
        )
        from unittest.mock import patch

        with httpx.Client(transport=transport) as client:
            def fake_post(url, json=None, headers=None, timeout=None):
                return client.post(url, json=json)

            with patch.object(httpx, "post", side_effect=fake_post):
                result = reranker.rerank("q", ["docA", "docB"], top_k=5)

        assert [r.index for r in result] == [1, 0]
        assert [r.text for r in result] == ["docB", "docA"]


class TestLocalRerankerImport:
    def test_requires_sentence_transformers(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError("No module named 'sentence_transformers'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="sentence-transformers"):
            LocalReranker()


class TestCreateReranker:
    def test_disabled_returns_none(self):
        config = RerankerConfig(enabled=False)
        assert create_reranker(config) is None

    def test_api_requires_url(self):
        config = RerankerConfig(
            enabled=True, provider="openai-compatible", api_url=None
        )
        with pytest.raises(ValueError, match="api_url is required"):
            create_reranker(config)

    def test_api_creates_reranker(self):
        config = RerankerConfig(
            enabled=True,
            provider="openai-compatible",
            model="test-model",
            api_url="http://localhost:8080/v1",
        )
        reranker = create_reranker(config)
        assert isinstance(reranker, OpenAICompatibleReranker)

    def test_unknown_provider_raises(self):
        config = RerankerConfig(enabled=True, provider="unknown")
        with pytest.raises(ValueError, match="Unknown reranker provider"):
            create_reranker(config)
