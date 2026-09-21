"""Bundled supplement for global methods missing from platform help files.

The 1C:Enterprise help (HBK) does not always list every well-known global
method (e.g. ``Выполнить``).  This module merges a curated, version-agnostic
supplement into the loaded context, deduplicating against real data so a
future platform release that documents a method properly is never
overridden.
"""

from __future__ import annotations

import importlib.resources as pkg_resources
import json
from typing import Any

from mcp_bsl_context.domain.entities import (
    MethodDefinition,
    ParameterDefinition,
    Signature,
)

from mcp_bsl_context.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_SUPPLEMENT_FILENAME = "global_methods_supplement.json"


def load_default_supplement() -> list[MethodDefinition]:
    """Read the bundled supplement JSON shipped with the package.

    Returns an empty list on any load/parse failure so the server can start
    with HBK-only data rather than crashing over an optional supplement.
    """
    try:
        ref = pkg_resources.files("mcp_bsl_context.docinfo").joinpath(
            DEFAULT_SUPPLEMENT_FILENAME
        )
        content = ref.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(
            "Не удалось прочитать супплемент глобальных методов ({}): {}",
            DEFAULT_SUPPLEMENT_FILENAME,
            exc,
        )
        return []
    return parse_supplement_entries(content)


def parse_supplement_entries(data: str | list | dict) -> list[MethodDefinition]:
    """Parse supplement JSON content into ``MethodDefinition`` entities.

    Accepts either a JSON string, a list of entries or a ``{"methods": [...]}``
    mapping.  Malformed entries are skipped with a warning.
    """
    if isinstance(data, str):
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            logger.warning("Супплемент глобальных методов: не JSON ({})", exc)
            return []
    else:
        payload = data

    if isinstance(payload, dict):
        payload = payload.get("methods", [])

    entries: list[MethodDefinition] = []
    for item in payload or []:
        if not isinstance(item, dict) or not item.get("name"):
            logger.warning("Супплемент глобальных методов: пропущена запись без имени")
            continue
        signature_items = item.get("signatures") or []
        signatures: list[Signature] = []
        for sig in signature_items:
            parameters: list[ParameterDefinition] = []
            for param in sig.get("parameters") or []:
                parameters.append(
                    ParameterDefinition(
                        name=str(param.get("name", "")),
                        type=str(param.get("type", "")),
                        description=str(param.get("description", "")),
                        required=bool(param.get("required", False)),
                        default_value=param.get("default_value"),
                    )
                )
            signatures.append(
                Signature(
                    name=str(sig.get("name", "")),
                    description=str(sig.get("description", "")),
                    parameters=parameters,
                )
            )
        entries.append(
            MethodDefinition(
                name=str(item["name"]),
                name_en=str(item.get("name_en", "") or ""),
                description=str(item.get("description", "")),
                return_type=str(item.get("return_type", "")),
                signatures=signatures,
            )
        )
    return entries


def merge_supplement_methods(
    existing: list[MethodDefinition],
    supplement: list[MethodDefinition],
) -> tuple[list[MethodDefinition], int]:
    """Merge supplement methods into ``existing``, deduplicating by RU/EN name.

    An existing method always wins: a supplement entry whose Russian *or*
    English name collides with an already-loaded method is skipped.  Returns
    ``(merged_methods, added_count)`` with the original ``existing`` list
    untouched (a new list is returned).
    """
    known: set[str] = set()
    for method in existing:
        known.add(method.name.lower())
        if method.name_en:
            known.add(method.name_en.lower())

    merged = list(existing)
    added = 0
    for method in supplement:
        keys = {method.name.lower()}
        if method.name_en:
            keys.add(method.name_en.lower())
        if keys & known:
            continue
        merged.append(method)
        known |= keys
        added += 1
    return merged, added