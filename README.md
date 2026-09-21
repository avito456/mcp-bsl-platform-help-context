# MCP BSL Platform Help Context

[![SafeSkill 92/100](https://img.shields.io/badge/SafeSkill-92%2F100_Verified%20Safe-brightgreen)](https://safeskill.dev/scan/desko77-mcp-bsl-platform-help-context)

**MCP-сервер для доступа к документации API платформы 1С:Предприятие**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![MCP](https://img.shields.io/badge/MCP-Compatible-purple)

Python-порт [mcp-bsl-platform-context](https://github.com/alkoleft/mcp-bsl-platform-context) (Kotlin/Spring Boot).

---

## Возможности

- **Три режима поиска**: keyword (нечёткий), semantic (embeddings + Qdrant), hybrid (оба + RRF-слияние + reranker)
- **Детальная информация** о типах, методах, свойствах, конструкторах платформы 1С
- **Навигация по объектной модели** платформы
- **Документация по строгой типизации** BSL и рекомендации по стилю кода
- **Два источника данных**: прямое чтение HBK файлов или pre-exported JSON
- **Три транспорта**: STDIO (для Claude Desktop, Cursor), SSE и Streamable HTTP
- **Мультиверсионность**: автоматическое обнаружение версий платформы с выбором ближайшей
- **YAML-конфигурация** с поддержкой переменных окружения и CLI-аргументов
- **Двуязычность**: все имена API доступны по русским и английским алиасам (`ТаблицаЗначений` = `ValueTable`, `НайтиПоСсылкам` = `FindByRef`); описания инструментов — на русском и английском
- **Готовность**: инструмент `health` и опциональный прогрев семантики при старте (`--warmup`)

## MCP-инструменты

### Поиск и навигация по API

| Инструмент | Описание | Параметры |
|------------|----------|-----------|
| `search` | Поиск по API платформы 1С. Поддерживает keyword, semantic и hybrid режимы. Работают русские и английские термины, а также запросы вида `Тип.Метод` (`ТаблицаЗначений.Добавить`, `ValueTable.Add`). При пустом результате — подсказки «Возможно, вы имели в виду» | `query` (строка поиска), `mode?` (keyword/semantic/hybrid), `type_filter?` (method/property/type), `limit?` (1–50, по умолчанию 10) |
| `info` | Детальная информация о конкретном элементе API по точному имени (русскому или английскому) | `name` (точное имя, например `НайтиПоСсылкам` или `FindByRef`), `type_filter?` (method/property/type; при отсутствии тип определяется автоматически) |
| `get_member` | Получить информацию о методе или свойстве конкретного типа | `type_name` (имя типа, например `ТаблицаЗначений` или `ValueTable`), `member_name` (имя метода/свойства) |
| `get_members` | Полный список методов и свойств типа | `type_name` (имя типа, например `ТаблицаЗначений`) |
| `get_constructors` | Сигнатуры конструкторов для создания экземпляров типа | `type_name` (имя типа) |
| `get_platform_info` | Информация о текущей версии платформы и список доступных версий | — |
| `health` | Статус сервера: версия платформы, источник данных, статистика контекста и готовность semantic/hybrid | — |

### Документация и стандарты кода

| Инструмент | Описание | Параметры |
|------------|----------|-----------|
| `get_coding_guideline` | Рекомендации по стилю кода BSL (1С:Предприятие) | — |
| `get_strict_typing_info` | Документация по строгой типизации BSL. Используйте `topic='topics'` для списка тем | `topic` (название темы или `topics`) |
| `search_strict_typing` | Текстовый поиск по документации строгой типизации с контекстом | `query` (поисковый запрос) |

## Режимы поиска

Инструмент `search` поддерживает три режима (параметр `mode`, по умолчанию из конфигурации):

| Режим | Движок | Описание |
|-------|--------|----------|
| `keyword` | `SimpleSearchEngine` | 4-стратегийный поиск: точное совпадение, префикс, составные имена, порядок слов. Каждая сущность доступна по русскому и английскому имени. При пустом результате выдаются ближайшие имена («did you mean») |
| `semantic` | `SemanticSearchEngine` | Векторный поиск: embedding запроса → ANN в Qdrant → опциональный cross-encoder rerank |
| `hybrid` | `HybridSearchEngine` | Keyword + semantic параллельно → RRF-слияние (k=60) → rerank |

**RAG-пайплайн:** `DocumentBuilder` → `EmbeddingProvider` → Qdrant embedded → `Reranker`

**Модели по умолчанию:**
- Embedder: `ai-forever/ru-en-RoSBERTa`
- Reranker: `DiTy/cross-encoder-russian-msmarco`

**Провайдеры:** `local` (sentence-transformers) или `openai-compatible` (любой API в формате OpenAI)

## Установка

Рекомендуется [uv](https://docs.astral.sh/uv/):

```bash
# В корне проекта:
uv sync                                   # Базовая установка (keyword search)
uv sync --extra local                     # + sentence-transformers, torch (semantic/hybrid search)
uv sync --extra local --extra dev         # + pytest для разработки

uv run mcp-bsl-context -c config.yml      # Запуск
```

Приведённые ниже примеры используют `mcp-bsl-context`; внутри каталога проекта это эквивалентно `uv run mcp-bsl-context`.

### Зависимости

- Python 3.10+
- fastmcp >= 4.0
- beautifulsoup4 >= 4.12
- lxml >= 5.0
- click >= 8.1
- PyYAML >= 6.0

## Конфигурация

### YAML-файл (рекомендуется)

Скопируйте `config.example.yml` в `config.yml` и настройте под своё окружение:

```bash
cp config.example.yml config.yml
mcp-bsl-context -c config.yml
```

**Приоритет конфигурации:** YAML < переменные окружения (`MCP_BSL_*`) < CLI-аргументы.

Основные секции: `server`, `platform`, `search`, `embeddings`, `reranker`, `storage`, `index`, `docs`, `logging`.

### Параметры CLI

```
--config, -c               Путь к YAML-файлу конфигурации
--platform-path, -p        Путь к каталогу установки 1С
--platform-version         Предпочтительная версия платформы (e.g., 8.3.20)
--mode, -m                 Транспорт: stdio (по умолчанию), sse или streamable-http
--port                     Порт для HTTP-сервера (по умолчанию: 8080)
--data-source              Источник данных: hbk или json
--json-path                Путь к каталогу с JSON-файлами
--verbose, -v              Включить отладочное логирование
--reindex                  Принудительная пересборка семантического индекса из HBK
--warmup                   Прогрев семантики при старте (без пересборки индекса)
```

### Переменные окружения

| CLI-аргумент | Переменная окружения | По умолчанию |
|---|---|---|
| `--platform-path` | `MCP_BSL_PLATFORM_PATH` | авто-поиск по ОС (hbk) |
| `--platform-version` | `MCP_BSL_PLATFORM_VERSION` | null (авто — последняя) |
| `--mode` | `MCP_BSL_MODE` | `stdio` |
| `--port` | `MCP_BSL_PORT` | `8080` |
| `--data-source` | `MCP_BSL_DATA_SOURCE` | `hbk` |
| `--json-path` | `MCP_BSL_JSON_PATH` | — |
| `--verbose` | `MCP_BSL_VERBOSE` | `false` |
| `--reindex` | `MCP_BSL_INDEX_REINDEX` | `false` |
| `--warmup` | `MCP_BSL_INDEX_WARMUP` | `false` |
| `--host` | `MCP_BSL_HOST` | `127.0.0.1` |
| — | `MCP_BSL_DOCS_STRICT_TYPES_PATH` | null (встроенный) |
| — | `MCP_BSL_DOCS_GUIDELINE_PATH` | null (встроенный) |
| — | `MCP_BSL_LOG_FILE` | null (только stderr) |
| — | `MCP_BSL_LOG_ROTATION` | `10 MB` |
| — | `MCP_BSL_LOG_RETENTION` | `7 days` |
| — | `MCP_BSL_LOG_LEVEL` | как у сервера (`verbose`) |

### Логирование

Логи пишутся в **stderr** (stdout зарезервирован под JSON-RPC stdio-транспорта),
формат: `YYYY-MM-DD HH:mm:ss [LEVEL] module: message`. Уровень — `DEBUG` при
`--verbose`/`server.verbose: true`, иначе `INFO`. При старте сервер выводит
сводку по моделям ИИ (режим поиска, источник данных, embeddings/reranker,
пути хранения); `api_key` никогда не логируется.

Дополнительно можно включить файловый приёмник с ротацией (по умолчанию
выключен) через секцию `logging` или переменные `MCP_BSL_LOG_*`:

```yaml
logging:
  file: ./data/logs/mcp-bsl.log   # null = только stderr
  rotation: "10 MB"               # "10 MB", "1 day", ...
  retention: "7 days"
  level: null                     # null = как у сервера
```

## Использование

### YAML-конфигурация (рекомендуется)

```bash
mcp-bsl-context -c config.yml                                  # Полная конфигурация из YAML
mcp-bsl-context -c config.yml -p /opt/1cv8/x86_64              # YAML + CLI override
```

### CLI-параметры

```bash
mcp-bsl-context                                 # Авто-поиск платформы по каталогам установки ОС
mcp-bsl-context -p /opt/1cv8/x86_64                            # Автоопределение последней версии
mcp-bsl-context -p /opt/1cv8/x86_64 --platform-version 8.3.20  # Ближайшая к 8.3.20
mcp-bsl-context -p /path -m streamable-http --port 8080         # Streamable HTTP транспорт
mcp-bsl-context -p /path --data-source json --json-path /path   # JSON источник
mcp-bsl-context -p /path --reindex                              # Пересборка семантического индекса
mcp-bsl-context -p /path --warmup                               # Прогрев семантики при старте (без пересборки)
```

Если источник `hbk`, а `platform.path` не задан (ни в `config.yml`, ни через
`--platform-path`/`MCP_BSL_PLATFORM_PATH`), сервер при старте ищет
установленную платформу 1С: сначала встроенный HBK в репозитории сервера,
затем каталоги установки текущей ОС (macOS: `~/Applications/1cv8`,
`/Applications/1cv8`, `/opt/1cv8`; Linux: `/opt/1cv8[/x86_64]`; Windows:
`C:/Program Files/1cv8`). Если она не найдена — ошибка конфигурации с
просьбой указать `--platform-path`.

## Интеграция

### Инсталлятор (`mcp-bsl-context install`)

Самый простой способ подключить сервер к **opencode** и **Claude Code** — подкоманда
`install` (входит в `mcp-bsl-context`). Она регистрирует MCP-сервер (project-скоп)
в целевом проекте: создаёт `config.yml`, если его нет, вносит запись
в `opencode.jsonc` и `.mcp.json`, а также добавляет описание инструментов
в `AGENTS.md`/`CLAUDE.md` проекта.

```bash
uv run mcp-bsl-context install                                  # в текущий каталог (интерактивно)
uv run mcp-bsl-context install --project ../my-1c-app --platform-path /opt/1cv8/x86_64
uv run mcp-bsl-context install --dry-run                        # предпросмотр без записи
uv run mcp-bsl-context install --yes                            # все дефолты, без вопросов
uv run mcp-bsl-context uninstall --project ../my-1c-app         # удалить регистрацию
```

`uninstall` убирает всё, что `install` добавил в целевой проект: раздел в
`AGENTS.md`/`CLAUDE.md`, записи в `opencode.jsonc`/`.mcp.json` и `config.yml`
(если он был создан инсталлятором). Конфиг, существовавший до установки,
остаётся нетронутым.

На интерактивном терминале голый `install` запускает мастер и спрашивает
только то, что не удалось определить автоматически:

1. **Каталог платформы 1С** — ищется по каталогам установки текущей ОС
   (`~/Applications/1cv8`, `/Applications/1cv8`, `/opt/1cv8` на macOS,
   `/opt/1cv8/x86_64`, `/opt/1cv8` на Linux, `C:/Program Files/1cv8` на Windows);
   если найдены установленные версии, печатается их нумерованный список;
2. **Версия 1С** — выбирается по номеру из списка, вводом значения (например
   `8.3.20`), Enter — последняя, или `auto` (не фиксировать версию). Версия
   записывается в `config.yml` как `platform.version`;
3. **Каталог с файлом справки `*.hbk`** — если установленных платформ не
   найдено, мастер спрашивает каталог с файлом справки (например каталог
   версии с `shcntx_ru.hbk`) и проверяет, что в нём есть HBK;
4. **Подтверждение записи** — Enter подтверждает.

Команды выполняются из корня этого репозитория. Для запуска из любого каталога —
с `--project <репо>`:
`uv run --project /path/to/mcp-bsl-platform-help-context mcp-bsl-context install --project /path/to/1c-project`

Дополнительные флаги: `--repo <path>` (переопределить server-репо для
генерируемых команд), `--platform-version <версия>` (зафиксировать версию без
вопросов), `--opencode-only` / `--claude-only`, `--dry-run`, `--yes`/`-y`
(принять все дефолты, не спрашивать), `--non-interactive` (для CI: без вопросов,
ошибка, если значение невозможно определить автоматически).

Требуется `uv` на PATH. После установки проверьте: `opencode mcp list` и
`claude mcp get bsl-context-1c` (или `claude mcp list`). В Claude Code сервер из `.mcp.json`
утверждается при первом запуске (`/mcp`).

### opencode

Добавьте в `opencode.jsonc` корня проекта (инсталлятор делает это автоматически):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "bsl-context-1c": {
      "type": "local",
      "command": ["uv", "run", "--project", "/path/to/mcp-bsl-platform-help-context", "mcp-bsl-context", "-c", "/path/to/project/config.yml"],
      "cwd": "/path/to/project",
      "enabled": true
    }
  }
}
```

### Claude Code

Добавьте в `.mcp.json` корня проекта (инсталлятор делает это автоматически):

```json
{
  "mcpServers": {
    "bsl-context-1c": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "/path/to/mcp-bsl-platform-help-context", "mcp-bsl-context", "-c", "/path/to/project/config.yml"]
    }
  }
}
```

Либо через CLI: `claude mcp add --scope project bsl-context-1c -- uv run --project /path/to/mcp-bsl-platform-help-context mcp-bsl-context -c /path/to/project/config.yml`

> В `config.yml` должен быть задан `platform.path` (инсталлятор создаёт этот файл
> с путём к платформе 1С, если его нет). Если `config.yml` отсутствует, команда
> запустится с `-p`/env-переопределениями.

### Claude Desktop

Добавьте в `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bsl-context-1c": {
      "command": "uv",
      "args": ["--project", "/path/to/mcp-bsl-platform-help-context", "run", "mcp-bsl-context", "-p", "/opt/1cv8/x86_64/8.3.25.1257"]
    }
  }
}
```

### Cursor IDE

Добавьте в `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "bsl-context-1c": {
      "command": "uv",
      "args": ["--project", "C:\\path\\to\\mcp-bsl-platform-help-context", "run", "mcp-bsl-context", "-p", "C:\\Program Files\\1cv8\\8.3.25.1257"]
    }
  }
}
```

### Мультиверсионный режим

Укажите путь к родительскому каталогу, и сервер автоматически найдёт все установленные версии:

```bash
# Linux: /opt/1cv8/x86_64 содержит 8.3.22.2838/, 8.3.25.1257/, ...
mcp-bsl-context -p /opt/1cv8/x86_64

