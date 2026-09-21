"""CLI entry point for the MCP BSL platform context server.

``mcp-bsl-context`` starts the server (default) and also provides the
``install`` / ``uninstall`` subcommands that register the server in a
target project (opencode + Claude Code, project scope).
"""

from __future__ import annotations

import click
import sys
from pathlib import Path

from mcp_bsl_context import installer
from mcp_bsl_context.installer import InstallerError

from mcp_bsl_context.logging_setup import get_logger

logger = get_logger(__name__)


def _resolve_target(project: str | None) -> Path:
    if project:
        target = Path(project).expanduser().resolve()
    else:
        target = Path.cwd().resolve()
    if not target.is_dir():
        raise InstallerError(f"Target directory does not exist: {target}")
    return target


def _run_server(
    config: str | None,
    platform_path: str | None,
    platform_version: str | None,
    mode: str | None,
    port: int | None,
    data_source: str | None,
    json_path: str | None,
    verbose: bool | None,
    reindex: bool | None,
    warmup: bool | None,
) -> None:
    from mcp_bsl_context.config import load_config
    from mcp_bsl_context.logging_setup import log_ai_models, setup_logging

    # Build CLI overrides dict (None values are skipped by load_config)
    cli_overrides = {
        "platform.path": platform_path,
        "platform.version": platform_version,
        "platform.data_source": data_source,
        "platform.json_path": json_path,
        "server.mode": mode,
        "server.port": port,
        "server.verbose": verbose,
        "index.reindex": reindex,
        "index.warmup": warmup,
    }

    app_config = load_config(config_path=config, cli_overrides=cli_overrides)

    setup_logging(app_config)
    # Auto-resolve the platform path when it is not configured (hbk source):
    # bundled HBK in the server repo / OS install dirs first.
    if (
        app_config.platform.data_source == "hbk"
        and not app_config.platform.path
    ):
        auto = installer.auto_resolve_platform_path()
        if auto:
            app_config.platform.path = auto
            logger.info("Auto-resolved platform.path: {}", auto)

    from mcp_bsl_context.config import ConfigValidationError

    try:
        app_config.validate()
    except ConfigValidationError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    log_ai_models(app_config)

    from mcp_bsl_context.server import create_server

    server = create_server(app_config)

    if app_config.server.mode == "stdio":
        server.run(transport="stdio")
    else:
        server.run(
            transport=app_config.server.mode,
            host=app_config.server.host,
            port=app_config.server.port,
        )


def _want_interactive(yes: bool, non_interactive: bool) -> bool:
    """Interactive wizard runs only on a real TTY unless explicitly disabled."""
    return not yes and not non_interactive and sys.stdin.isatty()


def _run_install(
    project: str | None,
    platform_path: str | None,
    platform_version: str | None,
    repo: str | None,
    scope: installer.Scope,
    dry_run: bool,
    yes: bool,
    non_interactive: bool,
) -> None:
    target = _resolve_target(project)
    server_repo = installer.resolve_server_repo(repo)
    dry_run_label = " (dry run, nothing written)" if dry_run else ""
    click.echo(f"Installing '{installer.SERVER_NAME}' into {target}{dry_run_label}\n")

    if _want_interactive(yes, non_interactive):
        from mcp_bsl_context.interactive import confirm_install, interact_before_install

        platform_path, platform_version = interact_before_install(
            target, server_repo, platform_path, platform_version
        )
        if not dry_run and not yes:
            summary = f"  платформа: {platform_path}"
            if platform_version:
                summary += f"  (версия {platform_version})"
            summary += "\n  клиенты: opencode + claude"
            if not confirm_install(summary):
                raise click.ClickException("Установка отменена.")

    actions = installer.run_install(
        target,
        server_repo,
        platform_path,
        scope,
        dry_run,
        platform_version=platform_version,
    )
    click.echo()
    installer._print_actions(actions)
    if not dry_run:
        installer._print_verification(scope)


def _run_uninstall(project: str | None, scope: installer.Scope, dry_run: bool) -> None:
    target = _resolve_target(project)
    dry_run_label = " (dry run, nothing written)" if dry_run else ""
    click.echo(f"Uninstalling '{installer.SERVER_NAME}' from {target}{dry_run_label}\n")
    actions = installer.run_uninstall(target, scope, dry_run)
    click.echo()
    installer._print_actions(actions)


