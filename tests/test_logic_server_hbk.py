"""Server-level logic tests against a real HBK platform help (1C programming questions).

The battery mirrors an interactive "1C developer Q&A" session: search by
Russian questions, Type.Member dotted names, template types, typo/noise
handling, supplement-provided methods (Execute), Russian formatter headers,
version deduplication and the strict-typing/docs tools.

Skipped automatically when no HBK `shcntx_ru.hbk` is available: the bundled
repo directory `8.3.27.72` or the directory given in the environment variable
``MCP_BSL_LOGICTEST_HBK_DIR`` (e.g. a local installation path such as
``/opt/1cv8/8.5.1.1343``).
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest

from mcp_bsl_context.config import load_config
from mcp_bsl_context.server import create_server

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_DATA = REPO_ROOT / "8.3.27.72"
INTERNAL_ERROR = "Внутренняя ошибка"


def _find_hbk_dir() -> Path | None:
    candidates = [BUNDLED_DATA]
    env_dir = os.environ.get("MCP_BSL_LOGICTEST_HBK_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    for candidate in candidates:
        if (candidate / "shcntx_ru.hbk").is_file():
            return candidate
    return None


HBK_DIR = _find_hbk_dir()

pytestmark = pytest.mark.skipif(
    HBK_DIR is None,
    reason="real HBK data not present (bundled 8.3.27.72 or MCP_BSL_LOGICTEST_HBK_DIR)",
)


def first_item(output: str) -> str:
    """Extract the first bold item name from a compact results list."""
    for line in output.splitlines():
        match = re.match(r"^- \*\*([^*]+)\*\*", line.strip())
        if match:
            return match.group(1)
    return ""


@pytest.fixture(scope="module")
def tools() -> dict[str, callable]:
    """Server tool functions with a real HBK context, keyword mode only."""
    assert HBK_DIR is not None
    config = load_config(
        config_path=None,
        cli_overrides={
            "platform.data_source": "hbk",
            "platform.path": str(HBK_DIR),
            "search.default_mode": "keyword",
            "index.reindex": False,
            "index.warmup": False,
        },
    )
    server = create_server(config)

    async def _fetch() -> dict[str, callable]:
        tools_ = await server.list_tools()
        return {t.name: t.fn for t in tools_}

    return asyncio.run(_fetch())


def _search(tools: dict[str, callable], query: str, limit: int = 5) -> str:
    return tools["search"](query=query, mode="keyword", limit=limit)


class TestHealthAndVersions:
    def test_health_reports_loaded_context(self, tools) -> None:
        output = tools["health"]()
        assert INTERNAL_ERROR not in output
        assert "Context loaded:" in output

    def test_platform_info_without_duplicate_versions(self, tools) -> None:
        output = tools["get_platform_info"]()
        releases = [line for line in output.splitlines() if line.startswith("- ")]
        assert releases, "no platform versions reported"
        assert len(releases) == len(set(releases)), "duplicate version entries"


class TestSearchQuestions:
    def test_type_lookup_table_of_values(self, tools) -> None:
        output = _search(tools, "ТаблицаЗначений", limit=1)
        assert INTERNAL_ERROR not in output
        assert "## ТаблицаЗначений" in output

    def test_execute_method_found(self, tools) -> None:
        output = _search(tools, "Выполнить", limit=5)
        assert first_item(output) == "Выполнить"

    def test_find_by_ref_found(self, tools) -> None:
        output = _search(tools, "НайтиПоСсылкам", limit=2)
        assert "НайтиПоСсылкам" in output

    def test_partial_name_by_segments(self, tools) -> None:
        output = _search(tools, "ПоСс", limit=3)
        assert first_item(output) == "НайтиПоСсылкам"

    def test_word_form_строку(self, tools) -> None:
        output = _search(tools, "строку", limit=5)
        assert INTERNAL_ERROR not in output
        items = re.findall(r"^- \*\*([^*]+)\*\*", output, flags=re.M)
        assert len(items) >= 3, f"too few results: {items}"
        assert all("Строк" in item for item in items), (
            f"word form 'строку' not morph-matched: {items}"
        )

    def test_type_member_dotted_name(self, tools) -> None:
        output = _search(tools, "ТаблицаЗначений.Добавить", limit=3)
        assert first_item(output) == "ТаблицаЗначений.Добавить"


class TestNoiseAndTypos:
    def test_pure_noise_returns_nothing_found(self, tools) -> None:
        output = _search(tools, "хухрымухры", limit=3)
        assert INTERNAL_ERROR not in output
        assert "Nothing found" in output

    def test_typo_recovers_with_fuzzy_results(self, tools) -> None:
        output = _search(tools, "НайтиПоСсыцке", limit=3)
        assert INTERNAL_ERROR not in output
        assert "НайтиПоСсылкам" in output


class TestDetailTools:
    def test_info_execute_card_with_signature(self, tools) -> None:
        output = tools["info"](name="Выполнить")
        assert "## Выполнить" in output
        assert "СтрокиПрограммы" in output

    def test_get_member_table_of_values_add(self, tools) -> None:
        output = tools["get_member"](
            type_name="ТаблицаЗначений", member_name="Добавить"
        )
        assert "ТаблицаЗначений.Добавить" in output

    def test_get_member_template_type(self, tools) -> None:
        output = tools["get_member"](
            type_name="СправочникОбъект.<Имя справочника>", member_name="Записать"
        )
        assert "Записать" in output

    def test_get_members_russian_headers(self, tools) -> None:
        output = tools["get_members"](type_name="ТаблицаЗначений", limit=5)
        assert "## Методы" in output

    def test_get_members_rejects_unknown_method(self, tools) -> None:
        output = tools["get_member"](
            type_name="ТаблицаЗначений", member_name="НетТакогоМетода"
        )
        assert INTERNAL_ERROR not in output
        assert "Error" in output
        assert "Подсказка" in output

    def test_get_constructors_query(self, tools) -> None:
        output = tools["get_constructors"](type_name="Запрос")
        assert "Запрос" in output
        assert output.strip() != ""


class TestStrictTypingAndDocs:
    def test_strict_typing_topic_list(self, tools) -> None:
        output = tools["get_strict_typing_info"](topic="topics")
        assert "Доступные темы" in output

    def test_strict_typing_value_table_topic(self, tools) -> None:
        output = tools["get_strict_typing_info"](topic="value-table")
        assert "ТаблицаЗначений" in output or "ДеревоЗначений" in output

    def test_strict_typing_text_search(self, tools) -> None:
        output = tools["search_strict_typing"](query="Массив конструктор")
        assert "arrays" in output

    def test_coding_guideline(self, tools) -> None:
        output = tools["get_coding_guideline"]()
        assert len(output) > 200