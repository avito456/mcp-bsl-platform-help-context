"""Domain service: ContextSearchService."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .entities import Definition, PlatformTypeDefinition, Signature
from .enums import ApiType
from .exceptions import (
    AmbiguousNameException,
    InvalidSearchQueryException,
    PlatformTypeNotFoundException,
    TypeMemberNotFoundException,
)
from .value_objects import SearchQuery

if TYPE_CHECKING:
    from mcp_bsl_context.infrastructure.storage.repository import PlatformRepository

MIN_LIMIT = 1
MAX_LIMIT = 50
DEFAULT_LIMIT = 10


class ContextSearchService:
    def __init__(self, repository: PlatformRepository) -> None:
        self._repository = repository

    def search_all(
        self,
        query: str,
        type_str: str | None = None,
        limit: int | None = None,
    ) -> list[Definition]:
        if not query or not query.strip():
            raise InvalidSearchQueryException("Search query cannot be empty")

        api_type = None
        if type_str:
            api_type = ApiType.from_string(type_str)

        effective_limit = DEFAULT_LIMIT
        if limit is not None:
            effective_limit = max(MIN_LIMIT, min(limit, MAX_LIMIT))

        search_query = SearchQuery(query=query.strip(), type=api_type, limit=effective_limit)
        return self._repository.search(search_query)

    def get_info(self, name: str, type_str: str | None = None) -> Definition:
        if not name or not name.strip():
            raise InvalidSearchQueryException("Name cannot be empty")

        if type_str and type_str.strip():
            api_type = ApiType.from_string(type_str)
            if api_type is None:
                raise InvalidSearchQueryException(f"Unknown type: {type_str}")
            result = self._find_by_api_type(api_type, name.strip())
            if result is None:
                raise PlatformTypeNotFoundException(
                    f"{api_type.get_display_name()} '{name}' not found"
                )
            return result

        # Autodetect: a name may match a type, a global method or a property.
        candidates: list[tuple[ApiType, Definition]] = []
        for api_type in (ApiType.TYPE, ApiType.METHOD, ApiType.PROPERTY):
            result = self._find_by_api_type(api_type, name.strip())
            if result is not None:
                candidates.append((api_type, result))

        if not candidates:
            raise PlatformTypeNotFoundException(f"'{name}' not found")

        if len(candidates) == 1:
            return candidates[0][1]

        listing = ", ".join(
            f"{api_type.get_display_name().lower()} ({defn.name})"
            for api_type, defn in candidates
        )
        raise AmbiguousNameException(
            f"Имя '{name}' соответствует нескольким элементам: {listing}. "
            "Укажите type_filter: 'method', 'property' или 'type'."
        )

    def _find_by_api_type(
        self, api_type: ApiType, name: str
    ) -> Definition | None:
        if api_type == ApiType.TYPE:
            return self._repository.find_type(name)
        if api_type == ApiType.METHOD:
            return self._repository.find_method(name)
        if api_type == ApiType.PROPERTY:
            return self._repository.find_property(name)
        return None

    def find_member_by_type_and_name(
        self, type_name: str, member_name: str
    ) -> Definition:
        if not type_name or not type_name.strip():
            raise InvalidSearchQueryException("Type name cannot be empty")
        if not member_name or not member_name.strip():
            raise InvalidSearchQueryException("Member name cannot be empty")

        type_def = self._repository.find_type(type_name.strip())
        if type_def is None:
            raise PlatformTypeNotFoundException(f"Type '{type_name}' not found")

        member = self._repository.find_type_member(
            type_name.strip(), member_name.strip()
        )
        if member is None:
            raise TypeMemberNotFoundException(
                f"Member '{member_name}' not found in type '{type_name}'"
            )
        return member

    def find_type_members(self, type_name: str) -> list[Definition]:
        if not type_name or not type_name.strip():
            raise InvalidSearchQueryException("Type name cannot be empty")

        type_def = self._repository.find_type(type_name.strip())
        if type_def is None:
            raise PlatformTypeNotFoundException(f"Type '{type_name}' not found")

        members: list[Definition] = []
        members.extend(type_def.methods)
        members.extend(type_def.properties)
        return members

    def find_constructors(self, type_name: str) -> list[Signature]:
        if not type_name or not type_name.strip():
            raise InvalidSearchQueryException("Type name cannot be empty")

        type_def = self._repository.find_type(type_name.strip())
        if type_def is None:
            raise PlatformTypeNotFoundException(f"Type '{type_name}' not found")

        return type_def.constructors
