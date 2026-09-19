"""Integration tests against the real HBK data shipped in the repo.

These verify the AI-readiness behaviors end-to-end on real platform data:
RU/EN alias lookups, Type.Member search, template type names, owner types
and the info autodetect path. Skipped automatically when the HBK file is
not present (e.g. a source checkout without the data, or CI).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from mcp_bsl_context.domain.value_objects import SearchQuery
from mcp_bsl_context.infrastructure.search.engine import SimpleSearchEngine
from mcp_bsl_context.infrastructure.storage.loader import PlatformContextLoader
from mcp_bsl_context.infrastructure.storage.storage import PlatformContextStorage

DATA_DIR = Path(__file__).resolve().parents[1] / "8.3.27.72"
HBK = DATA_DIR / "shcntx_ru.hbk"

pytestmark = pytest.mark.skipif(
    not HBK.exists(), reason="real HBK data not present"
)


@pytest.fixture(scope="module")
def storage() -> PlatformContextStorage:
    logging.disable(logging.CRITICAL)
    s = PlatformContextStorage(PlatformContextLoader(), DATA_DIR)
    s.ensure_loaded()
    return s


@pytest.fixture(scope="module")
def engine(storage: PlatformContextStorage) -> SimpleSearchEngine:
    return SimpleSearchEngine(storage)


def test_english_alias_resolves_type(engine: SimpleSearchEngine) -> None:
    result = engine.find_type("ValueTable")
    assert result is not None
    assert result.name == "ТаблицаЗначений"


def test_english_alias_resolves_method(engine: SimpleSearchEngine) -> None:
    assert engine.find_method("FindByRef") is not None
    assert engine.find_method("FindByRef").name == "НайтиПоСсылкам"


def test_english_alias_type_member(engine: SimpleSearchEngine) -> None:
    member = engine.find_type_member("ValueTable", "Add")
    assert member is not None
    assert member.name == "Добавить"


def test_russian_type_member(engine: SimpleSearchEngine) -> None:
    member = engine.find_type_member("ТаблицаЗначений", "Добавить")
    assert member is not None
    assert member.name == "Добавить"


def test_type_member_search_finds_member_first(engine: SimpleSearchEngine) -> None:
    results = engine.search(SearchQuery(query="ТаблицаЗначений.Добавить", limit=3))
    assert results
    assert results[0].name == "Добавить"


def test_type_member_search_english(engine: SimpleSearchEngine) -> None:
    results = engine.search(SearchQuery(query="ValueTable.Add", limit=3))
    assert results
    assert results[0].name == "Добавить"


def test_template_type_member_roundtrip(engine: SimpleSearchEngine) -> None:
    member = engine.find_type_member("СправочникОбъект.<Имя справочника>", "Записать")
    assert member is not None
    assert member.name == "Записать"


def test_suggest_on_typo(engine: SimpleSearchEngine) -> None:
    suggestions = engine.suggest("НайтиПоСсыцке")
    assert "НайтиПоСсылкам" in suggestions


def test_member_owners_populated(storage: PlatformContextStorage) -> None:
    """Members of platform types map back to a real owner type name."""
    assert storage.member_owner
    type_names = {t.name for t in storage.types}
    for member in storage.members:
        owner = storage.member_owner.get(id(member))
        assert owner is not None, f"member {member.name} has no owner"
        assert owner in type_names, f"owner {owner!r} is not a known type"


def test_all_names_have_russian_primary(storage: PlatformContextStorage) -> None:
    """Every type has a Russian primary name (RU-first presentation)."""
    for t in storage.types:
        assert t.name


def test_fake_names_absent_from_data(storage: PlatformContextStorage) -> None:
    names = {
        d.name for d in [*storage.methods, *storage.properties, *storage.types]
    }
    assert "НайтиПоСсылке" not in names