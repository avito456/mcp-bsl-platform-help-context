"""Platform context storage with lazy initialization."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from mcp_bsl_context.domain.entities import (
    Definition,
    MethodDefinition,
    PlatformTypeDefinition,
    PropertyDefinition,
)

from .loader import PlatformContextLoader
from .mapper import method_info_to_entity, object_info_to_entity, property_info_to_entity

logger = logging.getLogger(__name__)


def build_member_index(
    types: list[PlatformTypeDefinition],
) -> tuple[list[Definition], dict[int, str]]:
    """Flatten type members into a searchable list with owner-type mapping.

    Returns ``(members, member_owner)`` where ``member_owner`` maps the
    ``id()`` of each member definition to its owning platform type name.
    """
    members: list[Definition] = []
    member_owner: dict[int, str] = {}
    for type_def in types:
        for method in type_def.methods:
            members.append(method)
            member_owner[id(method)] = type_def.name
        for prop in type_def.properties:
            members.append(prop)
            member_owner[id(prop)] = type_def.name
    return members, member_owner


class PlatformContextStorage:
    """Thread-safe lazy-loading storage for platform context data."""

    def __init__(self, loader: PlatformContextLoader, platform_path: Path) -> None:
        self._loader = loader
        self._platform_path = platform_path
        self.methods: list[MethodDefinition] = []
        self.properties: list[PropertyDefinition] = []
        self.types: list[PlatformTypeDefinition] = []
        self.members: list[Definition] = []
        self.member_owner: dict[int, str] = {}
        self._loaded = False
        self._lock = threading.RLock()

    @classmethod
    def from_loaded_data(
        cls,
        methods: list[MethodDefinition],
        properties: list[PropertyDefinition],
        types: list[PlatformTypeDefinition],
    ) -> "PlatformContextStorage":
        """Create a storage pre-populated with already-loaded data.

        Used by data sources (e.g. JSON loader) that bypass HBK parsing.
        The storage reports itself as loaded, so no loader is needed.
        """
        storage = cls(loader=None, platform_path=Path())
        storage.methods = methods
        storage.properties = properties
        storage.types = types
        storage.members, storage.member_owner = build_member_index(types)
        storage._loaded = True
        return storage

    def ensure_loaded(self) -> None:
        """Ensure context is loaded (double-checked locking)."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._do_load()
            self._loaded = True

    def _do_load(self) -> None:
        """Load platform context from HBK file."""
        logger.info("Loading platform context from: %s", self._platform_path)
        context = self._loader.load(self._platform_path)

        self.methods = [method_info_to_entity(m) for m in context.global_methods]
        self.properties = [property_info_to_entity(p) for p in context.global_properties]
        self.types = [object_info_to_entity(t) for t in context.types]
        self.members, self.member_owner = build_member_index(self.types)

        logger.info(
            "Platform context loaded: %d methods, %d properties, %d types",
            len(self.methods),
            len(self.properties),
            len(self.types),
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded
