#!/usr/bin/env python3
"""Install the ``mcp-bsl-context`` MCP server into a 1C project (or this repo).

Registers the server (project scope) in the target project and adds the
AI-agent usage guide (tools description) to its AGENTS.md / CLAUDE.md.

Targets:
  - opencode  -> opencode.jsonc   (mcp."bsl-context", type=local)
  - Claude Code -> .mcp.json      (mcpServers."bsl-context", type=stdio)

The target project is ``--project <path>`` or the current working directory.
The server repository is derived from this script's location.

Only stdlib is used, so it also runs on any Python 3.10+ without a venv (e.g.
``python3 scripts/install-mcp.py``).

Examples (run from the repository root):

  uv run scripts/install-mcp.py                          # install into cwd
  uv run scripts/install-mcp.py --project ../my-1c-app   # install into a project
  uv run scripts/install-mcp.py --dry-run                # preview, write nothing
  uv run scripts/install-mcp.py --uninstall              # remove own changes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SERVER_NAME = "bsl-context"
MARKER_START = "<!-- MCP-BSL-CONTEXT:START -->"
MARKER_END = "<!-- MCP-BSL-CONTEXT:END -->"
OPENCODE_SCHEMA = "https://opencode.ai/config.json"

COMMON_PLATFORM_DIRS = [
    "/opt/1cv8/x86_64",
    "/opt/1cv8",
    "C:/Program Files/1cv8",
    "C:/Program Files (x86)/1cv8",
]


class _Color:
    """Minimal ANSI coloring (disabled when not a tty)."""

    @staticmethod
    def _enabled() -> bool:
        return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    _ok = "\x1b[32m"
    _warn = "\x1b[33m"
    _reset = "\x1b[0m"

    @staticmethod
    def ok(msg: str) -> str:
        return f"{_Color._ok}{msg}{_Color._reset}" if _Color._enabled() else msg

    @staticmethod
    def warn(msg: str) -> str:
        return f"{_Color._warn}{msg}{_Color._reset}" if _Color._enabled() else msg


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# JSON / JSONC helpers
# ---------------------------------------------------------------------------


def _strip_jsonc_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments (string-content aware)."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _read_jsonc(path: Path) -> tuple[object, bool]:
    """Read JSON or JSONC into an object. Returns (obj, had_comments)."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text), False
    except json.JSONDecodeError:
        stripped = _strip_jsonc_comments(text)
        return json.loads(stripped), True


def _dump_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Platform path resolution
# ---------------------------------------------------------------------------


def _extract_platform_path(text: str) -> str | None:
    header = re.search(r"(?m)^\s*platform:\s*$", text)
    if not header:
        return None
    start = header.end()
    end = len(text)
    for nxt in re.finditer(r"(?m)^\S.*$", text[start:]):
        end = start + nxt.start()
        break
    block = text[start:end]
    pm = re.search(r'(?m)^\s*path:\s*(?:"(.*?)"|\'(.*?)\'|(\S.*?))\s*$', block)
    if not pm:
        return None
    return pm.group(1) or pm.group(2) or pm.group(3)


def _read_existing_config_platform(target: Path) -> str | None:
    cfg = target / "config.yml"
    if not cfg.is_file():
        return None
    return _extract_platform_path(cfg.read_text(encoding="utf-8"))


def _bundled_hbk_dir(server_repo: Path) -> Path | None:
    for cand in sorted(server_repo.glob("*")):
        if cand.is_dir() and (cand / "shcntx_ru.hbk").is_file():
            return cand
    return None


def resolve_platform_path(target: Path, server_repo: Path, cli_path: str | None) -> str:
    if cli_path:
        return str(Path(cli_path).expanduser().resolve())
    env = os.environ.get("MCP_BSL_PLATFORM_PATH")
    if env:
        return str(Path(env).expanduser().resolve())
    existing = _read_existing_config_platform(target)
    if existing:
        return existing
    bundled = _bundled_hbk_dir(server_repo)
    if bundled:
        return str(bundled)
    for cand in COMMON_PLATFORM_DIRS:
        p = Path(cand)
        if p.is_dir():
            return str(p)
    raise SystemExit(
        _Color.warn(
            "Platform path not found. Pass it explicitly:\n"
            "  uv run scripts/install-mcp.py --platform-path /opt/1cv8/x86_64\n"
            "or set MCP_BSL_PLATFORM_PATH."
        )
    )


