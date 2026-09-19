"""Install/uninstall the ``mcp-bsl-context`` MCP server in a target project.

Registers the server (project scope) in the target project and adds the
AI-agent usage guide to its AGENTS.md / CLAUDE.md.

Targets:
  - opencode  -> opencode.jsonc   (mcp."bsl-context", type=local)
  - Claude Code -> .mcp.json      (mcpServers."bsl-context", type=stdio)

CLI entry points: ``mcp-bsl-context install`` / ``mcp-bsl-context uninstall``
(see ``mcp_bsl_context.__main__``).
"""

from __future__ import annotations

import json
import os
import re
import sys
from importlib.resources import files as _resources_files
from pathlib import Path
from typing import Literal

SERVER_NAME = "bsl-context"
MARKER_START = "<!-- MCP-BSL-CONTEXT:START -->"
MARKER_END = "<!-- MCP-BSL-CONTEXT:END -->"
OPENCODE_SCHEMA = "https://opencode.ai/config.json"

Scope = Literal["opencode", "claude", None]

COMMON_PLATFORM_DIRS = [
    "/opt/1cv8/x86_64",
    "/opt/1cv8",
    "C:/Program Files/1cv8",
    "C:/Program Files (x86)/1cv8",
]

DEFAULT_CONFIG_TEMPLATE = r"""# MCP BSL Platform Help Context — файл конфигурации
# Создан инсталлятором mcp-bsl-context. Пути приведены к абсолютным.
# Все параметры можно переопределить через переменные окружения (MCP_BSL_*) или CLI-аргументы.

server:
  mode: stdio               # stdio | sse | streamable-http (MCP-клиенты: всегда stdio)
  port: 8080                # порт для HTTP-транспортов
  verbose: false            # подробное отладочное логирование

platform:
  # Путь к каталогу установки платформы 1С.
  # Linux:   /opt/1cv8/x86_64
  # Windows: C:/Program Files/1cv8
  path: "C:/Program Files/1cv8"

  # Предпочтительная версия платформы. null = авто-выбор последней доступной.
  version: null

  data_source: hbk          # hbk | json
  json_path: null           # обязателен при data_source=json

search:
  default_mode: hybrid      # hybrid | semantic | keyword

# Модель эмбеддингов для семантического поиска
embeddings:
  provider: local           # local | openai-compatible
  model: ai-forever/ru-en-RoSBERTa
  api_url: null
  api_key: null

# Кросс-энкодер-реранкер
reranker:
  enabled: true             # применить реранкинг результатов
  provider: local           # local | openai-compatible
  model: DiTy/cross-encoder-russian-msmarco
  api_url: null
  api_key: null

# Пути к постоянным данным
storage:
  qdrant_path: ./data/qdrant   # векторная база Qdrant (эмбеддинги)
  models_cache: ./data/models  # скачанные файлы моделей

# Управление индексом
index:
  reindex: false            # true = пересобрать индекс эмбеддингов при запуске.

# Файлы документации (необязательно — используются встроенные по умолчанию)
docs:
  strict_types_path: null   # Кастомный путь к strict-types.md
  guideline_path: null      # Кастомный путь к guideline.md
"""


class InstallerError(Exception):
    """Fatal installer problem; turned into a ClickException by the CLI."""


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
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Server repo / platform path resolution
# ---------------------------------------------------------------------------


def resolve_server_repo(repo_override: str | None) -> Path:
    """Locate the server repository (used for ``uv run --project <repo>``).

    Priority: ``<repo>`` override -> the package project root (where
    ``pyproject.toml`` and the ``mcp_bsl_context`` package live) -> cwd.
    """
    if repo_override:
        return Path(repo_override).expanduser().resolve()
    pkg_parent = Path(__file__).resolve().parent.parent
    if (pkg_parent / "pyproject.toml").is_file() and (
        pkg_parent / "mcp_bsl_context"
    ).is_dir():
        return pkg_parent
    return Path.cwd().resolve()


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
    raise InstallerError(
        "Platform path not found. Pass it explicitly:\n"
        "  uv run mcp-bsl-context install --platform-path /opt/1cv8/x86_64\n"
        "or set MCP_BSL_PLATFORM_PATH."
    )


