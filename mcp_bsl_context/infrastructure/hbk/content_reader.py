"""HBK content reader: extracts TOC and HTML pages from the container."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Callable

from .container_reader import HbkContainerReader
from .toc.toc import Toc

from mcp_bsl_context.logging_setup import get_logger

logger = get_logger(__name__)


class HbkContext:
    """Provides access to TOC and HTML pages from an HBK file."""

    def __init__(self, toc: Toc, zip_file: zipfile.ZipFile) -> None:
        self.toc = toc
        self._zip = zip_file
        self._name_set: set[str] | None = None
        self._lower_to_name: dict[str, str] | None = None

    def read_page(self, path: str) -> str | None:
        """Read an HTML page by its path from the ZIP archive."""
        if not path:
            return None
        try:
            # Normalize path separators and strip leading slash
            normalized = path.replace("\\", "/").lstrip("/")
            if self._name_set is None:
                self._name_set = set(self._zip.namelist())
                self._lower_to_name = {n.lower(): n for n in self._name_set}

            if normalized in self._name_set:
                # Pages carry a UTF-8 BOM (EF BB BF); utf-8-sig strips it
                return self._zip.read(normalized).decode("utf-8-sig", errors="replace")

            # Case-insensitive match via an O(1) lookup instead of a full scan
            original = self._lower_to_name.get(normalized.lower())
            if original is not None:
                return self._zip.read(original).decode("utf-8-sig", errors="replace")
        except (KeyError, zipfile.BadZipFile) as e:
            logger.warning("Failed to read page '{}': {}", path, e)
        return None


class HbkContentReader:
    """Reads and decompresses the HBK container into TOC + ZIP of HTML pages."""

    def __init__(self) -> None:
        self._container_reader = HbkContainerReader()

    def read(self, path: Path, callback: Callable[[HbkContext], None]) -> None:
        """Read HBK file and invoke callback with the context."""
        files = self._container_reader.read(path)

        # Extract and inflate PackBlock (TOC)
        pack_block_data = files.get("PackBlock")
        if pack_block_data is None:
            raise ValueError("PackBlock not found in HBK container")

        toc_data = self._inflate_pack_block(pack_block_data)
        toc = Toc.parse(toc_data)

        # Extract FileStorage (ZIP with HTML pages)
        file_storage_data = files.get("FileStorage")
        if file_storage_data is None:
            raise ValueError("FileStorage not found in HBK container")

        with zipfile.ZipFile(io.BytesIO(file_storage_data)) as zf:
            ctx = HbkContext(toc, zf)
            callback(ctx)

    @staticmethod
    def _inflate_pack_block(data: bytes) -> bytes:
        """Decompress the PackBlock ZIP to get the TOC bracket file."""
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/") and n]
            if not names:
                raise ValueError("PackBlock ZIP contains no files")
            for name in names:
                info = zf.getinfo(name)
                if info.file_size > 0:
                    return zf.read(name)
            raise ValueError("PackBlock ZIP files are all empty")
