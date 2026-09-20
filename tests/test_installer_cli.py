"""Tests for the ``install`` / ``uninstall`` subcommands (CliRunner)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from mcp_bsl_context.__main__ import cli
from mcp_bsl_context.installer import SERVER_NAME, auto_resolve_platform_path


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
    monkeypatch.setattr(
        "mcp_bsl_context.installer._os_platform_candidate_dirs", lambda: []
    )
    empty_repo = tmp_path / "repo"
    empty_repo.mkdir()
    result = _run(
        runner, "install", "--project", str(tmp_path), "--repo", str(empty_repo)
    )
    assert result.exit_code != 0
    assert "Platform path not found" in result.output


def _write_platform_root(root, *versions: str) -> None:
    for version in versions:
        d = root / version
        d.mkdir(parents=True, exist_ok=True)
        (d / "shcntx_ru.hbk").write_bytes(b"\x00")


def test_auto_resolve_prefers_bundled_hbk(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _write_platform_root(repo, "8.3.27.72")
    assert auto_resolve_platform_path(server_repo=repo) == str(repo / "8.3.27.72")


def test_auto_resolve_falls_back_to_os_dir(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("mcp_bsl_context.installer._bundled_hbk_dir", lambda _r: None)
    inst_root = tmp_path / "os-root"
    _write_platform_root(inst_root, "8.3.27.72")
    monkeypatch.setattr(
        "mcp_bsl_context.installer._os_platform_candidate_dirs",
        lambda: [inst_root],
    )
    assert auto_resolve_platform_path(server_repo=repo) == str(inst_root)


def test_auto_resolve_skips_empty_os_dir(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("mcp_bsl_context.installer._bundled_hbk_dir", lambda _r: None)
    empty_dir = tmp_path / "empty-os-dir"
    empty_dir.mkdir()
    inst_root = tmp_path / "os-root"
    _write_platform_root(inst_root, "8.3.27.72")
    monkeypatch.setattr(
        "mcp_bsl_context.installer._os_platform_candidate_dirs",
        lambda: [empty_dir, inst_root],
    )
    assert auto_resolve_platform_path(server_repo=repo) == str(inst_root)


def test_auto_resolve_none_when_nothing_found(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("mcp_bsl_context.installer._bundled_hbk_dir", lambda _r: None)
    monkeypatch.setattr(
        "mcp_bsl_context.installer._os_platform_candidate_dirs", lambda: []
    )
    assert auto_resolve_platform_path(server_repo=repo) is None


def test_server_autodetects_platform_without_config(
    runner: CliRunner, tmp_path, monkeypatch
) -> None:
    """`mcp-bsl-context --warmup` without -c resolves platform.path by OS."""
    monkeypatch.delenv("MCP_BSL_PLATFORM_PATH", raising=False)
    monkeypatch.setattr("mcp_bsl_context.installer._bundled_hbk_dir", lambda _r: None)
    inst_root = tmp_path / "os-root"
    _write_platform_root(inst_root, "8.3.27.72")
    monkeypatch.setattr(
        "mcp_bsl_context.installer._os_platform_candidate_dirs",
        lambda: [inst_root],
    )

    calls: dict = {}
    created = {"server": None}

    def _fake_create(config):
        calls["platform_path"] = config.platform.path

        class _FakeServer:
            def run(self, **kwargs):
                calls["run"] = kwargs
                created["server"] = type(self)

        return _FakeServer()

    monkeypatch.setattr("mcp_bsl_context.server.create_server", _fake_create)

    result = _run(runner, "--warmup")
    assert result.exit_code == 0, result.output
    assert calls["platform_path"] == str(inst_root)
    assert calls["run"] == {"transport": "stdio"}