@click.group(invoke_without_command=True)
@click.option(
    "--config", "-c",
    default=None,
    help="Path to YAML config file",
)
@click.option(
    "--platform-path", "-p",
    required=False,
    default=None,
    help="Path to 1C platform installation directory (overrides config/env)",
)
@click.option(
    "--platform-version",
    default=None,
    help="Preferred platform version, e.g. '8.3.20'. Picks closest available. (overrides config/env)",
)
@click.option(
    "--mode", "-m",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    default=None,
    help="Transport mode: stdio, sse, or streamable-http (overrides config/env)",
)
@click.option(
    "--port",
    type=int,
    default=None,
    help="Port for HTTP server (overrides config/env)",
)
@click.option(
    "--data-source",
    type=click.Choice(["hbk", "json"]),
    default=None,
    help="Data source: 'hbk' or 'json' (overrides config/env)",
)
@click.option(
    "--json-path",
    default=None,
    help="Path to directory with pre-exported JSON files (overrides config/env)",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=None,
    help="Enable debug logging (overrides config/env)",
)
@click.option(
    "--reindex",
    is_flag=True,
    default=None,
    help="Force rebuild of the semantic index from the HBK file on startup "
    "(overrides config/env)",
)
@click.option(
    "--warmup",
    is_flag=True,
    default=None,
    help="Load semantic models and prepare the index at startup (no rebuild; "
    "overrides config/env)",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: str | None,
    platform_path: str | None,
    platform_version: str | None,
    mode: str | None,
    port: int | None,
    data_source: str | None,
    json_path: str | None,
    verbose: bool | None,
    reindex: bool | None,
    warmup: bool | None,
) -> None:
    """MCP server for 1C:Enterprise BSL platform context.

    Provide AI assistants with search and navigation across 1C platform API
    documentation (methods, properties, types).

    Default command: start the server.

    \b
    Subcommands:
      install    - register the MCP server in a target project.
      uninstall  - remove the installer's own changes from a target project.

    Configuration priority: YAML config < env vars (MCP_BSL_*) < CLI arguments.
    """
    if ctx.invoked_subcommand is not None:
        return
    _run_server(
        config,
        platform_path,
        platform_version,
        mode,
        port,
        data_source,
        json_path,
        verbose,
        reindex,
        warmup,
    )


@cli.command("install")
@click.option(
    "--project",
    default=None,
    help="Target project directory. Default: current working directory.",
)
@click.option(
    "--platform-path",
    default=None,
    help="1C platform installation directory (HBK source). Overrides "
    "MCP_BSL_PLATFORM_PATH and existing config.yml.",
)
@click.option(
    "--platform-version",
    default=None,
    help="Preferred 1C platform version (e.g. '8.3.20'); written into "
    "generated config.yml. 'auto'/omitted = runtime picks the latest.",
)
@click.option(
    "--repo",
    default=None,
    help="Server repository path (used in 'uv run --project <repo>'). "
    "Default: this package's project root.",
)
@click.option(
    "--opencode-only",
    "scope",
    flag_value="opencode",
    default=None,
    help="Only opencode.",
)
@click.option(
    "--claude-only",
    "scope",
    flag_value="claude",
    default=None,
    help="Only Claude Code.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview changes, write nothing.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Accept all defaults, never prompt.",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Never prompt (for CI/scripts): fail if a value cannot be auto-resolved.",
)
def install(
    project: str | None,
    platform_path: str | None,
    platform_version: str | None,
    repo: str | None,
    scope: installer.Scope,
    dry_run: bool,
    yes: bool,
    non_interactive: bool,
) -> None:
    """Register 'bsl-context-1c' in a target project (project scope).

    On an interactive terminal a wizard asks only for values that could not
    be resolved automatically.
    """
    try:
        _run_install(
            project, platform_path, platform_version, repo, scope, dry_run, yes, non_interactive
        )
    except InstallerError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command("uninstall")
@click.option(
    "--project",
    default=None,
    help="Target project directory. Default: current working directory.",
)
@click.option(
    "--opencode-only",
    "scope",
    flag_value="opencode",
    default=None,
    help="Only opencode.",
)
@click.option(
    "--claude-only",
    "scope",
    flag_value="claude",
    default=None,
    help="Only Claude Code.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview changes, write nothing.",
)
def uninstall(
    project: str | None,
    scope: installer.Scope,
    dry_run: bool,
) -> None:
    """Remove the installer's own changes from a target project."""
    try:
        _run_uninstall(project, scope, dry_run)
    except InstallerError as exc:
        raise click.ClickException(str(exc)) from exc


def main() -> None:
    cli()


if __name__ == "__main__":
    main()