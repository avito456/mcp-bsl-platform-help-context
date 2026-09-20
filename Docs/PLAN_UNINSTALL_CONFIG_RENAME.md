# План: uninstall удаляет config.yml + переименование MCP-сервера в bsl-context-1c

Дата: 20.09.2026
Статус: согласован

## Проблемы

1. При `uninstall` не удаляется `config.yml` — остаётся в целевом проекте
   (сообщение «'config.yml' was left as-is; delete it manually if desired»).
2. MCP-сервер зарегистрирован под именем `bsl-context`; нужно
   `bsl-context-1c`.

## Согласованные решения

- **Безопасное удаление `config.yml`**: удалять только файл, созданный
  инсталлятором — идентифицируется по заголовку-маркеру
  `CONFIG_INSTALL_MARKER = "# Создан инсталлятором mcp-bsl-context."`
  в первой строке. Существовавший до установки конфиг пользователя
  (без маркера) остаётся без изменений. Решение принято пользователем.
- **Переименование**: менять только имя регистрации MCP-сервера
  `SERVER_NAME = "bsl-context"` → `"bsl-context-1c"` (ключ `mcp."…"` в
  `opencode.jsonc` / `mcpServers."…"` в `.mcp.json`). Для команд ввода
  вводится константа `CLI_COMMAND = "mcp-bsl-context"` — имя CLI-команды
  **не меняется**.
- Обратная несовместимость переименования приемлема: старые записи
  `bsl-context` в уже установленных проектах uninstall не трогает
  (ищет только новое имя).

## Изменения

1. `mcp_bsl_context/installer.py`:
   - константы `SERVER_NAME = "bsl-context-1c"`, `CLI_COMMAND = "mcp-bsl-context"`,
     `CONFIG_INSTALL_MARKER`;
   - функция `remove_config(target, dry_run, actions)` — удаляет `config.yml`
     только при наличии маркера (skip: «not found» / «not created by
     installer»);
   - вызов `remove_config` в `run_uninstall`;
   - `_print_verification`: `claude mcp get bsl-context-1c`;
   - в сгенерированных командах использовать `CLI_COMMAND`.
2. `mcp_bsl_context/installer_templates/agent-tools.md` — `bsl-context-1c`.
3. Реестры репозитория: `opencode.jsonc`, `.mcp.json`, раздел в
   `AGENTS.md`/`CLAUDE.md` — `bsl-context-1c`.
4. `mcp_bsl_context/__main__.py` — докстринг install/uninstall,
   убрать сообщение про «left as-is».
5. `tests/test_installer_cli.py` — обновить литеральные `bsl-context`;
   новый тест: предсозданный config.yml без маркера сохраняется;
   dry-run не удаляет config.yml; roundtrip удаляет config.yml.
6. Документация: `README.md`, `CHANGELOG.md`, `PLAN_MCP_INSTALLER.md`.
7. Проверка: `uv run pytest`; реальный `install` + `uninstall` на
   временном каталоге.

Каждый пункт фиксируется отдельным коммитом.