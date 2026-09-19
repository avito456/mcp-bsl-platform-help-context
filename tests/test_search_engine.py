"""Tests for the search engine."""

import threading

from mcp_bsl_context.domain.entities import (
    MethodDefinition,
    PlatformTypeDefinition,
    PropertyDefinition,
)
from mcp_bsl_context.domain.enums import ApiType
from mcp_bsl_context.domain.value_objects import SearchQuery
from mcp_bsl_context.infrastructure.search.engine import SimpleSearchEngine


class FakeStorage:
    """Fake storage for testing the search engine."""

    def __init__(self, methods, properties, types):
        self.methods = methods
        self.properties = properties
        self.types = types
        self.members = []
        self.member_owner = {}
        self._loaded = True
        self._lock = threading.RLock()

    def ensure_loaded(self):
        pass


class TestSimpleSearchEngine:
    def _make_engine(self, methods=None, properties=None, types=None):
        storage = FakeStorage(
            methods=methods or [],
            properties=properties or [],
            types=types or [],
        )
        from mcp_bsl_context.infrastructure.storage.storage import build_member_index

        storage.members, storage.member_owner = build_member_index(storage.types)
        return SimpleSearchEngine(storage)

    def test_search_methods_by_prefix(self, sample_methods):
        engine = self._make_engine(methods=sample_methods)
        results = engine.search(SearchQuery(query="Найти"))
        names = [r.name for r in results]
        assert "НайтиПоСсылке" in names
        assert "НайтиПоКоду" in names
        assert "НайтиПоНаименованию" in names

    def test_search_with_type_filter(self, sample_methods, sample_properties):
        engine = self._make_engine(methods=sample_methods, properties=sample_properties)
        results = engine.search(SearchQuery(query="Текущая", type=ApiType.PROPERTY))
        assert all(isinstance(r, PropertyDefinition) for r in results)

    def test_search_with_limit(self, sample_methods):
        engine = self._make_engine(methods=sample_methods)
        results = engine.search(SearchQuery(query="Найти", limit=1))
        assert len(results) <= 1

    def test_find_type(self, sample_types):
        engine = self._make_engine(types=sample_types)
        result = engine.find_type("ТаблицаЗначений")
        assert result is not None
        assert result.name == "ТаблицаЗначений"

    def test_find_type_case_insensitive(self, sample_types):
        engine = self._make_engine(types=sample_types)
        result = engine.find_type("таблицазначений")
        assert result is not None

    def test_find_type_not_found(self, sample_types):
        engine = self._make_engine(types=sample_types)
        result = engine.find_type("НесуществующийТип")
        assert result is None

    def test_find_method(self, sample_methods):
        engine = self._make_engine(methods=sample_methods)
        result = engine.find_method("Сообщить")
        assert result is not None
        assert result.name == "Сообщить"

    def test_find_property(self, sample_properties):
        engine = self._make_engine(properties=sample_properties)
        result = engine.find_property("ТекущаяДата")
        assert result is not None

    def test_find_type_member(self, sample_types):
        engine = self._make_engine(types=sample_types)
        result = engine.find_type_member("ТаблицаЗначений", "Добавить")
        assert result is not None
        assert result.name == "Добавить"

    def test_find_type_member_property(self, sample_types):
        engine = self._make_engine(types=sample_types)
        result = engine.find_type_member("ТаблицаЗначений", "Колонки")
        assert result is not None
        assert isinstance(result, PropertyDefinition)

    def test_find_type_member_not_found(self, sample_types):
        engine = self._make_engine(types=sample_types)
        result = engine.find_type_member("ТаблицаЗначений", "Неизвестный")
        assert result is None

    def test_empty_search(self):
        engine = self._make_engine()
        results = engine.search(SearchQuery(query="anything"))
        assert results == []

    def test_compound_type_search(self, sample_types):
        engine = self._make_engine(types=sample_types)
        results = engine.search(SearchQuery(query="Справочник Объект"))
        names = [r.name for r in results]
        assert "СправочникОбъект" in names

    def test_word_based_search(self, sample_methods):
        engine = self._make_engine(methods=sample_methods)
        results = engine.search(SearchQuery(query="Ссылке"))
        names = [r.name for r in results]
        assert "НайтиПоСсылке" in names

    def test_partial_word_falls_back_to_substring(self, sample_methods):
        """Non-token (partial/suffix) queries still match via substring scan."""
        engine = self._make_engine(methods=sample_methods)
        results = engine.search(SearchQuery(query="ПоСс"))
        names = [r.name for r in results]
        assert "НайтиПоСсылке" in names

    def test_suggest_returns_closest_names(self, sample_methods):
        engine = self._make_engine(methods=sample_methods)
        suggestions = engine.suggest("НайтиПоСсыцке")
        assert "НайтиПоСсылке" in suggestions

    def test_suggest_empty_for_exact_hit(self, sample_methods):
        engine = self._make_engine(methods=sample_methods)
        assert engine.suggest("НайтиПоКоду") == []

    def test_word_split_handles_yo(self, sample_methods):
        """Query words containing 'ё' are split and matched ('Жёсткий')."""
        engine = self._make_engine(
            methods=[MethodDefinition(name="ЖёсткийДиск", description="")],
            types=[
                PlatformTypeDefinition(
                    name="ТипТест", description="", methods=[], properties=[]
                )
            ],
        )
        results = engine.search(SearchQuery(query="Жёсткий"))
        names = [r.name for r in results]
        assert "ЖёсткийДиск" in names

    def test_single_word_member_search(self, sample_types):
        """C3: one-word queries find members of types (e.g. 'Добавить')."""
        engine = self._make_engine(types=sample_types)
        results = engine.search(SearchQuery(query="Добавить"))
        names = [r.name for r in results]
        assert names.count("Добавить") >= 2  # ТаблицаЗначений + Массив

    def test_members_of_different_types_not_collapsed(self, sample_types):
        """C1: dedup must not collapse same-name members of different types."""
        engine = self._make_engine(types=sample_types)
        results = engine.search(SearchQuery(query="Добавить"))
        add_members = [r for r in results if r.name == "Добавить"]
        assert len(add_members) >= 2

    def test_type_member_search_honors_api_type_filter(self, sample_types):
        """C2: TypeMemberSearch must respect the api_type filter."""
        engine = self._make_engine(types=sample_types)
        results = engine.search(
            SearchQuery(query="ТаблицаЗначений Добавить", type=ApiType.PROPERTY)
        )
        assert results == []

        results = engine.search(
            SearchQuery(query="ТаблицаЗначений Добавить", type=ApiType.METHOD)
        )
        names = [r.name for r in results]
        assert names
        assert all(r.name == "Добавить" for r in results)  # только методы, никаких свойств
