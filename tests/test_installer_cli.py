"""Tests for the ``install`` / ``uninstall`` subcommands (CliRunner)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from mcp_bsl_context.__main__ import cli
from mcp_bsl_context.installer import SERVER_NAME


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _run(runner: CliRunner, *args: str):
    return runner.invoke(cli, list(args), catch_exceptions=False)


def test_help_lists_subcommands(runner: CliRunner) -> None:
    result = _run(runner, "--help")
    assert result.exit_code == 0
    assert "install" in result.output
    assert "uninstall" in result.output


def test_install_dry_run_writes_nothing(
    runner: CliRunner, tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("MCP_BSL_PLATFORM_PATH", raising=False)
    result = _run(
        runner,
        "install",
        "--project", str(tmp_path),
        "--platform-path", str(tmp_path / "platform"),
        "--dry-run",
    )
    assert result.exit_code == 0
    assert "platform:" in result.output
    assert "[created  ]" in result.output or "created" in result.output
    assert list(tmp_path.iterdir()) == []


def test_install_then_idempotent(runner: CliRunner, tmp_path) -> None:
    platform = str(tmp_path / "platform-1c")
    result = _run(
        runner, "install", "--project", str(tmp_path), "--platform-path", platform
    )
    assert result.exit_code == 0

    cfg = tmp_path / "config.yml"
    assert cfg.is_file()
    cfg_text = cfg.read_text(encoding="utf-8")
    assert f"path: {json.dumps(platform)}" in cfg_text
    assert "mode: stdio" in cfg_text
    assert str(tmp_path / "data" / "qdrant") in cfg_text

    targets = [tmp_path / "AGENTS.md", tmp_path / "CLAUDE.md"]
    for doc in targets:
        assert "MCP-BSL-CONTEXT:START" in doc.read_text(encoding="utf-8")

    oc = tmp_path / "opencode.jsonc"
    assert oc.is_file()
    assert SERVER_NAME in json.loads(oc.read_text(encoding="utf-8"))["mcp"]

    mcp = tmp_path / ".mcp.json"
    assert mcp.is_file()
    assert SERVER_NAME in json.loads(mcp.read_text(encoding="utf-8"))["mcpServers"]

    # Idempotent second run.
    result2 = _run(
        runner, "install", "--project", str(tmp_path), "--platform-path", platform
    )
    assert result2.exit_code == 0
    assert "unchanged" in result2.output or "already up to date" in result2.output
    assert "created" not in result2.output.replace("unchanged", "")


def test_install_merges_existing_opencode_jsonc(
    runner: CliRunner, tmp_path
) -> None:
    oc = tmp_path / "opencode.jsonc"
    oc.write_text(
        '{\n  // keep this comment\n  "mcp": {"other": {"type": "local"}}\n}\n',
        encoding="utf-8",
    )
    result = _run(
        runner,
        "install",
        "--project", str(tmp_path),
        "--platform-path", str(tmp_path / "platform"),
    )
    assert result.exit_code == 0
    obj = json.loads(oc.read_text(encoding="utf-8"))
    assert "other" in obj["mcp"]
    assert SERVER_NAME in obj["mcp"]


def test_install_creates_only_requested_scope(
    runner: CliRunner, tmp_path
) -> None:
    result = _run(
        runner,
        "install",
        "--project", str(tmp_path),
        "--platform-path", str(tmp_path / "platform"),
        "--opencode-only",
    )
    assert result.exit_code == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "opencode.jsonc").exists()
    assert not (tmp_path / ".mcp.json").exists()


def test_uninstall_roundtrip(runner: CliRunner, tmp_path) -> None:
    platform = str(tmp_path / "platform-1c")
    _run(runner, "install", "--project", str(tmp_path), "--platform-path", platform)

    dry = _run(
        runner, "uninstall", "--project", str(tmp_path), "--dry-run"
    )
    assert dry.exit_code == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".mcp.json").exists()

    result = _run(runner, "uninstall", "--project", str(tmp_path))
    assert result.exit_code == 0

    oc = tmp_path / "opencode.jsonc"
    assert oc.exists()
    obj = json.loads(oc.read_text(encoding="utf-8"))
    assert "mcp" not in obj or SERVER_NAME not in obj["mcp"]

    assert not (tmp_path / ".mcp.json").exists()
    assert (tmp_path / "config.yml").exists()  # left as-is
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_install_missing_target_fails(runner: CliRunner, tmp_path) -> None:
    result = _run(
        runner, "install", "--project", str(tmp_path / "nope"), "--dry-run"
    )
    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_install_without_platform_hints(
    runner: CliRunner, tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("MCP_BSL_PLATFORM_PATH", raising=False)
    monkeypatch.setattr("mcp_bsl_context.installer.COMMON_PLATFORM_DIRS", [])
    empty_repo = tmp_path / "repo"
    empty_repo.mkdir()
    result = _run(
        runner, "install", "--project", str(tmp_path), "--repo", str(empty_repo)
    )
    assert result.exit_code != 0
    assert "Platform path not found" in result.output