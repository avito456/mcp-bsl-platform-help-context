"""Tests for the centralized loguru logging setup."""

from __future__ import annotations

from loguru import logger

from mcp_bsl_context.config import AppConfig
from mcp_bsl_context.logging_setup import (
    _normalize_level,
    get_logger,
    log_ai_models,
    setup_logging,
)


def _capture(level: str = "DEBUG") -> list[str]:
    """Install an in-memory loguru sink and return the collected records."""
    logger.remove()
    records: list[str] = []
    logger.add(records.append, format="{level}|{message}", level=level)
    return records


class TestLogAiModels:
    def test_logs_summary_fields(self):
        records = _capture("DEBUG")
        log_ai_models(AppConfig())
        text = "\n".join(records)
        assert "AI models: search mode=hybrid, data source=hbk" in text
        assert "Embeddings: provider=local" in text
        assert "ai-forever/ru-en-RoSBERTa" in text
        assert "Reranker: enabled" in text
        assert "Storage: qdrant_path=./data/qdrant" in text
        assert "Index flags: reindex=False, warmup=False" in text

    def test_never_logs_api_key(self):
        records = _capture("DEBUG")
        config = AppConfig()
        config.embeddings.api_key = "SUPER-SECRET-KEY"
        config.reranker.api_key = "OTHER-SECRET"
        log_ai_models(config)
        text = "\n".join(records)
        assert "SUPER-SECRET-KEY" not in text
        assert "OTHER-SECRET" not in text
        assert "api_key=***" in text

    def test_connection_details_are_debug_only(self):
        config = AppConfig()
        config.embeddings.api_url = "https://api.example.com/v1"

        info_records = _capture("INFO")
        log_ai_models(config)
        assert "api_url" not in "\n".join(info_records)

        debug_records = _capture("DEBUG")
        log_ai_models(config)
        assert "api_url=https://api.example.com/v1" in "\n".join(debug_records)

    def test_reranker_disabled(self):
        records = _capture("DEBUG")
        config = AppConfig()
        config.reranker.enabled = False
        log_ai_models(config)
        assert any("Reranker: disabled" in record for record in records)


class TestSetupLogging:
    def test_logs_go_to_stderr_not_stdout(self, capsys):
        setup_logging(AppConfig())
        get_logger("tests").info("hello-stderr")
        logger.remove()

        captured = capsys.readouterr()
        assert captured.out == "", "logs must never reach stdout (stdio MCP)"
        assert "hello-stderr" in captured.err

    def test_file_sink_creates_file(self, tmp_path):
        log_file = tmp_path / "app.log"
        config = AppConfig()
        config.logging.file = str(log_file)
        config.logging.level = "DEBUG"

        setup_logging(config)
        get_logger("tests").info("hello-file")
        logger.remove()

        assert "hello-file" in log_file.read_text(encoding="utf-8")

    def test_file_sink_disabled_by_default(self, tmp_path):
        setup_logging(AppConfig())
        logger.remove()
        assert list(tmp_path.iterdir()) == []

    def test_stderr_is_colored_by_default(self, capsys):
        setup_logging(AppConfig())
        get_logger("tests").info("colored-line")
        logger.remove()
        assert "\x1b[" in capsys.readouterr().err

    def test_stderr_colorize_can_be_disabled(self, capsys):
        config = AppConfig()
        config.logging.colorize = False
        setup_logging(config)
        get_logger("tests").info("plain-line")
        logger.remove()
        err = capsys.readouterr().err
        assert "\x1b[" not in err
        assert "plain-line" in err

    def test_file_output_has_no_ansi(self, tmp_path):
        log_file = tmp_path / "plain.log"
        config = AppConfig()
        config.logging.file = str(log_file)
        setup_logging(config)
        get_logger("tests").info("file-plain")
        logger.remove()
        assert "\x1b[" not in log_file.read_text(encoding="utf-8")


class TestNormalizeLevel:
    def test_accepts_case_insensitive_standard_level(self):
        assert _normalize_level("debug", "INFO") == "DEBUG"

    def test_falls_back_on_invalid_level(self):
        assert _normalize_level("verbose", "INFO") == "INFO"

    def test_uses_fallback_when_none(self):
        assert _normalize_level(None, "WARNING") == "WARNING"
