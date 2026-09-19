"""Tests for PlatformContextStorage."""

from mcp_bsl_context.domain.entities import (
    MethodDefinition,
    PlatformTypeDefinition,
    PropertyDefinition,
)
from mcp_bsl_context.infrastructure.storage.storage import (
    PlatformContextStorage,
    build_member_index,
)


class TestBuildMemberIndex:
    def test_flattens_members_with_owner(self):
        m1 = MethodDefinition(name="Добавить", description="")
        p1 = PropertyDefinition(name="Колонки", description="")
        types = [PlatformTypeDefinition(name="ТаблицаЗначений", description="", methods=[m1], properties=[p1])]

        members, owner = build_member_index(types)
        assert len(members) == 2
        assert owner[id(m1)] == "ТаблицаЗначений"
        assert owner[id(p1)] == "ТаблицаЗначений"

    def test_empty_types(self):
        members, owner = build_member_index([])
        assert members == []
        assert owner == {}


class TestFromLoadedData:
    def test_storage_preloaded(self):
        m = MethodDefinition(name="Добавить", description="")
        methods = [MethodDefinition(name="Сообщить", description="")]
        properties = [PropertyDefinition(name="ТекущаяДата", description="")]
        types = [
            PlatformTypeDefinition(
                name="ТаблицаЗначений", description="", methods=[m]
            )
        ]

        storage = PlatformContextStorage.from_loaded_data(methods, properties, types)

        assert storage.is_loaded is True
        assert storage.methods == methods
        assert storage.properties == properties
        assert storage.types == types
        assert m in storage.members
        assert storage.member_owner[id(m)] == "ТаблицаЗначений"
        # ensure_loaded must not touch the loader (which is None)
        storage.ensure_loaded()