def tools_section() -> str:
    try:
        resource = _resources_files("mcp_bsl_context").joinpath(
            "installer_templates", "agent-tools.md"
        )
        return resource.read_bytes().decode("utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise InstallerError(f"Tools template not found in package data: {exc}") from exc


# ---------------------------------------------------------------------------
# Section insert/remove in AGENTS.md / CLAUDE.md
# ---------------------------------------------------------------------------


def _applications(scope: Scope, target: Path) -> list[Path]:
    if scope == "opencode":
        return [target / "AGENTS.md"]
    if scope == "claude":
        return [target / "CLAUDE.md"]
    return [target / "AGENTS.md", target / "CLAUDE.md"]


def insert_section(path: Path, section: str, dry_run: bool, actions: list) -> bool:
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if MARKER_START in text:
            # Replace the marked block in place.
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


def generate_config(target: Path, platform_path: str, dry_run: bool, actions: list) -> None:
    cfg = target / "config.yml"
    if cfg.exists():
        actions.append(("skip", cfg, "already exists, left as-is"))
        return
    text = DEFAULT_CONFIG_TEMPLATE

    pm = re.search(r'(?m)^(\s*)path:\s*"[^"]*"\s*$', text)
    if not pm:
        raise InstallerError("config template: platform 'path:' line not found")
    text = text[: pm.start()] + f'{pm.group(1)}path: {json.dumps(platform_path, ensure_ascii=False)}' + text[pm.end() :]

    # MCP clients (opencode/Claude Code) spawn the server over stdio.
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
        ("qdrant_path: ./data/qdrant", f"qdrant_path: {json.dumps(str(target / 'data' / 'qdrant'), ensure_ascii=False)}"),
        ("models_cache: ./data/models", f"models_cache: {json.dumps(str(target / 'data' / 'models'), ensure_ascii=False)}"),
    ]
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
        else:
            _eprint(_Color.warn(f"  ! pattern not found in config template: {old!r}"))

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
    if had_comments:
        _eprint(_Color.warn(f"  ! {path.name} contains JSONC comments; rewritten as strict JSON"))
    actions.append(("write", path, f"mcp.{SERVER_NAME} registered"))


def remove_opencode(target: Path, dry_run: bool, actions: list) -> None:
    path = target / "opencode.jsonc"
    if not path.is_file():
        actions.append(("skip", path, "not found"))
        return
    obj, _ = _read_jsonc(path)
    mcp = obj.get("mcp")
    if not isinstance(mcp, dict) or mcp.get(SERVER_NAME) is None:
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
# Report
# ---------------------------------------------------------------------------

_VERB_GLYPH = {"write": "created  ", "update": "updated  ", "skip": "unchanged", "remove": "removed  "}


def _print_actions(actions: list) -> None:
    if not actions:
        print("Nothing to do.")
        return
    for verb, path, msg in actions:
        glyph = _VERB_GLYPH.get(verb, "  ?    ")
        print(f"  [{glyph}] {path}: {msg}")


def _print_verification(scope: Scope) -> None:
    print()
    print("Next steps:")
    if scope != "claude":
        print("  opencode      -> opencode mcp list")
    if scope != "opencode":
        print("  claude code   -> claude mcp get bsl-context   (or claude mcp list)")
    print()
    print("Notes:")
    print("  - 'uv' must be installed and on PATH for both clients.")
    print("  - Claude Code prompts to approve '.mcp.json' servers on first run (/mcp).")
    print("  - First semantic/hybrid query downloads models (~2GB) and builds the")
    print("    index. To prepare in advance: uv sync --extra local &&")
    print("    mcp-bsl-context -c <target>/config.yml --warmup")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_install(
    target: Path,
    server_repo: Path,
    platform_path: str | None,
    scope: Scope,
    dry_run: bool,
) -> list:
    """Apply the install steps; returns the list of actions. Prints progress."""
    actions: list = []
    resolved = resolve_platform_path(target, server_repo, platform_path)
    print(f"  platform: {resolved}")
    generate_config(target, resolved, dry_run, actions)
    section = tools_section()
    for doc in _applications(scope, target):
        insert_section(doc, section, dry_run, actions)
    if scope != "claude":
        install_opencode(server_repo, target, dry_run, actions)
    if scope != "opencode":
        install_claude(server_repo, target, dry_run, actions)
    return actions


def run_uninstall(target: Path, scope: Scope, dry_run: bool) -> list:
    """Remove the installer's own changes; returns the list of actions."""
    actions: list = []
    for doc in _applications(scope, target):
        remove_section(doc, dry_run, actions)
    if scope != "claude":
        remove_opencode(target, dry_run, actions)
    if scope != "opencode":
        remove_claude(target, dry_run, actions)
    return actions