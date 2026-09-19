"""Search strategies for the platform context search engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp_bsl_context.domain.entities import (
    Definition,
    MethodDefinition,
    PlatformTypeDefinition,
    PropertyDefinition,
    definition_key,
    definition_names,
)
from mcp_bsl_context.domain.enums import ApiType

if TYPE_CHECKING:
    from .indexes import Indexes


@dataclass
class SearchResult:
    item: Definition
    priority: int
    words_matched: int = 0
    type_name: str = ""


_SPLIT_RE = re.compile(
    r"[А-ЯA-ZЁ][а-яa-zё]*|[а-яa-zё]+|[A-ZЁ]+(?=[А-ЯA-ZЁ][а-яa-zё]|\d|\b)"
)


def _split_words(text: str) -> list[str]:
    """Split camelCase/PascalCase and space-separated words."""
    # Split by spaces first
    parts = text.strip().split()
    words: list[str] = []
    for part in parts:
        # Split camelCase/PascalCase
        tokens = _SPLIT_RE.findall(part)
        if tokens:
            words.extend(tokens)
        else:
            words.append(part)
    return [w.lower() for w in words if w]


class CompoundTypeSearch:
    """Priority 1: Multi-word type queries — joins words into compound type names."""

    priority = 1

    def search(
        self,
        query: str,
        hash_indexes: Indexes,
        prefix_indexes: Indexes,
        api_type: ApiType | None,
    ) -> list[SearchResult]:
        words = query.strip().split()
        if len(words) < 2:
            return []

        if api_type is not None and api_type != ApiType.TYPE:
            return []

        results: list[SearchResult] = []
        seen: set[tuple[str, str, str]] = set()

        # Generate compound variants
        variants = self._generate_variants(words)
        for variant, word_count in variants:
            for item in prefix_indexes.types.get(variant):
                key = definition_key(item)
                if key not in seen:
                    seen.add(key)
                    results.append(SearchResult(item, self.priority, word_count))

        return results

    @staticmethod
    def _generate_variants(words: list[str]) -> list[tuple[str, int]]:
        """Generate compound word variants from a list of words."""
        variants: list[tuple[str, int]] = []
        # All words joined
        variants.append(("".join(words), len(words)))
        # Adjacent pairs
        for i in range(len(words) - 1):
            variants.append(("".join(words[i : i + 2]), 2))
        # First + last (if 3+ words)
        if len(words) >= 3:
            variants.append((words[0] + words[-1], 2))
        return variants


class TypeMemberSearch:
    """Priority 2: Type.Member pattern queries."""

    priority = 2

    def search(
        self,
        query: str,
        hash_indexes: Indexes,
        prefix_indexes: Indexes,
        api_type: ApiType | None,
    ) -> list[SearchResult]:
        words = query.strip().split()
        if len(words) < 2:
            return []

        if api_type is not None and api_type not in (ApiType.METHOD, ApiType.PROPERTY):
            return []

        results: list[SearchResult] = []
        seen: set[tuple[str, str, str]] = set()

        # Try splitting at each position: words[:i] as type, words[i:] as member
        for split_pos in range(1, len(words)):
            type_name = "".join(words[:split_pos])
            member_name = "".join(words[split_pos:])

            type_matches = hash_indexes.types.get(type_name)
            if not type_matches:
                type_matches = prefix_indexes.types.get(type_name)

            for type_def in type_matches:
                if not isinstance(type_def, PlatformTypeDefinition):
                    continue
                member_lower = member_name.lower()
                for method in type_def.methods:
                    if api_type is not None and api_type != ApiType.METHOD:
                        continue
                    if any(
                        n.lower().startswith(member_lower)
                        for n in definition_names(method)
                    ):
                        key = definition_key(method, type_def.name)
                        if key not in seen:
                            seen.add(key)
                            results.append(
                                SearchResult(
                                    method, self.priority, split_pos + 1, type_def.name
                                )
                            )
                for prop in type_def.properties:
                    if api_type is not None and api_type != ApiType.PROPERTY:
                        continue
                    if any(
                        n.lower().startswith(member_lower)
                        for n in definition_names(prop)
                    ):
                        key = definition_key(prop, type_def.name)
                        if key not in seen:
                            seen.add(key)
                            results.append(
                                SearchResult(
                                    prop, self.priority, split_pos + 1, type_def.name
                                )
                            )

        return results


class RegularSearch:
    """Priority 3: Direct index lookup."""

    priority = 3

    def search(
        self,
        query: str,
        hash_indexes: Indexes,
        prefix_indexes: Indexes,
        api_type: ApiType | None,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[tuple[str, str, str]] = set()
        q = query.strip()

        def _add(items: list, priority: int = self.priority) -> None:
            for item in items:
                key = definition_key(item)
                if key not in seen:
                    seen.add(key)
                    results.append(SearchResult(item, priority))

        if api_type is None or api_type == ApiType.METHOD:
            _add(hash_indexes.methods.get(q))
            _add(prefix_indexes.methods.get(q))

        if api_type is None or api_type == ApiType.PROPERTY:
            _add(hash_indexes.properties.get(q))
            _add(prefix_indexes.properties.get(q))

        if api_type is None or api_type == ApiType.TYPE:
            _add(hash_indexes.types.get(q))
            _add(prefix_indexes.types.get(q))

        return results


class WordOrderSearch:
    """Priority 4: Word-based matching across all definitions.

    Uses a cached inverted index (word → definitions) so that common queries
    with fully-matching words skip a full scan of every definition.  When a
    query word is not present as an exact token (partial/suffix matches), the
    search falls back to the historical substring scan to preserve results.
    """

    priority = 4

    def __init__(self) -> None:
        self._word_index: dict[str, list[Definition]] | None = None
        self._index_signature: int | None = None

    def search(
        self,
        query: str,
        all_methods: list[MethodDefinition],
        all_properties: list[PropertyDefinition],
        all_types: list[PlatformTypeDefinition],
        all_members: list[Definition] | None = None,
        member_owner: dict[int, str] | None = None,
        api_type: ApiType | None = None,
    ) -> list[SearchResult]:
        words = _split_words(query)
        if not words:
            return []

        owner = member_owner or {}
        results: list[SearchResult] = []
        seen: set[tuple[str, str, str]] = set()

        def _include(
            item: Definition,
            expected_type: ApiType | None = None,
            type_name: str = "",
        ) -> None:
            if api_type is not None and expected_type is not None and api_type != expected_type:
                return
            names_lower = [n.lower() for n in definition_names(item)]
            matched = sum(
                1 for w in words if any(w in nl for nl in names_lower)
            )
            if matched > 0:
                effective_owner = owner.get(id(item), type_name)
                key = definition_key(item, effective_owner)
                if key not in seen:
                    seen.add(key)
                    results.append(
                        SearchResult(item, self.priority, matched, effective_owner)
                    )

        pool = self._pool(all_methods, all_properties, all_types, all_members)
        index = self._get_index(
            all_methods, all_properties, all_types, all_members, pool
        )

        word_lists = [index.get(w) for w in words]
        if all(word_lists):
            # Fast path: all query words are exact tokens — scan only candidates
            candidates: list[Definition] = []
            seen_candidates: set[int] = set()
            for token_list in word_lists:
                for item in token_list:
                    if id(item) not in seen_candidates:
                        seen_candidates.add(id(item))
                        candidates.append(item)
            for item in candidates:
                _include(item, _classify(item))
            return results

        # Fallback: substring scan across all definitions (historical behavior)
        for method in all_methods:
            _include(method, ApiType.METHOD)
        for prop in all_properties:
            _include(prop, ApiType.PROPERTY)
        for type_def in all_types:
            _include(type_def, ApiType.TYPE)

        if all_members:
            for item in all_members:
                if isinstance(item, MethodDefinition):
                    _include(item, ApiType.METHOD)
                elif isinstance(item, PropertyDefinition):
                    _include(item, ApiType.PROPERTY)

        return results

    @staticmethod
    def _pool(
        all_methods: list[MethodDefinition],
        all_properties: list[PropertyDefinition],
        all_types: list[PlatformTypeDefinition],
        all_members: list[Definition] | None,
    ) -> list[Definition]:
        """Merge all definition pools with identity deduplication."""
        pooled: list[Definition] = []
        seen_ids: set[int] = set()
        for item in [*all_methods, *all_properties, *all_types, *(all_members or [])]:
            if id(item) not in seen_ids:
                seen_ids.add(id(item))
                pooled.append(item)
        return pooled

    def _get_index(
        self,
        all_methods: list[MethodDefinition],
        all_properties: list[PropertyDefinition],
        all_types: list[PlatformTypeDefinition],
        all_members: list[Definition] | None,
        pool: list[Definition],
    ) -> dict[str, list[Definition]]:
        """Build (or reuse) the word → definitions inverted index.

        The index is cached on the object identity of the underlying lists,
        which are stable for the lifetime of a storage instance.
        """
        signature = (
            id(all_methods),
            id(all_properties),
            id(all_types),
            id(all_members),
        )
        if self._index_signature != signature:
            index: dict[str, list[Definition]] = {}
            for item in pool:
                for alias in definition_names(item):
                    for token in _split_words(alias):
                        index.setdefault(token, []).append(item)
            self._word_index = index
            self._index_signature = signature
        return self._word_index


def _classify(item: Definition) -> ApiType | None:
    """Map a Definition to its ApiType for filtering."""
    if isinstance(item, MethodDefinition):
        return ApiType.METHOD
    if isinstance(item, PropertyDefinition):
        return ApiType.PROPERTY
    if isinstance(item, PlatformTypeDefinition):
        return ApiType.TYPE
    return None
