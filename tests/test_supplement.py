"""Unit tests for the bundled global-method supplement.

The supplement restores known global methods absent from some HBK files
(``Выполнить``, ``УдалитьОбработчикОжидания`` …) and must never override
real platform data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_bsl_context.domain.entities import MethodDefinition
from mcp_bsl_context.infrastructure.storage.supplement import (
    load_default_supplement,
    merge_supplement_methods,
    parse_supplement_entries,
)

EXISTING = [
    MethodDefinition(name="Сообщить", name_en="Message", description=""),
    MethodDefinition(name="НайтиПоСсылкам", name_en="FindByRef", description=""),
]


def _farm_method(name: str, name_en: str = "") -> MethodDefinition:
    return MethodDefinition(name=name, name_en=name_en, description="тест")


@pytest.fixture
def supplement() -> list[MethodDefinition]:
    return load_default_supplement()


def test_bundled_supplement_parses() -> None:
    methods = load_default_supplement()
    assert methods, "bundled supplement must not be empty"


def test_parses_list_and_dict_payload() -> None:
    json_str = (
        '[{"name": "A", "name_en": "EnA", "description": "d",'
        '"return_type": "Булево", "signatures": [{'
        '"name": "A()", "parameters": [{"name": "p", "type": "Строка",'
        '"description": "pd", "required": true}]}]}]'
    )
    for payload in (json_str, json.loads(json_str), {"methods": json.loads(json_str)}):
        methods = parse_supplement_entries(payload)
        assert len(methods) == 1
        m = methods[0]
        assert (m.name, m.name_en, m.return_type) == ("A", "EnA", "Булево")
        assert m.signatures[0].name == "A()"
        assert m.signatures[0].parameters[0].required is True


def test_invalid_json_returns_empty() -> None:
    assert parse_supplement_entries("{not json") == []


def test_entry_without_name_is_skipped() -> None:
    methods = parse_supplement_entries([{"description": "x"}])
    assert methods == []


def test_merge_appends_supplement() -> None:
    merged, added = merge_supplement_methods(
        list(EXISTING), [_farm_method("Выполнить", "Execute")]
    )
    assert added == 1
    assert [m.name for m in merged][-1] == "Выполнить"


def test_merge_dedup_by_russian_name_keeps_existing() -> None:
    merged, added = merge_supplement_methods(
        list(EXISTING), [_farm_method("Сообщить", "Execute")]
    )
    assert added == 0
    assert len(merged) == len(EXISTING)


def test_merge_dedup_by_english_name() -> None:
    merged, added = merge_supplement_methods(
        list(EXISTING), [_farm_method("Экзотика", "FindByRef")]
    )
    assert added == 0
    assert len(merged) == len(EXISTING)


def test_merge_does_not_mutate_existing() -> None:
    original = list(EXISTING)
    merge_supplement_methods(original, [_farm_method("Выполнить")])
    assert original == EXISTING


def test_supplement_contains_execute_with_signature() -> None:
    methods = load_default_supplement()
    by_name = {m.name: m for m in methods}
    execute = by_name.get("Выполнить")
    assert execute is not None
    assert execute.name_en == "Execute"
    assert execute.signatures and execute.signatures[0].parameters


# --- Real-HBK regression: merge stays additive against actual data -----------

@pytest.fixture(scope="module")
def hbk_storage():
    from mcp_bsl_context.infrastructure.storage.loader import PlatformContextLoader
    from mcp_bsl_context.infrastructure.storage.storage import PlatformContextStorage

    data_dir = Path(__file__).resolve().parents[1] / "8.3.27.72"
    hbk = data_dir / "shcntx_ru.hbk"
    if not hbk.exists():
        pytest.skip("real HBK data not present")
    storage = PlatformContextStorage(PlatformContextLoader(), data_dir)
    storage.ensure_loaded()
    return storage


def test_supplement_merged_into_real_hbk(hbk_storage) -> None:
    names = {m.name for m in hbk_storage.methods}
    assert "Выполнить" in names
    assert "ЭтоАдминистраторИБ" in names


def test_bundled_json_has_no_real_hbk_collision(hbk_storage) -> None:
    hbk_names = {m.name.lower() for m in hbk_storage.methods}
    for m in load_default_supplement():
        assert m.name.lower() not in hbk_names, (
            f"супплемент дублирует реальный метод {m.name}"
        )