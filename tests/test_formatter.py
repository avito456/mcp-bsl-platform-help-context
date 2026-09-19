"""Tests for the Markdown formatter."""

from mcp_bsl_context.domain.entities import (
    MethodDefinition,
    ParameterDefinition,
    PlatformTypeDefinition,
    PropertyDefinition,
    Signature,
)
from mcp_bsl_context.presentation.formatter import MarkdownFormatter


class TestMarkdownFormatter:
    def setup_method(self):
        self.formatter = MarkdownFormatter()

    def test_empty_results(self):
        result = self.formatter.format_search_results([])
        assert "Nothing found" in result

    def test_single_method_result(self):
        method = MethodDefinition(
            name="Найти",
            description="Поиск значения",
            return_type="Произвольный",
        )
        result = self.formatter.format_search_results([method])
        assert "Найти" in result
        assert "Поиск значения" in result

    def test_multiple_results_compact(self):
        methods = [
            MethodDefinition(name=f"Method{i}", description=f"Description {i}")
            for i in range(3)
        ]
        result = self.formatter.format_search_results(methods)
        assert "Found 3 results" in result
        assert "Method0" in result
        assert "Method1" in result
        assert "Method2" in result

    def test_many_results_table(self):
        methods = [
            MethodDefinition(name=f"Method{i}", description=f"Desc {i}")
            for i in range(10)
        ]
        result = self.formatter.format_search_results(methods)
        assert "showing top 5" in result
        assert "| #" in result

    def test_format_type(self):
        t = PlatformTypeDefinition(
            name="ТаблицаЗначений",
            description="Описание",
            methods=[MethodDefinition(name="Добавить", description="")],
            properties=[PropertyDefinition(name="Колонки", description="")],
        )
        result = self.formatter.format_member(t)
        assert "ТаблицаЗначений" in result
        assert "Methods" in result
        assert "Properties" in result

    def test_format_method_with_params(self):
        method = MethodDefinition(
            name="Func",
            description="A function",
            signatures=[
                Signature(
                    name="Func",
                    parameters=[
                        ParameterDefinition(name="a", type="int", description="param", required=True),
                    ],
                    description="",
                )
            ],
        )
        result = self.formatter.format_member(method)
        assert "Func" in result
        assert "Parameters" in result
        assert "`a`" in result

    def test_format_property(self):
        prop = PropertyDefinition(
            name="ТекущаяДата",
            description="Дата",
            property_type="Дата",
            is_read_only=True,
        )
        result = self.formatter.format_member(prop)
        assert "ТекущаяДата" in result
        assert "Read-only" in result

    def test_format_constructors(self):
        ctors = [
            Signature(
                name="Новый",
                parameters=[
                    ParameterDefinition(name="Размер", type="Число", description="Размер"),
                ],
                description="Создает массив",
            )
        ]
        result = self.formatter.format_constructors(ctors, "Массив")
        assert "Constructors for Массив" in result
        assert "Размер" in result

    def test_format_constructors_empty(self):
        result = self.formatter.format_constructors([], "Тип")
        assert "no constructors" in result

    def test_format_type_members(self):
        members = [
            MethodDefinition(name="M1", description="method"),
            PropertyDefinition(name="P1", description="property"),
        ]
        result = self.formatter.format_type_members(members)
        assert "Methods" in result
        assert "Properties" in result
        assert "M1" in result
        assert "P1" in result

    def test_format_type_members_limit(self):
        members = [
            MethodDefinition(name=f"M{i}", description=f"m{i}")
            for i in range(25)
        ]
        result = self.formatter.format_type_members(members, limit=20)
        assert "M4" in result
        assert "M20" not in result
        assert "5 more members" in result

    def test_format_type_members_limit_and_offset(self):
        members = [
            MethodDefinition(name=f"M{i}", description="")
            for i in range(25)
        ]
        result = self.formatter.format_type_members(members, limit=10, offset=20)
        assert "M20" in result
        assert "M24" in result
        assert "M19" not in result
        assert "more members" not in result

    def test_format_type_members_empty(self):
        result = self.formatter.format_type_members([])
        assert "No members" in result

    def test_escape_inline_markdown_chars(self):
        method = MethodDefinition(
            name="СправочникОбъект.<Имя>",
            description="Описание [см. также] | тест",
        )
        # Headers are escaped so markdown chars in names don't break rendering.
        result = self.formatter.format_member(method)
        assert "СправочникОбъект.\\<Имя\\>" in result

        # Short inline fragments in result lists are escaped too.
        listed = self.formatter.format_type_members([method], limit=20)
        assert "Описание \\[см. также\\] \\| тест" in listed

    def test_escape_does_not_touch_code_spans(self):
        prop = PropertyDefinition(
            name="P",
            property_type="СправочникОбъект.<Имя справочника>",
            description="test",
        )
        result = self.formatter.format_member(prop)
        assert "`СправочникОбъект.<Имя справочника>`" in result

    def test_truncate_description_at_word_boundary(self):
        method = MethodDefinition(
            name="M",
            description="a" * 90 + " word " + "b" * 30,
        )
        result = self.formatter.format_type_members([method], limit=20)
        # 'word' stays intact instead of being split mid-word
        assert "word..." in result
        assert "b" * 30 not in result

    def test_format_error(self):
        result = self.formatter.format_error(Exception("test error"))
        assert "Error" in result
        assert "test error" in result

    def test_format_query(self):
        result = self.formatter.format_query("Найти")
        assert "Найти" in result
