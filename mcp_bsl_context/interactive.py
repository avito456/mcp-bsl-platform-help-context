"""Interactive wizard for ``mcp-bsl-context install``.

Engaged only on a real TTY (see ``_want_interactive`` in ``__main__``).
Asks only for values that could not be auto-resolved:

1. platform root — when auto-resolution fails, offers detected defaults;
2. 1C version — when several versions are found, free input with the latest
   as default (``auto`` / empty = leave unset);
3. write confirmation — unless ``--dry-run`` or ``--yes``.

No new dependencies: plain ``click.prompt`` / ``click.confirm``.
"""

from __future__ import annotations

from pathlib import Path

import click

from mcp_bsl_context.installer import (
    InstallerError,
    _os_platform_dir_candidates,
    resolve_platform_path,
)


def discover_versions(root: Path) -> list:
    """Discover platform versions under *root* via the runtime's discovery."""
    from mcp_bsl_context.infrastructure.storage.version_discovery import VersionDiscovery

    try:
        return VersionDiscovery().discover(root)
    except Exception:
        return []


def _version_proc(value: str) -> str | None:
    v = value.strip()
    if not v or v.lower() == "auto":
        return None
    from mcp_bsl_context.domain.value_objects import PlatformVersion

    if PlatformVersion.parse(v) is None:
        raise click.BadParameter(
            f"не распознан формат версии: {v!r} (ожидается 8.3.x, например 8.3.20)"
        )
    return v


def prompt_platform_path() -> str:
    """Ask for the 1C install root, suggesting detected OS defaults."""
    candidates = _os_platform_dir_candidates()
    text = "Путь к каталогу установки 1С (содержит shcntx_ru.hbk либо каталоги версий)"
    if candidates:
        default = str(candidates[0])
        return click.prompt(text, default=default, show_default=True).strip()
    return click.prompt(text).strip()


def prompt_version(root: Path) -> str | None:
    """Choose a 1C version. Returns version string, or None to leave unset.

    No prompt when zero or exactly one version is discovered.
    """
    versions = discover_versions(root)
    versioned = [d for d in versions if d.version is not None]
    if not versioned:
        return None
    latest = max(versioned, key=lambda d: d.version)
    latest_str = str(latest.version)
    names = sorted({str(d.version) for d in versioned})
    if len(names) == 1:
        return latest_str
    click.echo("  Обнаружены версии 1С: " + ", ".join(names))
    value = click.prompt(
        "Версия 1С (Enter = последняя, 'auto' = авто-выбор)",
        default=latest_str,
        show_default=True,
        value_proc=_version_proc,
    )
    return value


def confirm_install(summary: str) -> bool:
    """Final yes/no before writing anything."""
    return click.confirm(f"{summary}\nЗаписать изменения?", default=True)


def interact_before_install(
    target: Path,
    server_repo: Path,
    platform_path: str | None,
    platform_version: str | None,
) -> tuple[str, str | None]:
    """Resolve path/version, prompting only for what auto-resolution missed.

    Returns ``(platform_path, platform_version)`` ready for ``run_install``.
    Raises ``InstallerError`` when the user declines to provide a path.
    """
    resolved: str
    try:
        resolved = resolve_platform_path(target, server_repo, platform_path)
    except InstallerError as exc:
        if platform_path:
            raise
        click.echo(click.style(str(exc), fg="yellow"))
        resolved = prompt_platform_path()
        if not discover_versions(Path(resolved)):
            if not click.confirm(
                f"  В {resolved} не найдено HBK/версий 1С. Продолжить всё равно?",
                default=False,
            ):
                raise InstallerError("Установка отменена: каталог платформы не подтверждён.")

    if platform_version is None:
        platform_version = prompt_version(Path(resolved))
    return resolved, platform_version