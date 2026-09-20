"""Service for BSL documentation: strict typing guide and coding guidelines."""

from __future__ import annotations

import re
from pathlib import Path

from mcp_bsl_context.domain.exceptions import (
    DomainException,
    InvalidSearchQueryException,
)

TOPIC_PATTERN = re.compile(r"^## TOPIC:\s*(.+)$", re.MULTILINE)

CONTEXT_CHARS = 100


class TopicNotFoundException(DomainException):
    pass


class DocsLoadException(DomainException):
    pass


class DocsInfoService:
    """Loads and queries bundled BSL documentation files."""

    def __init__(
        self,
        strict_types_content: str,
        guideline_content: str,
    ) -> None:
        self._strict_types_content = strict_types_content
        self._guideline_content = guideline_content
        self._topics: dict[str, str] | None = None

    def get_guideline(self) -> str:
        """Return full guideline markdown content."""
        return self._guideline_content

    def get_strict_typing_info(self, topic: str) -> str:
        """Return a specific topic section, or list all topic names."""
        topics = self._ensure_topics()

        if topic.strip().lower() == "topics":
            lines = ["**Доступные темы по строгой типизации:**\n"]
            for name in topics:
                lines.append(f"- `{name}`")
            return "\n".join(lines)

        key = topic.strip().lower()
        if key not in topics:
            available = ", ".join(f"`{n}`" for n in topics)
            raise TopicNotFoundException(
                f"Тема '{topic}' не найдена. Доступные темы: {available}"
            )

        return topics[key]

    def search_strict_typing(self, query: str) -> str:
        """Keyword search within strict-types content with context previews.

        The query is split into words; a topic matches when any of its words
        appear in the topic body (so multi-word queries like «Массив
        конструктор» still find the ``arrays`` topic). Topics that match
        more query words rank higher; ties break by the earliest match.
        """
        stripped = query.strip()
        if not stripped:
            raise InvalidSearchQueryException(
                "Поисковый запрос не может быть пустым"
            )

        tokens = self._tokenize_query(stripped)
        if not tokens:
            raise InvalidSearchQueryException(
                "Поисковый запрос не содержит слов"
            )

        topics = self._ensure_topics()
        scored: list[tuple[int, int, str, str]] = []

        for name, content in topics.items():
            content_lower = content.lower()
            matched = [w for w in tokens if w in content_lower]
            if not matched:
                continue
            first_pos = min(content_lower.find(w) for w in matched)
            scored.append((len(matched), first_pos, name, content))

        if not scored:
            return f"По запросу «{stripped}» ничего не найдено."

        scored.sort(key=lambda s: (-s[0], s[1]))

        results: list[str] = []
        for matched_count, first_pos, name, content in scored:
            preview = self._context_preview(content, first_pos, len(stripped))
            matched_note = (
                f" _(совпало {matched_count} из {len(tokens)} слов)_"
                if matched_count < len(tokens)
                else ""
            )
            results.append(f"### Тема: `{name}`{matched_note}\n\n{preview}")

        header = (
            f"**Результаты поиска по запросу «{stripped}»** "
            f"({len(results)} {self._pluralize(len(results))}):\n"
        )
        return header + "\n\n---\n\n".join(results)

    @staticmethod
    def _tokenize_query(query: str) -> list[str]:
        """Split a query into lowered word tokens, dropping punctuation."""
        tokens = [
            token.strip(".,;:!?()[]«»\"'`")
            for token in query.split()
        ]
        return [t.lower() for t in tokens if t]

    @staticmethod
    def _context_preview(content: str, pos: int, query_len: int) -> str:
        """Build a context window centered on the first match position."""
        start = max(0, pos - CONTEXT_CHARS)
        end = min(len(content), pos + query_len + CONTEXT_CHARS)
        preview = content[start:end].strip()
        if start > 0:
            preview = "..." + preview
        if end < len(content):
            preview = preview + "..."
        return preview

    def _ensure_topics(self) -> dict[str, str]:
        if self._topics is None:
            self._topics = self._parse_topics(self._strict_types_content)
        return self._topics

    @staticmethod
    def _pluralize(count: int) -> str:
        """Russian plural form of 'совпадение' for a given count."""
        n10 = count % 10
        n100 = count % 100
        if n10 == 1 and n100 != 11:
            return "совпадение"
        if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
            return "совпадения"
        return "совпадений"

    @staticmethod
    def _parse_topics(content: str) -> dict[str, str]:
        """Parse strict-types markdown into topic sections."""
        parts = TOPIC_PATTERN.split(content)
        topics: dict[str, str] = {}

        # parts[0] is text before first TOPIC header (preamble, skip)
        # then alternating: topic_name, topic_content, topic_name, ...
        i = 1
        while i < len(parts) - 1:
            name = parts[i].strip().lower()
            body = parts[i + 1].strip()
            topics[name] = body
            i += 2

        return topics