# ---------------------------------------------------------------------------
# Section insert/remove in AGENTS.md / CLAUDE.md
# ---------------------------------------------------------------------------


def _applications(flags, target: Path) -> list[Path]:
    files: list[Path] = []
    if flags.opencode_only:
        files.append(target / "AGENTS.md")
    elif flags.claude_only:
        files.append(target / "CLAUDE.md")
    else:
        files += [target / "AGENTS.md", target / "CLAUDE.md"]
    return files


def insert_section(path: Path, section: str, dry_run: bool, actions: list) -> bool:
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if MARKER_START in text:
            start = text.index(MARKER_START)
            end = text.index(MARKER_END) + len(MARKER_END)
            new_text = text[:start] + section.rstrip() + text[end:]
            changed = new_text != text
            if changed:
                if not dry_run:
                    path.write_text(new_text, encoding="utf-8")
                actions.append(("update", path, "section refreshed"))
            else:
                actions.append(("skip", path, "section already up to date"))
            return True
        prefix = text if text.endswith("\n\n") else (text if not text else text.rstrip() + "\n\n")
        new_text = prefix + section + "\n"
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")
        actions.append(("write", path, "section appended"))
        return True
    _ensure_parent(path)
    if not dry_run:
        path.write_text(section + "\n", encoding="utf-8")
    actions.append(("write", path, "file created with tools section"))
    return True


def remove_section(path: Path, dry_run: bool, actions: list) -> None:
    if not path.is_file():
        actions.append(("skip", path, "not found"))
        return
    text = path.read_text(encoding="utf-8")
    if MARKER_START not in text or MARKER_END not in text:
        actions.append(("skip", path, "no tools section"))
        return
    start = text.index(MARKER_START)
    end = text.index(MARKER_END) + len(MARKER_END)
    new_text = (text[:start] + text[end:]).strip("\n")
    if not new_text.strip():
        new_text = ""  # section was the only content — drop the file
    if not dry_run:
        if new_text:
            path.write_text(new_text + "\n", encoding="utf-8")
        else:
            path.unlink()
    actions.append(("remove", path, "tools section removed"))


# ---------------------------------------------------------------------------
# Config files
# ---------------------------------------------------------------------------


def generate_config(target: Path, platform_path: str, example: Path, dry_run: bool, actions: list) -> None:
    cfg = target / "config.yml"
    if cfg.exists():
        actions.append(("skip", cfg, "already exists, left as-is"))
        return
    if not example.is_file():
        raise SystemExit(_Color.warn(f"config.example.yml not found: {example}"))
    text = example.read_text(encoding="utf-8")

    pm = re.search(r'(?m)^(\s*)path:\s*"[^"]*"\s*$', text)
    if not pm:
        raise SystemExit(_Color.warn(f"config.example.yml: platform 'path:' line not found"))
    text = text[: pm.start()] + f'{pm.group(1)}path: {json.dumps(platform_path)}' + text[pm.end() :]

    # MCP clients (opencode/Claude Code) spawn the server over stdio —
    # force server.mode: stdio regardless of the example default.
    server_header = text.find("server:")
    sm = None
    if server_header != -1:
        server_block = text[server_header: text.find("platform:", server_header)]
        sm = re.search(r'(?m)^(\s*)mode:\s*\S+(\s*#.*)?$', server_block)
    if sm:
        start = server_header + sm.start()
        end = server_header + sm.end()
        text = text[:start] + f'{sm.group(1)}mode: stdio{sm.group(2) or ""}' + text[end:]
    else:
        _eprint(_Color.warn("  ! 'server.mode' not set to stdio in generated config.yml"))

    replacements = [
        ("qdrant_path: ./data/qdrant", f"qdrant_path: {json.dumps(str(target / 'data' / 'qdrant'))}"),
        ("models_cache: ./data/models", f"models_cache: {json.dumps(str(target / 'data' / 'models'))}"),
    ]
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
        else:
            _eprint(_Color.warn(f"  ! pattern not found in config.example.yml: {old!r}"))

    _ensure_parent(cfg)
    if not dry_run:
        cfg.write_text(text, encoding="utf-8")
    actions.append(("write", cfg, f"generated (platform={platform_path})"))


