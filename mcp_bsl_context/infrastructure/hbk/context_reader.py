"""Main orchestrator for reading platform context from HBK files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .content_reader import HbkContentReader, HbkContext
from .models import EnumInfo, MethodInfo, ObjectInfo, PropertyInfo
from .pages_visitor import PlatformContextPagesVisitor

from mcp_bsl_context.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class PlatformContext:
    """Collected platform context data."""
    types: list[ObjectInfo] = field(default_factory=list)
    enums: list[EnumInfo] = field(default_factory=list)
    global_methods: list[MethodInfo] = field(default_factory=list)
    global_properties: list[PropertyInfo] = field(default_factory=list)


class PlatformContextReader:
    """Reads and collects platform context from an HBK file."""

    def __init__(self) -> None:
        self._content_reader = HbkContentReader()

    def read(self, hbk_path: Path) -> PlatformContext:
        """Read platform context from an HBK file."""
        logger.info("Reading platform context from: {}", hbk_path)
        result = PlatformContext()

        def on_context(ctx: HbkContext) -> None:
            visitor = PlatformContextPagesVisitor(ctx)

            result.global_methods = visitor.collect_global_methods()
            logger.info("Collected {} global methods", len(result.global_methods))

            result.global_properties = visitor.collect_global_properties()
            logger.info("Collected {} global properties", len(result.global_properties))

            result.types = visitor.collect_types()
            logger.info("Collected {} types", len(result.types))

            result.enums = visitor.collect_enums()
            logger.info("Collected {} enums", len(result.enums))

        self._content_reader.read(hbk_path, on_context)
        return result