# Выбрать конкретную версию (будет найдена ближайшая доступная)
mcp-bsl-context -p /opt/1cv8/x86_64 --platform-version 8.3.20
```

### Streamable HTTP (рекомендуется для сетевого доступа)

[Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http) — актуальный HTTP-транспорт в спецификации MCP, заменяющий устаревший SSE. Основные отличия:

- **Единый эндпоинт** `/mcp` вместо двух (`/sse` + `/messages`) — проще настройка и проксирование
- **Stateless-режим** — каждый запрос самодостаточен, не требуется держать долгоживущее SSE-соединение
- **Лучше для production** — корректно работает за reverse proxy, load balancer, в Kubernetes

```bash
mcp-bsl-context -p /opt/1cv8/x86_64/8.3.25.1257 -m streamable-http --port 8080
```

Подключение клиента:

```json
{
  "mcpServers": {
    "bsl-context-1c": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

> **Примечание:** SSE-режим (`-m sse`) по-прежнему поддерживается для обратной совместимости.

## Docker

### Docker Compose

В `docker-compose.yml` нужно указать путь к каталогу установки платформы 1С, в котором находится файл `shcntx_ru.hbk`.

```yaml
volumes:
  # Linux:
  - /opt/1cv8/x86_64/8.3.25.1257:/data/platform:ro
  # Windows (Docker Desktop):
  # - "C:/Program Files/1cv8/8.3.25.1257:/data/platform:ro"
```

```bash
docker compose up -d                   # CPU + API providers
docker compose --profile gpu up -d     # GPU + локальные модели
docker compose --profile json up -d    # JSON data source
```

### Ручная сборка

```bash
docker build -t mcp-bsl-context .

# HBK-данные
docker run -d \
  -v /opt/1cv8/x86_64/8.3.25.1257:/data/platform:ro \
  -p 8080:8080 \
  mcp-bsl-context

# JSON-данные
docker run -d \
  -e MCP_BSL_DATA_SOURCE=json \
  -v ./json-data:/data/json:ro \
  -p 8080:8080 \
  mcp-bsl-context
```

### Проверка здоровья

```bash
docker inspect --format='{{.State.Health.Status}}' mcp-bsl-context
```

## Архитектура

```
mcp_bsl_context/
├── config.py                  # AppConfig — YAML + env + CLI merge
├── domain/                    # Доменный слой (все dataclasses frozen)
│   ├── entities.py            # Definition, MethodDefinition, PropertyDefinition, PlatformTypeDefinition
│   ├── enums.py               # ApiType (METHOD, PROPERTY, TYPE, CONSTRUCTOR)
│   ├── exceptions.py          # Иерархия исключений
│   ├── value_objects.py       # SearchQuery, SearchOptions, PlatformVersion
│   ├── services.py            # ContextSearchService
│   └── docs_service.py        # DocsInfoService (строгая типизация, guideline)
│
├── infrastructure/
│   ├── hbk/                   # Парсер бинарного формата HBK
│   │   ├── container_reader.py     # Бинарный контейнер
│   │   ├── content_reader.py       # ZIP-распаковка, TOC + FileStorage
│   │   ├── context_reader.py       # Оркестратор чтения
│   │   ├── pages_visitor.py        # Visitor: обход дерева страниц
│   │   ├── toc/                    # TOC: токенизатор, парсер, дерево
│   │   └── parsers/                # HTML-парсеры страниц (BeautifulSoup)
│   │
│   ├── json_loader/           # Альтернативный источник: JSON
│   ├── search/                # Поисковые движки
│   │   ├── indexes.py         # HashIndex, StartWithIndex
│   │   ├── strategies.py      # 4 стратегии keyword-поиска
│   │   ├── engine.py          # SimpleSearchEngine (keyword)
│   │   ├── semantic_engine.py # SemanticSearchEngine (Qdrant + embeddings)
│   │   └── hybrid_engine.py   # HybridSearchEngine (RRF + rerank)
│   │
│   ├── embeddings/            # ML-модели
│   │   ├── provider.py        # EmbeddingProvider (local/API)
│   │   ├── reranker.py        # Reranker (cross-encoder, local/API)
│   │   └── document_builder.py # Entities → embeddable text + Qdrant payload
│   │
│   └── storage/               # Хранилище и репозиторий
│       ├── storage.py         # PlatformContextStorage (thread-safe, lazy)
│       ├── repository.py      # PlatformRepository (фасад)
│       ├── loader.py          # PlatformContextLoader
│       ├── mapper.py          # Маппинг сущностей
│       └── version_discovery.py # VersionDiscovery (мультиверсионность)
│
├── presentation/
│   └── formatter.py           # Markdown-форматтер для MCP-ответов
│
├── docinfo/                   # Встроенная документация
│   ├── strict-types.md        # Строгая типизация BSL
│   └── guideline.md           # Рекомендации по стилю кода
│
├── server.py                  # FastMCP сервер (10 инструментов)
└── __main__.py                # CLI (click) + YAML config
```

### Поисковый движок (keyword)

4 стратегии с приоритетами:

1. **CompoundTypeSearch** — составные имена типов ("Справочник Объект" → "СправочникОбъект")
2. **TypeMemberSearch** — паттерн "Тип.Член" ("ТаблицаЗначений Добавить")
3. **RegularSearch** — прямой lookup по индексам (точное совпадение + префикс)
4. **WordOrderSearch** — поиск по вхождению отдельных слов

### Семантический поиск

- **Embedding** запроса через `ai-forever/ru-en-RoSBERTa` (или API-провайдер)
- **ANN-поиск** в Qdrant embedded (in-process, данные на диске)
- **Reranking** результатов cross-encoder (`DiTy/cross-encoder-russian-msmarco`)
- **Ленивая инициализация**: модели загружаются при первом semantic/hybrid запросе

## Инструкции для AI-ассистентов

При использовании этого MCP-сервера рекомендуется:

1. **Начинайте с `search`** для нахождения нужных элементов API. Используйте конкретные термины 1С, а не общие описания. Точные имена, возвращённые в таблицах результатов (включая шаблонные типа `СправочникОбъект.<Имя справочника>`), подставляйте в последующие вызовы как есть.

2. **Уточняйте через `info`** — после нахождения нужного элемента получите полную документацию по точному имени.

3. **Навигация по типам**: используйте `get_members` для обзора всех методов/свойств типа, затем `get_member` для конкретного.

4. **Конструкторы**: если нужно создать объект, используйте `get_constructors` для получения сигнатур.

5. **Строгая типизация**: для вопросов о типизации BSL используйте `get_strict_typing_info` (сначала `topic='topics'` для списка тем).

6. **Стиль кода**: `get_coding_guideline` содержит полные рекомендации по написанию кода 1С.

7. **Режимы поиска**:
   - `keyword` — быстрый, для точных имён API (НайтиПоСсылкам, ValueTable); при опечатке — подсказки «Возможно, вы имели в виду»
   - `semantic` — для запросов на естественном языке ("как добавить строку в таблицу")
   - `hybrid` — лучшее качество, комбинирует оба подхода; при недоступности семантики автоматически возвращается к keyword с пометкой

8. **Версии платформы**: `get_platform_info` покажет текущую версию и доступные.

9. **Готовность**: перед первым semantic/hybrid-запросом (или при сомнениях) вызывайте `health` — он покажет, инициализирована ли семантика. Первый semantic/hybrid-запрос может занять несколько минут.

## Тестирование

```bash
uv sync --extra dev
uv run pytest -v                     # Все тесты
uv run pytest -v tests/test_search_engine.py           # Один модуль
uv run pytest -v tests/test_search_engine.py::test_name  # Один тест
```

## Источник данных

Сервер читает файл `shcntx_ru.hbk` из каталога установки платформы 1С:Предприятие. Это бинарный контейнер, содержащий:
- **PackBlock** — ZIP с оглавлением в bracket-формате
- **FileStorage** — ZIP с HTML-страницами документации

Поддерживаются версии HBK до 8.3.27+ включительно (multi-page data chains, изменённые TOC-коды языков, CSS-классы `V8SH_heading`/`V8SH_chapter`).

Альтернативно можно использовать pre-exported JSON (через [platform-context-exporter](https://github.com/alkoleft/platform-context-exporter)).

## Индексация

- **Keyword-индекс** строится автоматически при старте сервера (в памяти, без отдельной команды).
- **Семантический индекс** (Qdrant, каталог `storage.qdrant_path`, по умолчанию `./data/qdrant`) строится лениво при первом `semantic`/`hybrid`-запросе и переиспользуется между запусками.

Для принудительной пересборки семантического индекса из HBK используйте флаг `--reindex` (или `MCP_BSL_INDEX_REINDEX=true`, или `index.reindex: true` в `config.yml`). Индекс пересоберётся при первом semantic/hybrid-запросе после старта сервера:

```bash
mcp-bsl-context -c config.yml --reindex
```

Если после пересборки изменилось наполнение embed-текста (например, добавлены
EN-алиасы), индекс пересобирается автоматически: fingerprint данных меняется.

Чтобы заранее загрузить модели и подготовить индекс без пересборки, используйте
`--warmup` (`MCP_BSL_INDEX_WARMUP=true`, `index.warmup: true` в `config.yml`).
Прогрев выполняется **в фоновом потоке** — старт сервера и MCP-хендшейк не
блокируются, а к моменту первого semantic/hybrid-запроса модели обычно уже
загружены. Если семантика недоступна (нет моделей), warmup не роняет сервер —
keyword-поиск продолжает работать, а первый semantic/hybrid-запрос не
повисает на загрузке моделей дольше ~15 с (`SEMANTIC_READY_WAIT_TIMEOUT`):
при недошедшем прогреве он вернёт результаты keyword-поиска с пометкой о
неготовности семантики.

Статус сервера и готовность режимов в любой момент проверяются инструментом
`health`.

### Готовность к semantic/hybrid — первый запуск

semantic/hybrid-поиск требует два разовых шага, которые выполняются при первом
запросе (не при старте сервера):

1. **Скачивание моделей** — эмбеддер `ai-forever/ru-en-RoSBERTa` и реранкер
   `DiTy/cross-encoder-russian-msmarco` загружаются из HuggingFace в
   `storage.models_cache` (по умолчанию `./data/models`). Требуется ~2 ГБ
   дискового пространства и соединение с интернетом.
2. **Сборка индекса** — готовое Qdrant-хранилище сохраняется в
   `./data/qdrant` (коллекция `platform_context`, стабильные UUID5-точки).

До завершения этих шагов первый `semantic`/`hybrid`-запрос может занимать
минуты (скачивание + эмбеддинг). Последующие запросы — порядка сотен
миллисекунд. Фоновая загрузка (`index.warmup: true`) не блокирует запуск,
а повторные запросы во время прогрева быстро деградируют на keyword с пометкой.
Чтобы выполнить оба шага заранее, не дожидаясь реального запроса:

```bash
uv sync --extra local
mcp-bsl-context -c config.yml --reindex   # завершится после сборки индекса
```

Полная пересборка с нуля (перескачивание моделей и индекса):

```bash
rm -rf data/models data/qdrant
mcp-bsl-context -c config.yml --reindex
```

## Благодарности

- [alkoleft/mcp-bsl-platform-context](https://github.com/alkoleft/mcp-bsl-platform-context) — оригинальный Kotlin-проект
- [DitriXNew/mcp-bsl-platform-context](https://github.com/DitriXNew/mcp-bsl-platform-context) — развитие оригинального проекта
- [Model Context Protocol](https://modelcontextprotocol.io/) — спецификация MCP
- [FastMCP](https://github.com/jlowin/fastmcp) — Python MCP-фреймворк

## Лицензия

MIT
