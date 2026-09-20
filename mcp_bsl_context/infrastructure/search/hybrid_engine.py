"""Hybrid search engine — merges keyword and semantic results via RRF."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcp_bsl_context.domain.entities import (
    Definition,
    definition_key,
)
from mcp_bsl_context.domain.value_objects import SearchQuery
from mcp_bsl_context.infrastructure.embeddings.document_builder import DocumentBuilder
from mcp_bsl_context.infrastructure.embeddings.reranker import Reranker
from mcp_bsl_context.infrastructure.search.engine import SimpleSearchEngine
from mcp_bsl_context.infrastructure.search.semantic_engine import SemanticSearchEngine

if TYPE_CHECKING:
    from mcp_bsl_context.infrastructure.storage.storage import PlatformContextStorage

logger = logging.getLogger(__name__)

# Standard RRF constant from the original paper (Cormack et al., 2009).
RRF_K = 60
# Keyword-list contribution weight in RRF.
# Measured on real 8.5.1 HBK data: the keyword engine already ranks exact
# lexical hits first (stem + owner-type matching), so equal weights keep
# semantic proximity from being flooded by the keyword side.  Values above
# ~1.2 measurably hurt this ranking, so keep this near 1.0.
KEYWORD_WEIGHT = 1.0
# How much broader the sub-searches run than the final limit.
HYBRID_FETCH_MULTIPLIER = 3
# How many merged candidates are fed to the reranker.
RERANK_CANDIDATES_MULTIPLIER = 2


class HybridSearchEngine:
    """Reciprocal Rank Fusion (RRF) merge of keyword + semantic search.

    Algorithm:
      1. Run keyword search → ranked list A
      2. Run semantic search → ranked list B
      3. For each document d, score(d) = KEYWORD_WEIGHT·Σ_{A} 1/(k + rank_A(d))
         + Σ_{B} 1/(k + rank_B(d))
      4. Deduplicate by name
      5. Optionally rerank top candidates with cross-encoder
      6. Return top-limit results

    RRF is scale-invariant — it doesn't depend on score magnitudes from
    either engine, only on the rank positions.  Documents found by both
    engines naturally receive higher fused scores.  The keyword weight is a
    tunable knob (measured optimal near 1.0); exact lexical hits are
    prioritised by the keyword engine itself rather than by fusing weights.
    """

    def __init__(
        self,
        keyword_engine: SimpleSearchEngine,
        semantic_engine: SemanticSearchEngine,
        reranker: Reranker | None = None,
    ) -> None:
        self._keyword = keyword_engine
        self._semantic = semantic_engine
        self._reranker = reranker
        self._builder = DocumentBuilder()

    def search(
        self,
        query: str,
        storage: PlatformContextStorage,
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[Definition]:
        """Run hybrid search: keyword + semantic → RRF merge → optional rerank.

        Args:
            query: Search query string.
            storage: Platform context storage.
            limit: Maximum results to return.
            type_filter: Optional API type filter ("method"/"property"/"type").
        """
        fetch_limit = limit * HYBRID_FETCH_MULTIPLIER

        # 1. Keyword search
        from mcp_bsl_context.domain.enums import ApiType

        api_type = ApiType.from_string(type_filter) if type_filter else None
        keyword_query = SearchQuery(query=query, type=api_type, limit=fetch_limit)
        keyword_results = self._keyword.search(keyword_query)

        # 2. Semantic search (raw ANN ranking — the cross-encoder rerank
        # happens once on the merged pool below, so keyword evidence is
        # combined with semantics before ordering).
        semantic_results = self._semantic.search(
            query, storage, limit=fetch_limit, type_filter=type_filter, rerank=False
        )

        # 3. RRF merge
        merged = self._rrf_merge(
            keyword_results, semantic_results, member_owner=storage.member_owner
        )

        # 4. Optional rerank
        if self._reranker and len(merged) > 1:
            rerank_candidates = merged[: limit * RERANK_CANDIDATES_MULTIPLIER]
            texts = [
                self._builder.build_text(
                    d, type_name=storage.member_owner.get(id(d), "")
                )
                for d in rerank_candidates
            ]
            reranked = self._reranker.rerank(query, texts, top_k=limit)
            return [rerank_candidates[r.index] for r in reranked]

        return merged[:limit]

    @staticmethod
    def _rrf_merge(
        list_a: list[Definition],
        list_b: list[Definition],
        member_owner: dict[int, str] | None = None,
    ) -> list[Definition]:
        """Merge two ranked lists using Reciprocal Rank Fusion.

        Each document receives score = KEYWORD_WEIGHT·1/(RRF_K + rank_A)
        + 1/(RRF_K + rank_B) from each list where it appears.  Results are
        sorted by fused score descending and deduplicated by a type-aware
        key, so members of different types with the same name are never
        collapsed.
        """
        owner = member_owner or {}
        scores: dict[tuple[str, str, str], float] = {}
        items: dict[tuple[str, str, str], Definition] = {}

        for rank, defn in enumerate(list_a):
            key = _definition_key(defn, owner)
            scores[key] = (
                scores.get(key, 0.0) + KEYWORD_WEIGHT / (RRF_K + rank + 1)
            )
            items.setdefault(key, defn)

        for rank, defn in enumerate(list_b):
            key = _definition_key(defn, owner)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
            items.setdefault(key, defn)

        # Sort by fused score descending
        sorted_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
        return [items[k] for k in sorted_keys]


def _definition_key(
    defn: Definition,
    member_owner: dict[int, str] | None = None,
) -> tuple[str, str, str]:
    """Type-aware dedup key: resolves the owner type for type members."""
    owner = member_owner or {}
    return definition_key(defn, owner.get(id(defn), ""))
