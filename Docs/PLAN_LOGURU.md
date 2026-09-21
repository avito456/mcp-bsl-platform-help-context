# План: переход на loguru + лог моделей ИИ при старте

Дата: 21.09.2026
Проект: `mcp-bsl-platform-help-context`

## Контекст

- 18 модулей используют stdlib `logging`, ~72 вызова `logger.*`.
- Настройка логирования ровно в одном месте: `mcp_bsl_context/__main__.py`
  (`logging.basicConfig`, stream=stderr, уровень по `verbose`).
- Модели ИИ описаны в `AppConfig` (`config.py`): embeddings
  `provider/model/device/api_url`, reranker `enabled/provider/model/device/api_url`.
  Фактически грузятся лениво в `server.py` (`_LazySemanticState._do_init`), а
  `embeddings/provider.py` и `embeddings/reranker.py` уже логируют факт загрузки.
- `loguru` в зависимостях нет.

## Решения (уточнены)

| Вопрос | Решение |
|--------|---------|
| Глубина миграции | Полная замена во всех 18 модулях, форматы `%s` -> `{}` |
| Имя модуля в логе | `get_logger(__name__)` -> `logger.bind(module=__name__)` |
| Приёмники | stderr всегда + опциональный файл (rotation/retention) |
| Блок моделей ИИ | Всегда на INFO (сводка), детали на DEBUG |
| Секреты | `api_url` логируется, `api_key` маскируется и не выводится |
| Тесты | conftest-фикстура для loguru + правка 4 тестов |

## Шаги

### 1. Зависимость
- `pyproject.toml`: добавить `loguru>=0.7` в `[project].dependencies`.
- `uv lock`, `uv sync`. Dockerfile'ы менять не нужно (ставят из `pyproject.toml`).

### 2. Централизованная настройка — новый `mcp_bsl_context/logging_setup.py`
- `setup_logging(config)`: `logger.remove()`, stderr-sink с форматом
  `{time:YYYY-MM-DD HH:mm:ss} [{level}] {extra[module]}: {message}`,
  `colorize` только для TTY, уровень DEBUG/INFO.
- `InterceptHandler` для stdlib -> loguru (сторонние `mcp`, `httpx`,
  `sentence_transformers`, `qdrant`); сохранить подавление
  `mcp.server.lowlevel.server` (WARNING) при `not verbose`.
- `get_logger(name)` -> `logger.bind(module=name)`.

### 3. Замена logger во всех 18 модулях
- `config.py`, `server.py`, `__main__.py`, `domain/services.py`,
  `infrastructure/embeddings/{provider,reranker}.py`,
  `infrastructure/hbk/{container_reader,content_reader,context_reader,pages_visitor}.py`,
  `infrastructure/json_loader/json_context_loader.py`,
  `infrastructure/search/{engine,hybrid_engine,semantic_engine}.py`,
  `infrastructure/storage/{loader,storage,supplement,version_discovery}.py`.
- Убрать `import logging` и `logging.getLogger(...)`; добавить
  `from loguru import logger` + `logger = get_logger(__name__)`.
- Переписать `%s/%d` -> `{}` (72 места).
- Спец-случаи: `logger.debug(..., exc_info=True)` -> `logger.opt(exception=True).debug(...)`;
  `logger.exception(...)` оставить.

### 4. Лог моделей ИИ при старте
- `log_ai_models(config)` в `logging_setup.py`, вызов в `_run_server` после
  `setup_logging` и до `create_server`.
- INFO: `search.default_mode`, `platform.data_source`, embeddings
  `provider/model/device`, reranker `enabled/provider/model/device`,
  `storage.qdrant_path`, `storage.models_cache`, флаги `index.reindex/warmup`.
- DEBUG: `api_url`; `api_key` — никогда (только факт `***`).
- Обновить форматы сообщений в `provider.py` / `reranker.py`.

### 5. Файловый sink
- Секция `logging` в `config.py` (`LoggingConfig`): `file`, `rotation`,
  `retention`, `level`.
- Env: `MCP_BSL_LOG_FILE`, `MCP_BSL_LOG_ROTATION`, `MCP_BSL_LOG_RETENTION`,
  `MCP_BSL_LOG_LEVEL` в `_ENV_MAPPING`.
- По умолчанию файл выключен. Обновить `config.example.yml` и `README.md`.

### 6. Тесты и проверки
- `tests/conftest.py`: autouse-фикстура глушения loguru.
- Обновить `test_docs_guard.py`, `test_integration_real_hbk.py`,
  `test_logic_server_hbk.py`, `test_supplement.py`.
- Новый тест на `log_ai_models` (поля + отсутствие `api_key`).
- Проверка «stdout чист» (критично для stdio MCP).
- `pytest`.

## Риски
- **stdout** — только stderr/файл, иначе сломается stdio-транспорт MCP.
- `{extra[module]}` — забытый `.bind(module=...)` даёт ошибку формата;
  защита через `get_logger`.
- Не логировать `api_key`.
- Новые ключи конфига/`_ENV_MAPPING` не должны ломать `validate()`.
- `uv.lock` перегенерируется.

## Порядок
1 -> 2 -> 3 -> 4 -> 5 -> 6. Правки только в `mcp-bsl-platform-help-context`.
