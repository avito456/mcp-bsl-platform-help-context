"""Regression tests for the server-level ``search`` tool.

These build a real server from a small JSON context and exercise the
``search`` tool function end-to-end. The key regression is an empty
keyword result: it must return a clean "Nothing found." (with a "did you
mean" hint when applicable) instead of the generic "Внутренняя ошибка".
"""

from __future__ import annotations

import asyncio
import json

from mcp_bsl_context.config import load_config
from mcp_bsl_context.domain.value_objects import PlatformVersion
from mcp_bsl_context.server import create_server, dedupe_versions

_METHODS = [
    {"name": "НайтиПоСсылкам", "name_en": "FindByRef", "description": "Поиск элемента по ссылке"},
    {"name": "НайтиПоКоду", "name_en": "FindByCode", "description": "Поиск элемента по коду"},
    {"name": "Сообщить", "name_en": "Message", "description": "Вывод сообщения"},
]

_TYPES = [
    {
        "name": "ТаблицаЗначений",
        "name_en": "ValueTable",
        "description": "Таблица значений",
        "methods": [
            {"name": "Добавить", "name_en": "Add", "description": "Добавить строку"},
            {"name": "НайтиСтроки", "name_en": "FindRows", "description": "Найти строки по условию"},
            {"name": "Сортировать", "name_en": "Sort", "description": "Сортировать"},
        ],
        "properties": [
            {"name": "Количество", "name_en": "Count", "description": "Количество строк", "type": "Число"}
        ],
        "constructors": [],
    }
]


def _write_context(directory) -> None:
    (directory / "methods.json").write_text(json.dumps(_METHODS), encoding="utf-8")
    (directory / "types.json").write_text(json.dumps(_TYPES), encoding="utf-8")


def _make_search_tool(json_dir):
    config = load_config(
        config_path=None,
        cli_overrides={
            "platform.data_source": "json",
            "platform.json_path": str(json_dir),
            "search.default_mode": "keyword",
            "index.reindex": False,
            "index.warmup": False,
        },
    )
    server = create_server(config)

    async def _fetch() -> callable:
        tools = await server.list_tools()
        return next(t.fn for t in tools if t.name == "search")

    return asyncio.run(_fetch())


class TestSearchToolEmptyResult:
    def test_no_match_returns_clean_output(self, tmp_path):
        _write_context(tmp_path)
        search = _make_search_tool(tmp_path)

        output = search(query="абвгдеёжзиклмнопрст", mode="keyword")

        assert "Внутренняя ошибка" not in output
        assert "Nothing found" in output

    def test_typo_suggests_closest_names(self, tmp_path):
        _write_context(tmp_path)
        search = _make_search_tool(tmp_path)

        output = search(query="Ссобщить", mode="keyword")

        assert "Внутренняя ошибка" not in output
        assert "Возможно, вы имели в виду" in output
        assert "Сообщить" in output

    def test_existing_query_still_works(self, tmp_path):
        _write_context(tmp_path)
        search = _make_search_tool(tmp_path)

        output = search(query="НайтиПоСсылкам", mode="keyword")

        assert "Внутренняя ошибка" not in output
        assert "НайтиПоСсылкам" in output


class TestDedupeVersions:
    def test_deduplicates_builds_of_same_release_preserving_order(self):
        versions = [
            PlatformVersion(8, 5, 1),
            PlatformVersion(8, 3, 27),
            PlatformVersion(8, 5, 1),
            PlatformVersion(8, 4, 10),
        ]
        result = dedupe_versions(versions)
        assert result == [
            PlatformVersion(8, 5, 1),
            PlatformVersion(8, 3, 27),
            PlatformVersion(8, 4, 10),
        ]

    def test_distinct_versions_untouched(self):
        versions = [
            PlatformVersion(8, 3, 25),
            PlatformVersion(8, 4, 10),
        ]
        assert dedupe_versions(versions) == versions

    def test_empty_list_passes_through(self):
        assert dedupe_versions([]) == []