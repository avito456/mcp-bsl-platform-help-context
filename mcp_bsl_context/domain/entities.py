"""Domain entities for 1C platform context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class ParameterDefinition:
    name: str
    type: str
    description: str
    required: bool = False
    default_value: str | None = None


@dataclass(frozen=True)
class Signature:
    name: str
    parameters: list[ParameterDefinition]
    description: str


@dataclass(frozen=True)
class MethodDefinition:
    name: str
    description: str
    return_type: str = ""
    name_en: str = ""
    signatures: list[Signature] = field(default_factory=list)


@dataclass(frozen=True)
class PropertyDefinition:
    name: str
    description: str
    property_type: str = ""
    is_read_only: bool = False
    name_en: str = ""


@dataclass(frozen=True)
class PlatformTypeDefinition:
    name: str
    description: str
    name_en: str = ""
    methods: list[MethodDefinition] = field(default_factory=list)
    properties: list[PropertyDefinition] = field(default_factory=list)
    constructors: list[Signature] = field(default_factory=list)

    def has_methods(self) -> bool:
        return len(self.methods) > 0

    def has_properties(self) -> bool:
        return len(self.properties) > 0


Definition = Union[MethodDefinition, PropertyDefinition, PlatformTypeDefinition]


def definition_api_type(defn: Definition) -> str:
    """Return the API type string for a definition."""
    if isinstance(defn, MethodDefinition):
        return "method"
    if isinstance(defn, PropertyDefinition):
        return "property"
    return "type"


def definition_names(defn: Definition) -> list[str]:
    """Return all lookup names of a definition (RU + EN aliases).

    The primary name is first; the English alias follows when present
    and different from the primary.  Used to build search indexes so
    queries in either language resolve to the same entity.
    """
    aliases = [defn.name]
    name_en = getattr(defn, "name_en", "") or ""
    if name_en and name_en != defn.name:
        aliases.append(name_en)
    return aliases


def definition_key(defn: Definition, type_name: str = "") -> tuple[str, str, str]:
    """Unified dedup key: (api_type, owner_type_name, name), all lowercased.

    ``type_name`` is the owning platform type for type members (empty for
    global methods/properties and types themselves).  Two members with the
    same name but different owners produce different keys and are never
    collapsed during deduplication.
    """
    return (definition_api_type(defn), (type_name or "").lower(), defn.name.lower())
