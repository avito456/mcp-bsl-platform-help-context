"""Tests for EmbeddingProvider abstraction and factory."""

import httpx
import pytest

from mcp_bsl_context.config import EmbeddingsConfig
from mcp_bsl_context.infrastructure.embeddings.provider import (
    EmbeddingProvider,
    LocalEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    create_embedding_provider,
)


class TestEmbeddingProviderInterface:
    def test_abc_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            EmbeddingProvider()

    def test_local_provider_requires_sentence_transformers(self, monkeypatch):
        """If sentence-transformers is not installed, ImportError is raised."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError("No module named 'sentence_transformers'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="sentence-transformers"):
            LocalEmbeddingProvider()


class TestOpenAICompatibleProvider:
    def test_stores_config(self):
        provider = OpenAICompatibleEmbeddingProvider(
            api_url="http://localhost:1234/v1",
            model="test-model",
            api_key="test-key",
        )
        assert provider._api_url == "http://localhost:1234/v1"
        assert provider._model == "test-model"
        assert provider._api_key == "test-key"

    def test_strips_trailing_slash(self):
        provider = OpenAICompatibleEmbeddingProvider(
            api_url="http://localhost:1234/v1/",
            model="test",
        )
        assert provider._api_url == "http://localhost:1234/v1"


class TestOpenAICompatibleProviderHttp:
    """HTTP behaviour via httpx.MockTransport: partial responses, ordering, retries."""

    @staticmethod
    def _provider(handler):
        transport = httpx.MockTransport(handler)
        provider = OpenAICompatibleEmbeddingProvider(
            api_url="http://test/v1", model="m"
        )
        provider._client = httpx.Client(transport=transport)
        return provider

    def test_returns_embeddings_in_request_order(self):
        def handler(request: httpx.Request) -> httpx.Response:
            payload = request.read().decode()
            assert '"input"' in payload
            # Deliberately shuffled by index; provider must re-sort
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.2, 0.2]},
                        {"index": 0, "embedding": [0.1, 0.1]},
                    ]
                },
            )

        provider = self._provider(handler)
        result = provider._post_embeddings(["a", "b"])
        assert result == [[0.1, 0.1], [0.2, 0.2]]

    def test_partial_response_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

        provider = self._provider(handler)
        with pytest.raises(RuntimeError, match="refusing partial index"):
            provider._post_embeddings(["a", "b", "c"])

    def test_empty_data_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        provider = self._provider(handler)
        with pytest.raises(RuntimeError):
            provider._post_embeddings(["a"])

    def test_retry_on_503_then_success(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503)
            return httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [0.7]}]}
            )

        provider = self._provider(handler)
        assert provider._post_embeddings(["a"]) == [[0.7]]
        assert calls["n"] == 2

    def test_exhausts_retries_and_raises(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503)

        provider = self._provider(handler)
        with pytest.raises(httpx.HTTPStatusError):
            provider._post_embeddings(["a"])
        assert calls["n"] == 3

    def test_sends_auth_header(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [0.0]}]}
            )

        from unittest.mock import patch

        real_client_cls = httpx.Client
        transport = httpx.MockTransport(handler)

        def make_client(*args, **kwargs):
            return real_client_cls(transport=transport, **kwargs)

        provider = OpenAICompatibleEmbeddingProvider(
            api_url="http://test/v1", model="m", api_key="k123"
        )
        with patch("httpx.Client", side_effect=make_client):
            provider._post_embeddings(["a"])
        assert seen["auth"] == "Bearer k123"


class TestCreateEmbeddingProvider:
    def test_factory_local_raises_without_deps(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError("No module named 'sentence_transformers'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        config = EmbeddingsConfig(provider="local")
        with pytest.raises(ImportError):
            create_embedding_provider(config)

    def test_factory_api_requires_url(self):
        config = EmbeddingsConfig(provider="openai-compatible", api_url=None)
        with pytest.raises(ValueError, match="api_url is required"):
            create_embedding_provider(config)

    def test_factory_api_creates_provider(self):
        config = EmbeddingsConfig(
            provider="openai-compatible",
            model="test-model",
            api_url="http://localhost:1234/v1",
            api_key="key",
        )
        provider = create_embedding_provider(config)
        assert isinstance(provider, OpenAICompatibleEmbeddingProvider)

    def test_factory_unknown_provider_raises(self):
        config = EmbeddingsConfig(provider="unknown")
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            create_embedding_provider(config)


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    """Install a fake 'sentence_transformers' module (import happens in __init__)."""
    import sys
    import types

    class FakeST:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def get_sentence_embedding_dimension(self):
            return 384

        def encode(self, texts, **kwargs):
            import numpy as np

            if isinstance(texts, str):
                texts = [texts]
            return np.zeros((len(texts), 384), dtype="float32")

    mod = types.ModuleType("sentence_transformers")
    mod.SentenceTransformer = FakeST
    monkeypatch.setitem(sys.modules, "sentence_transformers", mod)
    return FakeST


class TestLocalEmbeddingProviderDevice:
    def test_default_device_is_cpu(self, fake_sentence_transformers):
        provider = LocalEmbeddingProvider(model_name="test-model")
        assert provider._model.kwargs["device"] == "cpu"

    def test_factory_forwards_device(self, fake_sentence_transformers):
        config = EmbeddingsConfig(provider="local", device="mps")
        provider = create_embedding_provider(config)
        assert provider._model.kwargs["device"] == "mps"
        assert provider._model.args[0] == config.model

    def test_embedding_uses_model(self, fake_sentence_transformers):
        provider = LocalEmbeddingProvider(model_name="test-model")
        result = provider.embed_query("привет")
        assert len(result) == 1
        assert len(result[0]) == 384
