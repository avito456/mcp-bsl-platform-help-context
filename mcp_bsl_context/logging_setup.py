"""Centralized loguru logging setup.

All application logs go to **stderr**: stdout is the JSON-RPC channel for the
stdio MCP transport, so writing logs there would corrupt the protocol. An
optional file sink (with rotation/retention) can be enabled through the
``logging`` config section or the ``MCP_BSL_LOG_*`` environment variables.

This module is the single place that configures sinks; every module obtains a
logger through :func:`get_logger`, which binds the module name so the log
format ``{extra[module]}`` always resolves.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger

    from mcp_bsl_context.config import AppConfig

LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} [{level}] {extra[module]}: {message}"

# Third-party loggers routed into loguru by the intercept handler.
INTERCEPTED_LOGGERS = (
    "mcp",
    "httpx",
    "httpcore",
    "sentence_transformers",
    "transformers",
    "qdrant_client",
    "urllib3",
)

# Chatty during the MCP handshake; kept at WARNING unless verbose.
QUIET_LOGGERS = ("mcp.server.lowlevel.server",)


class InterceptHandler(logging.Handler):
    """Forward stdlib ``logging`` records to loguru.

    Keeps third-party libraries (MCP SDK, httpx, sentence-transformers, …)
    on the same sink and format as the rest of the application without
    requiring changes in those libraries.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).bind(
            module=record.name
        ).log(level, record.getMessage())


def get_logger(name: str) -> "Logger":
    """Return a module-bound logger.

    ``name`` is normally ``__name__``; it is exposed in the log format via
    ``{extra[module]}``.
    """
    return logger.bind(module=name)


def setup_logging(config: AppConfig) -> None:
    """Configure loguru sinks from the application config.

    Replaces the default loguru handler, adds a stderr sink, optionally adds
    a rotating file sink, and routes stdlib logging into loguru.
    """
    verbose = bool(getattr(getattr(config, "server", None), "verbose", False))
    level = "DEBUG" if verbose else "INFO"

    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=LOG_FORMAT,
        colorize=sys.stderr.isatty(),
        backtrace=verbose,
        diagnose=False,
    )

    _add_file_sink(config, default_level=level, verbose=verbose)
    _install_intercept(verbose)


def _add_file_sink(
    config: AppConfig, default_level: str, verbose: bool
) -> None:
    """Add a rotating file sink when a log file path is configured."""
    log_config: Any = getattr(config, "logging", None)
    file_path = getattr(log_config, "file", None) if log_config else None
    if not file_path:
        return

    rotation = getattr(log_config, "rotation", None) or "10 MB"
    retention = getattr(log_config, "retention", None) or "7 days"
    file_level = getattr(log_config, "level", None) or default_level

    logger.add(
        str(file_path),
        level=file_level,
        format=LOG_FORMAT,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        backtrace=verbose,
        diagnose=False,
    )


def _install_intercept(verbose: bool) -> None:
    """Route stdlib logging into loguru and quiet noisy libraries."""
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in INTERCEPTED_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    if not verbose:
        for name in QUIET_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
