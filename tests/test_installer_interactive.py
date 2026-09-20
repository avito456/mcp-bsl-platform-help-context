"""Tests for the interactive ``install`` wizard (CliRunner)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from mcp_bsl_context.__main__ import cli
from mcp_bsl_context.installer import _os_platform_candidate_dirs


def _write_version(root, version: str, with_bin: bool = False) -> None:
    """Create a fake version dir with an HBK file at platform install root."""
    d = root / version
    d.mkdir(parents=True, exist_ok=True)
    target = d / "bin" if with_bin else d
    target.mkdir(exist_ok=True)
    (target / "shcntx_ru.hbk").write_bytes(b"\x00")


@pytest.fixture(autouse=True)
def wizard(monkeypatch):
    """Simulate an interactive terminal, honouring --yes/--non-interactive."""

    def _want_interactive(yes: bool, non_interactive: bool) -> bool:
        return not yes and not non_interactive

    monkeypatch.setattr("mcp_bsl_context.__main__._want_interactive", _want_interactive)


@pytest.fixture(autouse=True)
def no_platform_hints(monkeypatch, tmp_path) -> None:
    """Prevent auto-resolution from the environment/built-in hbk/repo."""
    monkeypatch.delenv("MCP_BSL_PLATFORM_PATH", raising=False)
    monkeypatch.setattr("mcp_bsl_context.installer.COMMON_PLATFORM_DIRS", [])


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _empty_repo(tmp_path):
    repo = tmp_path / "empty-repo"
    repo.mkdir()
    return str(repo)


def test_wizard_picks_version_from_two(tmp_path, runner, wizard, no_platform_hints) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.20.1234", with_bin=True)
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        ["install", "--project", str(tmp_path), "--repo", _empty_repo(tmp_path)],
        input=f"{root}\n8.3.20\ny\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "config.yml").read_text(encoding="utf-8")
    assert f"path: {json.dumps(str(root))}" in cfg
    assert 'version: "8.3.20"' in cfg
    assert "Обнаружены версии 1С" in result.output


def test_wizard_single_version_no_version_prompt(tmp_path, runner, wizard, no_platform_hints) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        ["install", "--project", str(tmp_path), "--repo", _empty_repo(tmp_path)],
        input=f"{root}\ny\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "config.yml").read_text(encoding="utf-8")
    assert 'version: "8.3.27"' in cfg
    assert "Обнаружены версии 1С" not in result.output


def test_wizard_path_flag_skips_path_prompt(tmp_path, runner, wizard) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        ["install", "--project", str(tmp_path), "--platform-path", str(root)],
        input="y\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "config.yml").read_text(encoding="utf-8")
    assert f"path: {json.dumps(str(root))}" in cfg
    assert 'version: "8.3.27"' in cfg


def test_wizard_version_flag_wins(tmp_path, runner, wizard) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.20.1234", with_bin=True)
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        [
            "install",
            "--project", str(tmp_path),
            "--platform-path", str(root),
            "--platform-version", "8.3.20",
        ],
        input="y\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "config.yml").read_text(encoding="utf-8")
    assert 'version: "8.3.20"' in cfg
    assert "Обнаружены версии 1С" not in result.output


def test_wizard_auto_version_leaves_unset(tmp_path, runner, wizard, no_platform_hints) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.20.1234", with_bin=True)
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        ["install", "--project", str(tmp_path), "--repo", _empty_repo(tmp_path)],
        input=f"{root}\nauto\ny\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "version: null" in (tmp_path / "config.yml").read_text(encoding="utf-8")


def test_wizard_invalid_version_reprompts(tmp_path, runner, wizard, no_platform_hints) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.20.1234", with_bin=True)
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        ["install", "--project", str(tmp_path), "--repo", _empty_repo(tmp_path)],
        input=f"{root}\nnot-a-version\n8.3.20\ny\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "config.yml").read_text(encoding="utf-8")
    assert 'version: "8.3.20"' in cfg
    assert "Error" in result.output


def test_wizard_cancel_on_negative_confirm(tmp_path, runner, wizard, no_platform_hints) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.20.1234", with_bin=True)
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        ["install", "--project", str(tmp_path), "--repo", _empty_repo(tmp_path)],
        input=f"{root}\n8.3.20\nn\n",
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    assert not (tmp_path / "config.yml").exists()
    assert not (tmp_path / "opencode.jsonc").exists()


def test_yes_skips_wizard(tmp_path, runner, wizard, no_platform_hints) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.20.1234", with_bin=True)
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        ["install", "--project", str(tmp_path), "--platform-path", str(root), "--yes"],
        input="",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "config.yml").read_text(encoding="utf-8")
    assert "version: null" in cfg  # wizard skipped -> version not resolved


def test_non_interactive_fails_when_unresolved(tmp_path, runner, wizard, no_platform_hints) -> None:
    result = runner.invoke(
        cli,
        ["install", "--project", str(tmp_path), "--repo", _empty_repo(tmp_path), "--non-interactive"],
        input="",
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    assert "Platform path not found" in result.output


def test_non_interactive_writes_when_resolved(tmp_path, runner, wizard) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.20.1234", with_bin=True)
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        ["install", "--project", str(tmp_path), "--platform-path", str(root), "--non-interactive"],
        input="",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "config.yml").read_text(encoding="utf-8")
    assert "version: null" in cfg


def test_non_interactive_with_version_flag(tmp_path, runner, wizard) -> None:
    root = tmp_path / "pf"
    _write_version(root, "8.3.20.1234", with_bin=True)
    _write_version(root, "8.3.27.72")
    result = runner.invoke(
        cli,
        [
            "install",
            "--project", str(tmp_path),
            "--platform-path", str(root),
            "--platform-version", "8.3.20",
            "--non-interactive",
        ],
        input="",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert 'version: "8.3.20"' in (tmp_path / "config.yml").read_text(encoding="utf-8")


def test_os_candidate_dirs_per_platform(tmp_path, monkeypatch) -> None:
    import pathlib

    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: pathlib.Path(tmp_path)))

    monkeypatch.setattr("sys.platform", "linux")
    linux = _os_platform_candidate_dirs()
    assert [p.name for p in linux] == ["x86_64", "1cv8"]

    monkeypatch.setattr("sys.platform", "win32")
    win = _os_platform_candidate_dirs()
    assert [str(p) for p in win] == [
        "C:/Program Files/1cv8",
        "C:/Program Files (x86)/1cv8",
    ]

    monkeypatch.setattr("sys.platform", "darwin")
    darwin = _os_platform_candidate_dirs()
    assert darwin[0] == tmp_path / "Applications/1cv8"
    assert [p.name for p in darwin] == ["1cv8", "1cv8", "1cv8"]