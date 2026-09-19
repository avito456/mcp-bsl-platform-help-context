# План: инсталлятор MCP-сервера в opencode и Claude Code

Дата: 19.09.2026
Статус: согласован.

## Цель

Создать инсталлятор, который устанавливает MCP-сервер `mcp-bsl-context` (этот репо)
в целевой проект — **1С-проект** или **этот репо** (при запуске инсталлятора здесь).
Инсталлятор делает в целевом проекте все правки: `AGENTS.md`/`CLAUDE.md` (описание
инструментов), `config.yml`, `opencode.jsonc`, `.mcp.json`.

## Согласованные решения

- **Форма инсталлятора** — Python-скрипт `scripts/install-mcp.py` (stdlib-only,
  кроссплатформенный, idempotent, `--dry-run`/`--uninstall`).
- **Scope регистрации** — только project-скоп в целевом проекте
  (`opencode.jsonc` + `.mcp.json`). User/глобальные конфиги не трогаем.
- **Объём установки** — только регистрация: резолв платформы 1С, генерация
  `config.yml` при необходимости, правка конфигов, вывод проверки.
  Никаких `uv sync`, сборки индекса, warmup.
- **Описание инструментов** — раздел вставляется в `AGENTS.md` **и** `CLAUDE.md`
  целевого проекта (opencode/codex читают `AGENTS.md`, Claude Code — `CLAUDE.md`).
  Canonical-текст хранится в сервер-репо как шаблон.
- **Target по умолчанию** — `cwd` (текущий каталог запуска скрипта). Запуск из
  этого репо → установка сюда; запуск из каталога 1С-проекта → установка туда.
- `--project <path>` — явное указание целевой директории (опционально).

## Изменения

### Новые файлы в сервер-репо

#### `scripts/install-mcp.py`

Запуск:

```bash
uv run <server-repo>/scripts/install-mcp.py [--project <target>] [--platform-path PATH]
          [--opencode-only | --claude-only] [--dry-run] [--uninstall]
```

Логика:

1. **Server-repo** вычисляется от `__file__` (каталог, где лежит скрипт).
2. **Target project** — `--project <path>` или, по умолчанию, текущий рабочий
   каталог запуска скрипта.
3. **Резолв платформы 1С** (приоритет):
   - `--platform-path PATH`;
   - env `MCP_BSL_PLATFORM_PATH`;
   - `platform.path` из уже существующего `config.yml` целевого проекта;
   - встроенный HBK сервер-репо (`<server>/8.3.27.72/`);
   - типовые каталоги 1С: `/opt/1cv8/x86_64`, `C:/Program Files/1cv8`;
   - иначе — понятная ошибка с подсказкой по `--platform-path`.
4. **Правки в целевом проекте:**
   - `config.yml` — если отсутствует, генерируется из `config.example.yml`
     сервер-репо с абсолютными `platform.path` и `storage.*`
     (под `<target>/data/`). Если уже существует — **не перезаписывается**
     (используется как есть, значение `platform.path` сверяется).
   - `AGENTS.md` и `CLAUDE.md` — вставка раздела «MCP: контекст платформы 1С»
     из шаблона (создаются при отсутствии), по маркерам, идемпотентно.
   - `opencode.jsonc` — создание/слияние записи `mcp."bsl-context"`:
     ```jsonc
     "bsl-context": {
       "type": "local",
       "command": ["uv", "run", "--project", "<server-repo>",
                   "mcp-bsl-context", "-c", "<target>/config.yml"],
       "cwd": "<target>",
       "enabled": true
     }
     ```
   - `.mcp.json` — создание/слияние project-scope записи
     `mcpServers."bsl-context"` (stdio; `type: "stdio"`, `command: "uv"`,
     `args: ["run","--project",<server-repo>,"mcp-bsl-context","-c",<target>/config.yml]`).
5. **Вывод** — сводка внесённых правок и команды проверки:
   - `opencode mcp list`;
   - `claude mcp get bsl-context` / `claude mcp list`;
   - напоминания: требуется `uv` на PATH; в Claude Code — одобрение
     `.mcp.json` при первом запуске.

Флаги:
- `--dry-run` — показать планируемые изменения без записи;
- `--uninstall` — удалить свои вставки (по маркерам секций и именам записей);
- `--opencode-only` / `--claude-only` — точечная регистрация.

#### `scripts/templates/agent-tools.md`

Canonical-текст раздела «MCP: контекст платформы 1С»:
список 10 инструментов + правила использования для AI-агентов
(начинать с `search`, подставлять точные имена как есть, шаблонные типы
`СправочникОбъект.<Имя справочника>`, `health` перед semantic/hybrid,
автодеградация в keyword при недоступности семантики).
Используется инсталлятором для вставки в `AGENTS.md`/`CLAUDE.md` целевого проекта.

### Правки в сервер-репо

- `README.md` — короткий блок в раздел «Интеграция»: установка для opencode и
  Claude Code через `scripts/install-mcp.py` (рядом с существующими
  Claude Desktop / Cursor).

### Явно НЕ трогаем

- User/глобальные конфиги (`~/.config/opencode/*`, `~/.claude.json`) — вне scope.
- `AGENTS.md`/`CLAUDE.md` сервер-репо — раздел появится там **только** когда
  инсталлятор запустят «сюда» (этот репо как target).
- Зависимости/индекс (`uv sync`, `--reindex`, `--warmup`) — вне scope.

## Проверка

1. `uv run scripts/install-mcp.py --project /tmp/пробный-1с-проект --dry-run` —
   превью без изменений.
2. Прогон на реальном target (в т.ч. на этом репо):
   - `config.yml` создан, `platform.path` верный;
   - секция в `AGENTS.md` и `CLAUDE.md` вставлена один раз (идемпотентность);
   - `opencode.jsonc` / `.mcp.json` содержат корректную запись `bsl-context`.
3. `--uninstall` возвращает конфиги к исходному виду.
4. Прогон из этого репо: `opencode.jsonc` мержится с существующим `codegraph`.