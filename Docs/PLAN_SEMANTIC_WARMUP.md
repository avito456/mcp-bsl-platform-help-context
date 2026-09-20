# PLAN_SEMANTIC_WARMUP

Исправление: семантический поиск (semantic/hybrid) недоступен из opencode.

## Диагноз

- Модели (`ai-forever/ru-en-RoSBERTa` + реранкер `DiTy/cross-encoder-russian-msmarco`) уже скачаны
  в кэш (2,2 ГБ), индекс Qdrant собран (193 МБ), fingerprint совпадает — пересборки индекса не будет.
- Инициализация занимает 13–15 с на каждый запуск процесса (загрузка двух моделей в память).
- Инициализация ленивая (`_LazySemanticState._ensure_initialized`, `mcp_bsl_context/server.py:102`):
  первый semantic/hybrid-вызов грузит модели внутри обработчика запроса.
- У opencode локальный MCP-сервер по умолчанию имеет `timeout: 5000 мс` → запрос срывается на 13–15 с.
  После повторных срывов opencode рвёт соединение (признак «connection closed»).
- Механизм `index.warmup` уже есть в коде, но он **синхронный** в `create_server`
  (`server.py:292-297`): включение «как есть» добавило бы 13–15 с к хендшейку и риск провала
  `tools/list` (тот же таймаут клиента). Поэтому прогрев делаем асинхронным.

## Шаги

### 1. `mcp_bsl_context/server.py` — асинхронный прогрев

- `_LazySemanticState.start_background_warmup()` — демон-поток с `_ensure_initialized()`;
  исключения логгируются (транзиентные сбои не кэшируются, поведение сохраняется).
- В `semantic_search`/`hybrid_search` — ограниченное ожидание готовности (poll `_initialized` +
  `_init_error`, дедлайн ~10–15 с) вместо бесконечного блокирования. По истечении — `RuntimeError`
  («семантика ещё инициализируется, повторите запрос») → существующий fallback на keyword
  (`server.py:359-371`) с понятной пометкой.
- `create_server`: блок `warmup` — вместо синхронного `semantic_state.initialize()` вызывать
  `start_background_warmup()`. `reindex` остаётся синхронным.
- `health()`/`status`: во время фонового прогрева выводить `initializing…`.

### 2. `config.yml` (+ `config.example.yml`)

- Включить `index.warmup: true` (модели в кэше → фоновая загрузка ~13–15 с, хендшейк не ждёт).
- Добавить `index.warmup` в `config.example.yml` с пояснением.

### 3. `opencode.jsonc` (проектный)

- В запись `bsl-context-1c` добавить `"timeout": 300000` — страховка на случай запроса в первые
  секунды прогрева. `.mcp.json` не трогаем (Claude Code ждёт дольше).

### 4. Тесты — `tests/test_semantic_warmup.py`

- `create_server` с `warmup=True` не блокируется (заглушка `_do_init` с задержкой).
- Фоновая инициализация доводит `status` до `ready`.
- `semantic_search` возвращает `RuntimeError` при недошедшем прогреве за дедлайн (fallback-ветка).
- Существующие тесты задают `warmup=False` — не затрагиваются.

### 5. Документация

- README: заметка о `index.warmup` и асинхронном прогреве.

### 6. Верификация

- `pytest tests/ -q`.
- stdio-проба: `tools/list` быстрый при `warmup=true`, `health` → «warmup on startup»,
  после ~15 с `semantic: ready`, первый semantic-запрос ~0,1–0,3 с.
- «connection closed» не воспроизводится, повторные semantic-запросы стабильны.