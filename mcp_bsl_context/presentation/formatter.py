"""Markdown formatter for search results and definitions."""

from __future__ import annotations

import re

from mcp_bsl_context.domain.entities import (
    Definition,
    MethodDefinition,
    ParameterDefinition,
    PlatformTypeDefinition,
    PropertyDefinition,
    Signature,
)

# ``<`` and ``>`` are safe inline (template type names like
# "СправочникОбъект.<Имя справочника>" must round-trip unescaped so an AI
# copies the exact name back into info/get_member lookups).  A leading ``<``
# could open an HTML block, so it is escaped separately in _escape_inline.
_ESCAPE_RE = re.compile(r"[\\`*_|\[\]]")


class MarkdownFormatter:
    """Formats platform context data as Markdown for MCP tool responses."""

    def format_error(self, exception: Exception) -> str:
        return f"**Error:** {exception}\n"

    def format_query(self, query: str) -> str:
        return f"**Search:** `{query}`\n\n"

    def format_search_results(
        self,
        results: list[Definition],
        member_owner: dict[int, str] | None = None,
    ) -> str:
        if not results:
            return "Nothing found.\n"

        owner = member_owner or {}

        if len(results) == 1:
            return self.format_member(results[0], owner.get(id(results[0]), ""))

        if len(results) <= 5:
            return self._format_compact_results(results, owner)

        return self._format_table_results(results, owner)

    def format_member(
        self, definition: Definition, owner_type: str = ""
    ) -> str:
        if isinstance(definition, PlatformTypeDefinition):
            return self._format_type(definition)
        if isinstance(definition, MethodDefinition):
            return self._format_method(definition, owner_type)
        if isinstance(definition, PropertyDefinition):
            return self._format_property(definition, owner_type)
        return f"**{self._escape_inline(definition.name)}**\n{definition.description}\n"

    def format_type_members(
        self,
        members: list[Definition],
        limit: int | None = None,
        offset: int = 0,
    ) -> str:
        """Format the members of a type, optionally paged by limit/offset.

        When the list overflows the paging window, a line with the remaining
        count is appended.
        """
        total = len(members)
        if limit is not None:
            page = members[offset : offset + limit]
        else:
            page = members[offset:]

        methods = [m for m in page if isinstance(m, MethodDefinition)]
        properties = [p for p in page if isinstance(p, PropertyDefinition)]

        parts: list[str] = []

        if methods:
            parts.append("## Методы\n")
            for m in methods:
                parts.append(f"- **{self._escape_inline(m.name)}**")
                if m.description:
                    parts.append(
                        f"  {self._escape_inline(self._truncate(m.description, 100))}"
                    )
            parts.append("")

        if properties:
            parts.append("## Свойства\n")
            for p in properties:
                ro = " *(read-only)*" if p.is_read_only else ""
                parts.append(f"- **{self._escape_inline(p.name)}**{ro}")
                if p.description:
                    parts.append(
                        f"  {self._escape_inline(self._truncate(p.description, 100))}"
                    )
            parts.append("")

        if not parts and not (limit is not None and offset < total):
            return "No members found.\n"

        if limit is not None and offset + limit < total:
            parts.append(f"*…and {total - (offset + limit)} more members*\n")

        return "\n".join(parts)

    def format_constructors(self, constructors: list[Signature], type_name: str) -> str:
        if not constructors:
            return f"Type **{self._escape_inline(type_name)}** has no constructors.\n"

        parts: list[str] = [
            f"## Конструкторы для {self._escape_inline(type_name)}\n"
        ]

        for ctor in constructors:
            if ctor.parameters:
                params = ", ".join(p.name for p in ctor.parameters)
                parts.append(f"```\n{ctor.name}({params})\n```\n")
            else:
                parts.append(f"```\n{ctor.name}()\n```\n")

            if ctor.description:
                parts.append(ctor.description)
                parts.append("")

            if ctor.parameters:
                parts.append("**Parameters:**\n")
                for p in ctor.parameters:
                    req = " *(required)*" if p.required else ""
                    desc = f" — {self._escape_inline(p.description)}" if p.description else ""
                    parts.append(f"- `{p.name}`{req}{desc}")
                parts.append("")

        return "\n".join(parts)

    def _format_type(self, type_def: PlatformTypeDefinition) -> str:
        parts: list[str] = [f"## {self._escape_inline(type_def.name)}\n"]

        if type_def.description:
            parts.append(type_def.description)
            parts.append("")

        if type_def.has_methods():
            parts.append(f"**Методы ({len(type_def.methods)}):**\n")
            for m in type_def.methods[:10]:
                parts.append(f"- `{m.name}`")
            if len(type_def.methods) > 10:
                parts.append(f"- ... and {len(type_def.methods) - 10} more")
            parts.append("")

        if type_def.has_properties():
            parts.append(f"**Свойства ({len(type_def.properties)}):**\n")
            for p in type_def.properties[:10]:
                parts.append(f"- `{p.name}`")
            if len(type_def.properties) > 10:
                parts.append(f"- ... and {len(type_def.properties) - 10} more")
            parts.append("")

        if type_def.constructors:
            parts.append(f"**Конструкторы ({len(type_def.constructors)}):**\n")

        return "\n".join(parts)

    def _format_method(self, method: MethodDefinition, owner_type: str = "") -> str:
        heading = (
            f"{owner_type}.{method.name}" if owner_type else method.name
        )
        parts: list[str] = [f"## {self._escape_inline(heading)}\n"]

        if owner_type:
            parts.append(f"**Тип-владелец:** `{self._escape_inline(owner_type)}`\n")

        if method.signatures:
            for sig in method.signatures:
                params = ", ".join(p.name for p in sig.parameters)
                parts.append(f"```\n{method.name}({params})\n```\n")

                if sig.parameters:
                    parts.append("**Parameters:**\n")
                    for p in sig.parameters:
                        req = " *(required)*" if p.required else ""
                        desc = f" — {self._escape_inline(p.description)}" if p.description else ""
                        parts.append(f"- `{p.name}`{req}{desc}")
                    parts.append("")

        if method.description:
            parts.append(method.description)
            parts.append("")

        if method.return_type:
            parts.append(f"**Returns:** `{method.return_type}`\n")

        return "\n".join(parts)

    def _format_property(self, prop: PropertyDefinition, owner_type: str = "") -> str:
        heading = f"{owner_type}.{prop.name}" if owner_type else prop.name
        parts: list[str] = [f"## {self._escape_inline(heading)}\n"]

        if owner_type:
            parts.append(f"**Тип-владелец:** `{self._escape_inline(owner_type)}`\n")

        if prop.property_type:
            parts.append(f"**Type:** `{prop.property_type}`\n")

        if prop.is_read_only:
            parts.append("*Read-only*\n")

        if prop.description:
            parts.append(prop.description)
            parts.append("")

        return "\n".join(parts)

    def _format_compact_results(
        self,
        results: list[Definition],
        member_owner: dict[int, str],
    ) -> str:
        parts: list[str] = [f"Found {len(results)} results:\n"]

        for item in results:
            kind = _get_kind_label(item)
            owner = member_owner.get(id(item), "")
            display = f"{owner}.{item.name}" if owner else item.name
            desc = self._truncate(item.description, 80) if item.description else ""
            parts.append(
                f"- **{self._escape_inline(display)}** ({kind}) — {desc}"
            )

        parts.append("")
        # Show details for the first result
        parts.append("---\n")
        parts.append(
            self.format_member(results[0], member_owner.get(id(results[0]), ""))
        )
        return "\n".join(parts)

    def _format_table_results(
        self,
        results: list[Definition],
        member_owner: dict[int, str],
    ) -> str:
        top5 = results[:5]
        parts: list[str] = [
            f"Found {len(results)} results (showing top 5):\n",
            "| # | Name | Type |",
            "|---|------|------|",
        ]

        for i, item in enumerate(top5, 1):
            kind = _get_kind_label(item)
            owner = member_owner.get(id(item), "")
            display = f"{owner}.{item.name}" if owner else item.name
            parts.append(
                f"| {i} | **{self._escape_inline(display)}** | {kind} |"
            )

        parts.append("")
        # Show details for the first result
        parts.append("---\n")
        parts.append(
            self.format_member(results[0], member_owner.get(id(results[0]), ""))
        )
        return "\n".join(parts)

    @staticmethod
    def _escape_inline(text: str) -> str:
        """Escape markdown inline characters in plain-text spans."""
        escaped = _ESCAPE_RE.sub(lambda m: "\\" + m.group(0), text)
        if escaped.startswith("<"):
            # A leading ``<`` could be read as an HTML block by some renderers.
            return "\\" + escaped
        return escaped

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        """Truncate text to ``limit`` characters at a word boundary."""
        if len(text) <= limit:
            return text
        cut = text[:limit]
        space = cut.rfind(" ")
        if space > limit // 2:
            cut = cut[:space]
        return cut.rstrip() + "..."


def _get_kind_label(item: Definition) -> str:
    if isinstance(item, MethodDefinition):
        return "Method"
    if isinstance(item, PropertyDefinition):
        return "Property"
    if isinstance(item, PlatformTypeDefinition):
        return "Type"
    return "Unknown"