def _opencode_command(server_repo: Path, target: Path) -> list[str]:
    return [
        "uv", "run", "--project", str(server_repo),
        "mcp-bsl-context", "-c", str(target / "config.yml"),
    ]


def _claude_entry(server_repo: Path, target: Path) -> dict:
    return {
        "type": "stdio",
        "command": "uv",
        "args": ["run", "--project", str(server_repo),
                 "mcp-bsl-context", "-c", str(target / "config.yml")],
    }


def install_opencode(server_repo: Path, target: Path, dry_run: bool, actions: list) -> None:
    path = target / "opencode.jsonc"
    entry = {
        "type": "local",
        "command": _opencode_command(server_repo, target),
        "cwd": str(target),
        "enabled": True,
    }
    if not path.exists():
        obj = {"$schema": OPENCODE_SCHEMA, "mcp": {SERVER_NAME: entry}}
        _ensure_parent(path)
        if not dry_run:
            _dump_json(path, obj)
        actions.append(("write", path, f"mcp.{SERVER_NAME} registered (new file)"))
        return
    obj, had_comments = _read_jsonc(path)
    mcp = obj.setdefault("mcp", {})
    if mcp.get(SERVER_NAME) == entry:
        actions.append(("skip", path, f"mcp.{SERVER_NAME} already registered"))
        return
    mcp[SERVER_NAME] = entry
    _ensure_parent(path)
    if not dry_run:
        _dump_json(path, obj)
    verb = "write"
    msg = f"mcp.{SERVER_NAME} registered"
    if had_comments:
        _eprint(_Color.warn(f"  ! {path.name} contains JSONC comments; rewritten as strict JSON"))
    actions.append((verb, path, msg))


def remove_opencode(target: Path, dry_run: bool, actions: list) -> None:
    path = target / "opencode.jsonc"
    if not path.is_file():
        actions.append(("skip", path, "not found"))
        return
    obj, had_comments = _read_jsonc(path)
    mcp = obj.get("mcp")
    new_mcp = mcp.get(SERVER_NAME) if isinstance(mcp, dict) else None
    if not isinstance(mcp, dict) or new_mcp is None:
        actions.append(("skip", path, f"mcp.{SERVER_NAME} not registered"))
        return
    del mcp[SERVER_NAME]
    if not mcp:
        del obj["mcp"]
    if not dry_run:
        _dump_json(path, obj)
    actions.append(("remove", path, f"mcp.{SERVER_NAME} unregistered"))


def install_claude(server_repo: Path, target: Path, dry_run: bool, actions: list) -> None:
    path = target / ".mcp.json"
    entry = _claude_entry(server_repo, target)
    if not path.exists():
        obj = {"mcpServers": {SERVER_NAME: entry}}
        _ensure_parent(path)
        if not dry_run:
            _dump_json(path, obj)
        actions.append(("write", path, f"mcpServers.{SERVER_NAME} registered (new file)"))
        return
    obj, _ = _read_jsonc(path)
    servers = obj.setdefault("mcpServers", {})
    if servers.get(SERVER_NAME) == entry:
        actions.append(("skip", path, f"mcpServers.{SERVER_NAME} already registered"))
        return
    servers[SERVER_NAME] = entry
    _ensure_parent(path)
    if not dry_run:
        _dump_json(path, obj)
    actions.append(("write", path, f"mcpServers.{SERVER_NAME} registered"))


def remove_claude(target: Path, dry_run: bool, actions: list) -> None:
    path = target / ".mcp.json"
    if not path.is_file():
        actions.append(("skip", path, "not found"))
        return
    obj, _ = _read_jsonc(path)
    servers = obj.get("mcpServers")
    if not isinstance(servers, dict) or servers.get(SERVER_NAME) is None:
        actions.append(("skip", path, f"mcpServers.{SERVER_NAME} not registered"))
        return
    del servers[SERVER_NAME]
    if not dry_run:
        if servers:
            _dump_json(path, obj)
        else:
            path.unlink()
    verb = "remove"
    msg = f"mcpServers.{SERVER_NAME} unregistered"
    if not servers:
        msg += " (empty .mcp.json removed)"
    actions.append((verb, path, msg))


