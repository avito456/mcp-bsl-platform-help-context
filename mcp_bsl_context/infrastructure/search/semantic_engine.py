"""Semantic search engine using Qdrant vector database."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from mcp_bsl_context.domain.entities import Definition
from mcp_bsl_context.infrastructure.embeddings.document_builder import DocumentBuilder
from mcp_bsl_context.infrastructure.embeddings.provider import EmbeddingProvider
from mcp_bsl_context.infrastructure.embeddings.reranker import Reranker

if TYPE_CHECKING:
    from mcp_bsl_context.infrastructure.storage.storage import PlatformContextStorage

from mcp_bsl_context.logging_setup import get_logger

logger = get_logger(__name__)

COLLECTION_NAME = "platform_context"
UPSERT_BATCH_SIZE = 100
FINGERPRINT_FILE = "index-fingerprint.json"
# Bumped again (embed-text now includes parameter types in DocumentBuilder).
_FINGERPRINT_NAMESPACE = uuid.UUID("c1e7a9f3-5b8d-4e2a-9c04-1f6b2d3e4a55")
# How many more candidates to fetch than requested so the reranker has room.
SEMANTIC_FETCH_MULTIPLIER = 3


class SemanticSearchEngine:
    """Vector-based search using embeddings + Qdrant + optional reranker.

    Lifecycle:
      1. ``ensure_ready(storage)`` — builds lookup dict, creates index if missing.
      2. ``search(query, storage, ...)`` — embed query → Qdrant ANN → rerank → Definitions.

    The Qdrant collection is persisted on disk (``qdrant_path``) and reused across
    restarts.  The in-memory lookup dict is rebuilt from storage on each startup.
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        qdrant_path: str,
        reranker: Reranker | None = None,
    ) -> None:
        from qdrant_client import QdrantClient

        self._embedder = embedding_provider
        self._reranker = reranker
        self._qdrant_path = qdrant_path
        self._client = QdrantClient(path=qdrant_path)
        self._builder = DocumentBuilder()
        self._lookup: dict[tuple[str, str, str], Definition] = {}
        self._ready = False
        self._lock = threading.Lock()

    def ensure_ready(
        self,
        storage: PlatformContextStorage,
        force_reindex: bool = False,
    ) -> None:
        """Prepare the engine: build lookup dict and index if needed.

        The vector index carries a fingerprint derived from the platform content.
        If the underlying data changes (new platform version, different HBK),
        the fingerprint no longer matches and the index is rebuilt automatically.

        Args:
            storage: Loaded platform context storage.
            force_reindex: If True, rebuild the vector index from scratch.
        """
        if self._ready and not force_reindex:
            return
        with self._lock:
            if self._ready and not force_reindex:
                return
            storage.ensure_loaded()
            self._build_lookup(storage)
            fingerprint = self._compute_fingerprint()
            if (
                force_reindex
                or fingerprint != self._read_fingerprint()
                or not self._has_collection()
            ):
                self._build_index(storage)
                self._write_fingerprint(fingerprint)
            self._ready = True

    def search(
        self,
        query: str,
        storage: PlatformContextStorage,
        limit: int = 10,
        type_filter: str | None = None,
        rerank: bool = True,
    ) -> list[Definition]:
        """Semantic search: embed query -> Qdrant ANN -> optional rerank.

        Args:
            query: Natural-language search query.
            storage: Platform context storage (for lazy init).
            limit: Maximum results to return.
            type_filter: Optional filter by api_type ("method"/"property"/"type").
            rerank: If True (and a reranker is configured), reorder the ANN
                results with the cross-encoder before returning.  The hybrid
                engine passes False here — it fetches the raw ANN ranking and
                applies a single rerank on the merged pool instead, so keyword
                and semantic evidence are combined before ranking.

        Returns:
            Ordered list of Definition objects (most relevant first).
        """
        self.ensure_ready(storage)

        use_rerank = self._reranker is not None and rerank
        search_limit = limit * SEMANTIC_FETCH_MULTIPLIER if use_rerank else limit
        query_vector = self._embedder.embed_query(query)

        qdrant_filter = None
        if type_filter:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            qdrant_filter = Filter(
                must=[
                    FieldCondition(
                        key="api_type", match=MatchValue(value=type_filter)
                    )
                ]
            )

        response = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=search_limit,
            query_filter=qdrant_filter,
        )
        results = response.points

        if not results:
            return []

        # Rerank candidates if reranker is available (and requested)
        if use_rerank and len(results) > 1:
            texts = [hit.payload.get("text", "") for hit in results]
            reranked = self._reranker.rerank(query, texts, top_k=limit)
            definitions: list[Definition] = []
            for ranked in reranked:
                payload = results[ranked.index].payload
                defn = self._resolve_definition(payload)
                if defn is not None and not any(d is defn for d in definitions):
                    definitions.append(defn)
            return definitions[:limit]

        # Without reranker — map Qdrant results directly
        definitions: list[Definition] = []
        for hit in results[:limit]:
            defn = self._resolve_definition(hit.payload)
            if defn is not None and not any(d is defn for d in definitions):
                definitions.append(defn)
        return definitions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _has_collection(self) -> bool:
        """Check if the Qdrant collection exists and contains points."""
        try:
            collections = self._client.get_collections().collections
        except Exception:
            logger.exception("Failed to list Qdrant collections")
            return False
        for col in collections:
            if col.name == COLLECTION_NAME:
                try:
                    info = self._client.get_collection(COLLECTION_NAME)
                except Exception:
                    logger.exception(
                        "Failed to inspect collection '{}'", COLLECTION_NAME
                    )
                    return False
                return info.points_count > 0
        return False

    def _compute_fingerprint(self) -> str:
        """Deterministic UUID5 fingerprint of the currently built lookup keys.

        The fingerprint changes whenever the set of platform entities changes,
        so an index built for another platform version is rebuilt automatically.
        """
        content = "\n".join(
            f"{api_type}|{type_name}|{name}"
            for api_type, type_name, name in sorted(self._lookup.keys())
        )
        return str(uuid.uuid5(_FINGERPRINT_NAMESPACE, content))

    def _fingerprint_path(self) -> Path:
        return Path(self._qdrant_path) / FINGERPRINT_FILE

    def _read_fingerprint(self) -> str | None:
        try:
            value = self._fingerprint_path().read_text(encoding="utf-8").strip()
            return value or None
        except OSError:
            return None

    def _write_fingerprint(self, fingerprint: str) -> None:
        try:
            self._fingerprint_path().write_text(fingerprint, encoding="utf-8")
        except OSError:
            logger.exception(
                "Failed to write index fingerprint to {}", self._fingerprint_path()
            )

    def _build_index(self, storage: PlatformContextStorage) -> None:
        """Build the vector index from all entities in storage."""
        from qdrant_client.models import Distance, PointStruct, VectorParams

        logger.info("Building semantic index...")
        docs = self._builder.build_all(storage)
        if not docs:
            logger.warning("No documents to index")
            return

        texts = [doc.text for doc in docs]
        logger.info("Embedding {} documents...", len(texts))
        vectors = self._embedder.embed_documents(texts)
        if len(vectors) != len(docs):
            raise RuntimeError(
                f"Embedding provider returned {len(vectors)} vectors "
                f"for {len(docs)} documents; refusing partial index"
            )

        # Recreate collection
        try:
            self._client.delete_collection(COLLECTION_NAME)
            logger.info("Dropped existing collection '{}'", COLLECTION_NAME)
        except Exception:
            logger.opt(exception=True).debug("No existing collection to drop")

        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=self._embedder.dimension(),
                distance=Distance.COSINE,
            ),
        )

        # Upsert in batches
        for i in range(0, len(docs), UPSERT_BATCH_SIZE):
            batch_docs = docs[i : i + UPSERT_BATCH_SIZE]
            batch_vectors = vectors[i : i + UPSERT_BATCH_SIZE]
            if len(batch_docs) != len(batch_vectors):
                raise RuntimeError(
                    f"Batch size mismatch: {len(batch_docs)} docs vs "
                    f"{len(batch_vectors)} vectors"
                )
            points = [
                PointStruct(id=doc.id, vector=vec, payload=doc.metadata)
                for doc, vec in zip(batch_docs, batch_vectors)
            ]
            self._client.upsert(
                collection_name=COLLECTION_NAME, points=points
            )

        logger.info("Semantic index built: {} documents indexed", len(docs))

    def _build_lookup(self, storage: PlatformContextStorage) -> None:
        """Build in-memory lookup dict for resolving Qdrant results to Definitions."""
        lookup: dict[tuple[str, str, str], Definition] = {}

        for method in storage.methods:
            lookup[("method", "", method.name)] = method

        for prop in storage.properties:
            lookup[("property", "", prop.name)] = prop

        for type_def in storage.types:
            lookup[("type", "", type_def.name)] = type_def
            for method in type_def.methods:
                lookup[("method", type_def.name, method.name)] = method
            for prop in type_def.properties:
                lookup[("property", type_def.name, prop.name)] = prop

        self._lookup = lookup
        logger.debug("Lookup table built: {} entries", len(lookup))

    def _resolve_definition(self, payload: dict) -> Definition | None:
        """Resolve a Qdrant payload back to a Definition object."""
        key = (
            payload.get("api_type", ""),
            payload.get("type_name", ""),
            payload.get("name", ""),
        )
        return self._lookup.get(key)
