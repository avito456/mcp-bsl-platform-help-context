# План: инсталлятор MCP-сервера в opencode и Claude Code

Дата: 19.09.2026
Статус: реализовано (перенос в CLI-пакет как подкоманда `install`/`uninstall`).

## Цель

Инсталлятор, который регистрирует MCP-сервер `mcp-bsl-context` (этот репо)
в целевом проекте — **1С-проекте** или **этом репо** (при запуске здесь).
Инсталлятор делает в целевом проекте все правки: `AGENTS.md`/`CLAUDE.md`
(описание инструментов), `config.yml`, `opencode.jsonc`, `.mcp.json`.

## Согласованные решения

- **Форма инсталлятора** — подкоманды `install` / `uninstall` существующего
  CLI (`mcp-bsl-context`, Click-group с `invoke_without_command=True`): сервер
  запускается как раньше (`mcp-bsl-context -c config.yml`), установщик — рядом.
  Логика в `mcp_bsl_context/installer.py`, standalone-скрипт `scripts/` удалён.
- **Вызов** — только через `uv`: `uv run mcp-bsl-context install --project <target>`
  (из корня репо) либо `uv run --project <путь-к-репо> mcp-bsl-context install ...`
  (из любого каталога).
- **Scope регистрации** — только project-скоп в целевом проекте
  (`opencode.jsonc` + `.mcp.json`). User/глобальные конфиги не трогаем.
- **Объём установки** — только регистрация: резолв платформы 1С, генерация
  `config.yml` при необходимости, правка конфигов, вывод проверки.
  Никаких `uv sync`, сборки индекса, warmup.
- **Описание инструментов** — раздел вставляется в `AGENTS.md` **и** `CLAUDE.md`
  целевого проекта. Canonical-текст — шаблон `agent-tools.md` в package-data
  пакета (`mcp_bsl_context/installer_templates/`).
- **Шаблон `config.yml`** — встроен в `installer.py` константой
  (`DEFAULT_CONFIG_TEMPLATE`): зависимость от `config.example.yml` в корне
  репозитория устранена (сам пример остаётся для ручной установки).
- **Target по умолчанию** — `cwd`. Явно — `--project <path>`.
- **Резолв платформы 1С** (приоритет, без изменений):
  1. `--platform-path PATH`;
  2. env `MCP_BSL_PLATFORM_PATH`;
  3. `platform.path` из уже существующего `config.yml` целевого проекта;
  4. встроенный HBK сервер-репо (`<repo>/8.3.27.72/`);
  5. типовые каталоги: `/opt/1cv8/x86_64`, `C:/Program Files/1cv8`;
  6. иначе — понятная ошибка с подсказкой по `--platform-path`.
- **Server-repo** для генерируемых `uv run --project <…>`-команд: root пакета
  (где лежит `pyproject.toml`), при недоступности — `cwd`; опционально
  переопределяется флагом `--repo <path>`.

## Изменения

### Новые файлы в сервер-репо

#### `mcp_bsl_context/installer.py`

Логика установки/удаления, перенесённая из старого `scripts/install-mcp.py`:

1. Резолв server-repo и платформы 1С.
2. Генерация `config.yml` (если отсутствует): абсолютные `platform.path`
   и `storage.*` (под `<target>/data/`), `server.mode: stdio`. Существующий
   файл **не перезаписывается**.
3. Вставка/удаление раздела «MCP: контекст платформы 1С» в/из
   `AGENTS.md` и `CLAUDE.md` по маркерам, идемпотентно.
4. Создание/слияние `mcp."bsl-context"` в `opencode.jsonc`
   (`type: local`, command `uv run --project <server-repo> mcp-bsl-context
   -c <target>/config.yml`, `cwd: <target>`).
5. Создание/слияние `mcpServers."bsl-context"` в `.mcp.json`
   (`type: stdio`, `command: uv`, `args: [...]`).
6. Вывод сводки + команд проверки (`opencode mcp list`,
   `claude mcp get bsl-context`).

Идемпотентность: повторный запуск не меняет файлы («unchanged»).
Ошибки — `installer.InstallerError` → в CLI превращается в `ClickException`.

#### `mcp_bsl_context/installer_templates/agent-tools.md`

Canonical-текст раздела «MCP: контекст платформы 1С»: список 10 инструментов
+ правила использования для AI-агентов. Читается через `importlib.resources`.

### Правки в сервер-репо

- `mcp_bsl_context/__main__.py` — `click.group(invoke_without_command=True)`:
  опции сервера на уровне группы (обратная совместимость `-c config.yml`),
  подкоманды `install` и `uninstall`.
- `pyproject.toml` — package-data для `installer_templates/*.md`;
  entry point не меняется.
- `README.md` — раздел «Инсталлятор»: `uv run mcp-bsl-context install/uninstall`.
- Удалены `scripts/install-mcp.py` и `scripts/templates/`.
- `tests/test_installer_cli.py` — тесты через Click `CliRunner`.

### Явно НЕ трогаем

- User/глобальные конфиги — вне scope.
- Зависимости/индекс (`uv sync`, `--reindex`, `--warmup`) — вне scope.
- `config.example.yml` в корне репо — остаётся для ручной установки
  (`mcp-bsl-context -c config.yml`), инсталлятором не используется.

## Проверка

1. `uv run mcp-bsl-context --help` — видны подкоманды `install`/`uninstall`.
2. `uv run mcp-bsl-context install --project /tmp/… --dry-run` — превью без записи.
3. Реальный прогон + повторный запуск: `config.yml`, секция в `AGENTS.md`/
   `CLAUDE.md` один раз, записи в `opencode.jsonc`/`.mcp.json`; второй прогон —
   «unchanged».
4. `uv run mcp-bsl-context -c <target>/config.yml` — сервер поднимается
   (поведение не сломано).
5. `uv run mcp-bsl-context uninstall --project /tmp/…` — конфиги к исходному виду,
   `config.yml` остаётся.
6. `uv run pytest`.