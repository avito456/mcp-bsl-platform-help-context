# План: интерактивная установка `mcp-bsl-context install`

Дата: 20.09.2026
Статус: реализовано.

## Цель

- Установка в текущий каталог по умолчанию — уже так (сохраняем).
- Голый `uv run mcp-bsl-context install` на терминале (tty) запускает
  интерактивный мастер.
- Программа определяет ОС, предлагает каталог установки 1С по умолчанию,
  пользователь просто вводит/выбирает версию 1С.
- **Спрашивать только нерешённое** (решение пользователя): что удалось
  определить автоматически — показать как дефолт и принять Enter'ом.

## Решения

- Клиент по умолчанию — **оба** (opencode + Claude Code), текущее поведение.
- Мастер включается только на реальном tty. Не-tty (пайпы, CI, тесты
  `CliRunner`) — без вопросов, текущая логика не меняется.
- Уточнение (мастер):
  1. каталог платформы 1С — только если авто-резолв не сработал;
  2. версия 1С — список найденных версий + свободный ввод,
     дефолт «последняя»; не спрашивается, если найдена одна версия;
  3. подтверждение записи (не при `--dry-run`; пропускается при `--yes`).
- Версия записывается в генерируемый `config.yml` как `platform.version`
  (рантайм уже умеет фильтровать, `server.py:615`).
- Новые флаги: `--platform-version`, `--yes/-y`, `--non-interactive`.
- Без новых зависимостей: `click.prompt` / `click.confirm`.

## Изменения

### `mcp_bsl_context/installer.py`

- `_os_platform_dir_candidates() -> list[Path]` — существующие каталоги-кандидаты
  по `sys.platform`:
  - darwin: `~/Applications/1cv8`, `/Applications/1cv8`, `/opt/1cv8`;
  - linux: `/opt/1cv8/x86_64`, `/opt/1cv8`;
  - win32: `C:/Program Files/1cv8`, `C:/Program Files (x86)/1cv8`.
- `generate_config(..., version=None)` — пишет `platform.version` в шаблон;
  сообщение действия включает версию.

### `mcp_bsl_context/interactive.py` (новый)

- `discover_versions(root)` — обёртка над `VersionDiscovery.discover()`.
- `prompt_platform_path(defaults, candidates)` — путь, если авто-резолв не сработал.
- `prompt_version(root, ...)` — выбор версии из найденных + свободный ввод
  (валидация через `PlatformVersion.parse`), `None` = не писать.
- `confirm_install(summary)` — подтверждение записи (Enter = да).
- `interact_before_install(...) -> (platform_path, platform_version)` —
  оркестрация: try `resolve_platform_path()`; при `InstallerError` — вопрос пути;
  затем выбор версии.

### `mcp_bsl_context/__main__.py`

- Опции `install`: `--platform-version`, `--yes/-y`, `--non-interactive`.
- `_want_interactive(yes, non_interactive) -> bool` — `not yes and not
  non_interactive and sys.stdin.isatty()`.
- `_run_install` до записей вызывает мастера и подставляет резолвы.

### Тесты

- `tests/test_installer_interactive.py`:
  - tty-мастер через `CliRunner` + `input=`, монкипат `_want_interactive`;
  - выбор версии из нескольких, запись `platform.version` в config.yml;
  - единая версия — без вопроса о версии;
  - `--platform-path`/`--platform-version` — мастер не спрашивает эти пункты;
  - `--non-interactive` / `--yes` — без вопросов;
  - resolve failure без tty — прежняя ошибка.
- Существующие тесты `test_installer_cli.py` остаются зелёными (не-tty).

### Документация

- `README.md`: интерактивный поток, `--yes`, `--non-interactive`.
- `CHANGELOG.md`.

## Проверка

1. `uv run mcp-bsl-context install` на tty в репо со встроенным HBK —
   один Enter, записывается `config.yml` с версией.
2. `install --platform-path X --platform-version 8.3.20` — без вопросов.
3. `install --yes` — без вопросов.
4. `uv run pytest`.