# ---------------------------------------------------------------------------
# Report + verification
# ---------------------------------------------------------------------------

_VERB_GLYPH = {"write": "created  ", "update": "updated  ", "skip": "unchanged", "remove": "removed  "}


def _print_actions(actions: list) -> None:
    if not actions:
        print("Nothing to do.")
        return
    for verb, path, msg in actions:
        glyph = _VERB_GLYPH.get(verb, "  ?    ")
        print(f"  [{glyph}] {path}: {msg}")


def _print_verification(flags) -> None:
    print()
    print("Next steps:")
    if not flags.claude_only:
        print("  opencode      -> opencode mcp list")
    if not flags.opencode_only:
        print("  claude code   -> claude mcp get bsl-context   (or claude mcp list)")
    print()
    print("Notes:")
    print("  - 'uv' must be installed and on PATH for both clients.")
    print("  - Claude Code prompts to approve '.mcp.json' servers on first run (/mcp).")
    print("  - First semantic/hybrid query downloads models (~2GB) and builds the")
    print("    index. To prepare in advance: uv sync --extra local &&")
    print("    mcp-bsl-context -c <target>/config.yml --warmup")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="install-mcp.py",
        description="Register the mcp-bsl-context MCP server in a target project "
        "(opencode + Claude Code, project scope) and add a tools guide to "
        "AGENTS.md / CLAUDE.md.",
    )
    p.add_argument(
        "--project", default=None,
        help="Target project directory. Default: current working directory.",
    )
    p.add_argument(
        "--platform-path", default=None,
        help="1C platform installation directory (HBK source). Overrides "
        "MCP_BSL_PLATFORM_PATH and existing config.yml.",
    )
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--opencode-only", action="store_true", help="Only opencode.")
    scope.add_argument("--claude-only", action="store_true", help="Only Claude Code.")
    p.add_argument("--uninstall", action="store_true", help="Remove own changes.")
    p.add_argument("--dry-run", action="store_true", help="Preview changes, write nothing.")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    server_repo = Path(__file__).resolve().parent.parent

    if args.project:
        target = Path(args.project).expanduser().resolve()
    else:
        target = Path.cwd().resolve()
    if not target.is_dir():
        raise SystemExit(_Color.warn(f"Target directory does not exist: {target}"))

    actions: list = []
    config_example = server_repo / "config.example.yml"

    if args.uninstall:
        print(f"Uninstalling '{SERVER_NAME}' from {target}\n")
        for doc in _applications(args, target):
            remove_section(doc, args.dry_run, actions)
        if not args.claude_only:
            remove_opencode(target, args.dry_run, actions)
        if not args.opencode_only:
            remove_claude(target, args.dry_run, actions)
        _print_actions(actions)
        print("\n'config.yml' was left as-is; delete it manually if desired.")
        return 0

    dry_run_label = " (dry run, nothing written)" if args.dry_run else ""
    print(f"Installing '{SERVER_NAME}' into {target}{dry_run_label}\n")

    platform_path = resolve_platform_path(target, server_repo, args.platform_path)
    print(f"  platform: {platform_path}")

    generate_config(target, platform_path, config_example, args.dry_run, actions)
    section_file = server_repo / "scripts" / "templates" / "agent-tools.md"
    if not section_file.is_file():
        raise SystemExit(_Color.warn(f"Tools template not found: {section_file}"))
    section = section_file.read_text(encoding="utf-8")

    for doc in _applications(args, target):
        insert_section(doc, section, args.dry_run, actions)
    if not args.claude_only:
        install_opencode(server_repo, target, args.dry_run, actions)
    if not args.opencode_only:
        install_claude(server_repo, target, args.dry_run, actions)

    print()
    _print_actions(actions)
    if not args.dry_run:
        _print_verification(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())