"""Interactive wizard for ``mcp-bsl-context install``.

Engaged only on a real TTY (see ``_want_interactive`` in ``__main__``).
Asks only for values that could not be auto-resolved:

1. platform root — located per the current OS (mac: ~/Applications/1cv8,
   /Applications/1cv8, /opt/1cv8; linux; win), detected install dirs first;
   when several versions are installed they are listed and the user picks one;
2. when nothing is installed — the directory containing the *.hbk help file;
3. 1C version — numbered list + free input with the latest as default
   (``auto`` / empty = leave unset);
4. write confirmation — unless ``--dry-run`` or ``--yes``.

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


def _version_proc(value: str, names: list[str] | None = None) -> str | None:
    """Validate a version answer: empty/'auto', a list index, or a version string."""
    v = value.strip()
    if not v or v.lower() == "auto":
        return None
    if names and v.isdigit():
        idx = int(v)
        if 1 <= idx <= len(names):
            return names[idx - 1]
        raise click.BadParameter(f"номер вне списка (доступно 1–{len(names)})")

    from mcp_bsl_context.domain.value_objects import PlatformVersion

    if PlatformVersion.parse(v) is None:
        raise click.BadParameter(
            f"не распознан формат версии: {v!r} (ожидается 8.3.x, например 8.3.20)"
        )
    return v


def prompt_platform_path() -> str:
    """Ask for a directory that contains a 1C help file (*.hbk).

    Re-asks while the supplied path yields no platform versions. Abort with
    Ctrl-C/Ctrl-D to cancel.
    """
    candidates = _os_platform_dir_candidates()
    default = str(candidates[0]) if candidates else None
    text = "Укажите каталог с файлом справки платформы 1С (*.hbk)"
    while True:
        value = click.prompt(text, default=default, show_default=default is not None)
        path = Path(value.strip()).expanduser()
        if path.is_file() and path.suffix.lower() == ".hbk":
            path = path.parent  # a direct path to the help file is accepted too
        if not path.is_dir():
            click.echo(click.style(f"  ! Не найден каталог: {path}", fg="yellow"))
            continue
        if discover_versions(path):
            return str(path.resolve())
        click.echo(
            click.style(
                f"  ! В {path} не найден файл справки (*.hbk). Укажите каталог "
                "установки 1С либо каталог версии с shcntx_ru.hbk",
                fg="yellow",
            )
        )


def prompt_version(root: Path) -> str | None:
    """Choose a 1C version. Returns version string, or None to leave unset.

    Prints a numbered list; accepts a number, a version string, Enter
    (latest) or ``auto`` (leave unset). No prompt when zero/one version.
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

    click.echo("  Обнаружены версии 1С:")
    for i, name in enumerate(names, 1):
        marker = " (последняя)" if name == latest_str else ""
        click.echo(f"    {i}. {name}{marker}")
    value = click.prompt(
        "Версия 1С (номер, значение или Enter = последняя; 'auto' = авто-выбор)",
        default=latest_str,
        show_default=True,
        value_proc=lambda v: _version_proc(v, names),
    )
    return value


def confirm_install(summary: str) -> bool:
    """Final yes/no before writing anything."""
    return click.confirm(f"{summary}\nЗаписать изменения?", default=True)


def _scan_os_platform_root() -> str | None:
    """First existing OS install root whose discovery yields versions."""
    for cand in _os_platform_dir_candidates():
        if discover_versions(cand):
            click.echo(click.style(f"  Найдена платформа 1С в {cand}", fg="cyan"))
            return str(cand)
    return None


def interact_before_install(
    target: Path,
    server_repo: Path,
    platform_path: str | None,
    platform_version: str | None,
) -> tuple[str, str | None]:
    """Resolve path/version, prompting only for what auto-resolution missed.

    Order:
      1. explicit ``--platform-path`` (no path questions);
      2. OS-aware auto-resolution (install dirs for the current OS);
      3. scan of existing OS roots for one with discovered versions;
      4. otherwise ask for a directory containing the *.hbk help file.

    Returns ``(platform_path, platform_version)`` ready for ``run_install``.
    Raises ``InstallerError`` when the user aborts a prompt.
    """
    resolved: str
    if platform_path:
        resolved = str(Path(platform_path).expanduser().resolve())
    else:
        try:
            candidate = resolve_platform_path(target, server_repo, platform_path)
        except InstallerError as exc:
            click.echo(click.style(str(exc), fg="yellow"))
            candidate = None
        if candidate and discover_versions(Path(candidate)):
            resolved = candidate
        else:
            resolved = _scan_os_platform_root()
            if resolved is None:
                try:
                    resolved = prompt_platform_path()
                except click.Abort as exc:
                    raise InstallerError("Установка отменена.") from exc

    if platform_version is None:
        platform_version = prompt_version(Path(resolved))
    return resolved, platform_version