"""Discovery of available platform versions from filesystem."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mcp_bsl_context.domain.value_objects import PlatformVersion

from mcp_bsl_context.logging_setup import get_logger

logger = get_logger(__name__)

HBK_FILENAME = "shcntx_ru.hbk"


@dataclass(frozen=True)
class DiscoveredVersion:
    """A discovered platform version with its filesystem paths."""

    version: PlatformVersion | None  # None when version cannot be determined
    hbk_path: Path  # exact path to shcntx_ru.hbk
    platform_dir: Path  # version-specific directory (passed to storage)


@dataclass(frozen=True)
class PlatformVersionInfo:
    """Resolved version state exposed to MCP tools."""

    active_version: PlatformVersion | None
    active_hbk_path: Path | None
    available_versions: list[PlatformVersion]


class VersionDiscovery:
    """Discovers available platform versions by scanning directory structure.

    Supports three common layouts:
    1. Root contains version subdirs directly:
       C:\\Program Files\\1cv8\\  ->  8.3.18.1741/, 8.3.25.1257/, common/
    2. Root IS a version directory:
       C:\\Program Files\\1cv8\\8.3.25.1257\\  ->  bin/shcntx_ru.hbk
    3. Root has arch subdirs containing version dirs:
       /opt/1cv8/  ->  x86_64/  ->  8.3.18.1741/, 8.3.25.1257/
    """

    def discover(self, platform_path: Path) -> list[DiscoveredVersion]:
        """Discover all available platform versions.

        Returns list sorted ascending by version.
        Empty list if nothing found.
        """
        if not platform_path.exists():
            logger.error("Platform path does not exist: {}", platform_path)
            return []

        # Step 1: scan immediate subdirs for version-pattern directories
        versions = self._scan_version_subdirs(platform_path)
        if versions:
            logger.info(
                "Multi-version mode: found {} versions in {}",
                len(versions),
                platform_path,
            )
            return sorted(versions, key=lambda d: d.version or PlatformVersion(0, 0, 0))

        # Step 2: scan one level deeper (handles arch intermediaries like x86_64/)
        for child in self._safe_iterdir(platform_path):
            if child.is_dir() and PlatformVersion.parse(child.name) is None:
                deeper = self._scan_version_subdirs(child)
                versions.extend(deeper)
        if versions:
            logger.info(
                "Multi-version mode (nested): found {} versions under {}",
                len(versions),
                platform_path,
            )
            return sorted(versions, key=lambda d: d.version or PlatformVersion(0, 0, 0))

        # Step 3: fallback — check if platform_path itself contains HBK
        hbk_path = self._find_hbk_in_dir(platform_path)
        if hbk_path is not None:
            version = PlatformVersion.parse(platform_path.name)
            logger.info(
                "Single-version mode: HBK found at {} (version: {})",
                hbk_path,
                version or "unknown",
            )
            return [
                DiscoveredVersion(
                    version=version,
                    hbk_path=hbk_path,
                    platform_dir=platform_path,
                )
            ]

        logger.warning("No HBK files found in {}", platform_path)
        return []

    def _scan_version_subdirs(self, root: Path) -> list[DiscoveredVersion]:
        """Scan immediate children of root for version-named dirs with HBK files."""
        results: list[DiscoveredVersion] = []

        for child in self._safe_iterdir(root):
            if not child.is_dir():
                continue
            version = PlatformVersion.parse(child.name)
            if version is None:
                continue
            hbk_path = self._find_hbk_in_dir(child)
            if hbk_path is not None:
                results.append(
                    DiscoveredVersion(
                        version=version,
                        hbk_path=hbk_path,
                        platform_dir=child,
                    )
                )
            else:
                logger.debug("Version dir {} has no HBK file, skipping", child.name)

        return results

    @staticmethod
    def _find_hbk_in_dir(dir_path: Path) -> Path | None:
        """Find HBK file in a directory: direct, then bin/, then rglob."""
        # Direct check (most common)
        direct = dir_path / HBK_FILENAME
        if direct.is_file():
            return direct

        # Check bin/ subdirectory (common Windows layout)
        bin_path = dir_path / "bin" / HBK_FILENAME
        if bin_path.is_file():
            return bin_path

        # Fallback: limited recursive search within this version dir
        try:
            for path in dir_path.rglob(HBK_FILENAME):
                if path.is_file():
                    return path
        except PermissionError:
            logger.warning("Permission denied during rglob in {}", dir_path)

        return None

    @staticmethod
    def _safe_iterdir(path: Path) -> list[Path]:
        """Iterate directory, handling permission errors gracefully."""
        try:
            return list(path.iterdir())
        except PermissionError:
            logger.warning("Permission denied: {}", path)
            return []
