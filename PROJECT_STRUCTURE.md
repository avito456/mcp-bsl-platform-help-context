# Структура проекта mcp-bsl-platform-help-context

**mcp-bsl-platform-help-context** — MCP-сервер для доступа к документации API платформы 1С:Предприятие (BSL). Python-порт Kotlin-проекта [mcp-bsl-platform-context](https://github.com/alkoleft/mcp-bsl-platform-context).

Tech-стек: Python 3.10+, FastMCP, BeautifulSoup4/lxml, Click, PyYAML, Qdrant client, sentence-transformers. Упаковка — `pyproject.toml` (setuptools, пакет `mcp_bsl_context`, CLI `mcp-bsl-context`).

---

## 1. Блок-схема структуры проекта

### 1.1. Общая архитектура

```mermaid
flowchart TB
    CLI[CLI: __main__.py<br/>(click) + config.yaml / env / args]
    CFG[config.py<br/>AppConfig: YAML < env < CLI]

    CLI --> CFG

    CFG --> SRV[server.py — FastMCP, 9 MCP-инструментов<br/>create_server / BslContextServer]

    subgraph DOMAIN["domain/ — бизнес-слой (frozen dataclasses)"]
        ENT[entities.py<br/>Definition, Method/Property/PlatformTypeDefinition]
        EN[enums.py<br/>ApiType: METHOD/PROPERTY/TYPE/CONSTRUCTOR]
        EXC[exceptions.py<br/>иерархия исключений]
        VO[value_objects.py<br/>SearchQuery, PlatformVersion]
        SRVC[services.py<br/>ContextSearchService]
        DS[docs_service.py<br/>DocsInfoService]
    end

    subgraph INFRA["infrastructure/ — данные и поиск"]
        subgraph HBK["hbk/ — парсер .hbk"]
            CR[container_reader.py<br/>бинарный контейнер (mmap)]
            CTR[content_reader.py<br/>PackBlock TOC + FileStorage ZIP]
            XTR[context_reader.py<br/>оркестратор чтения]
            PV[pages_visitor.py<br/>обход дерева страниц]
TOC["toc/ — токенизатор + парсер оглавления"]
            PARS["parsers/ — HTML-парсеры (BeautifulSoup)"]
        end

        subgraph JSON["json_loader/"]
            JCL[json_context_loader.py<br/>альтернативный источник]
        end

        subgraph SEARCH["search/ — поисковые движки"]
            IDX[indexes.py<br/>HashIndex, StartWithIndex]
            STR[strategies.py<br/>4 стратегии keyword-поиска]
            ENG[engine.py<br/>SimpleSearchEngine]
            SEM[semantic_engine.py<br/>SemanticSearchEngine (Qdrant+emb)]
            HYB[hybrid_engine.py<br/>HybridSearchEngine (RRF+rerank)]
        end

        subgraph EMB["embeddings/ — ML-модели"]
            PR[provider.py<br/>EmbeddingProvider local/API]
            RK[reranker.py<br/>cross-encoder reranking]
            DB[document_builder.py<br/>entities → эмбеддинг-тексты]
        end

        subgraph STORAGE["storage/ — хранилище"]
            ST[storage.py<br/>PlatformContextStorage, lazy]
            REPO[repository.py<br/>PlatformRepository фасад]
            LD[loader.py<br/>поиск shcntx_ru.hbk]
            MAP[mapper.py<br/>маппинг сущностей]
            VD[version_discovery.py<br/>мультиверсионность]
        end
    end

    subgraph PRES["presentation/"]
        FMT[formatter.py<br/>MarkdownFormatter]
    end

    subgraph DOC["docinfo/ — встроенная документация"]
        STM[strict-types.md]
        GL[guideline.md]
    end

    SRV --> DOMAIN
    SRV --> INFRA
    SRV --> PRES
    SRV --> DOC

    HBK -. "источники данных" .-> STORAGE
    JSON -. "источники данных" .-> STORAGE
    STORAGE --> SEARCH
    EMB --> SEM
    EMB --> HYB
    SEARCH --> SRVC
    SRVC --> SRV
```

### 1.2. Поток данных и обработки запроса

```mermaid
flowchart LR
    A[shcntx_ru.hbk] --> B[container_reader<br/>бинарный контейнер]
    B --> C[content_reader<br/>PackBlock → TOC, FileStorage → HTML]
    C --> D[pages_visitor + parsers<br/>обход и парсинг страниц]
    D --> E[PlatformContext<br/>методы/свойства/типы/перечисления]
    E --> F[storage.mapper → entities]
    F --> G[PlatformContextStorage<br/>lazy, thread-safe]
    G --> H[PlatformRepository]

    H --> I[ContextSearchService]
    I --> J[server: search / info / get_member(s) / ...]
    J --> K[MarkdownFormatter]
    K --> L[Ответ MCP-клиенту]

    G -.-> S1[SimpleSearchEngine<br/>keyword]
    G -.-> S2[SemanticSearchEngine<br/>Qdrant ANN + rerank]
    S1 --> H1[HybridSearchEngine<br/>RRF-слияние]
    S2 --> H1
```

---

## 2. Назначение модулей

| Модуль / файл | Строки | Назначение |
|---|---|---|
| `pyproject.toml` | 61 | Упаковка setuptools, зависимости, extras (`local`, `dev`), CLI-скрипт `mcp-bsl-context`, настройки pytest |
| `config.example.yml` / `config.yml` | ~60 | Шаблон и рабочая YAML-конфигурация: `server`, `platform`, `search`, `embeddings`, `reranker`, `storage`, `index`, `docs` |
| `Dockerfile` / `Dockerfile.gpu` / `docker-compose.yml` / `docker-entrypoint.sh` | — | Образы CPU/GPU (GPU + локальные модели), профили compose (`gpu`, `json`), проверка здоровья |
| `data/` | — | Runtime-данные: Qdrant-индекс (`data/qdrant`), HF-кэш моделей (`data/models`) |
| `8.3.27.72/shcntx_ru.hbk` | — | Пример исходного файла документации платформы 1С (HBK) |
| `tests/` | 20 файлов | Pytest: конфиг, HBK-чтение, поисковые движки, семантика, storage, сервисы, форматтер |

### 2.1. Корень пакета `mcp_bsl_context/`

| Файл | Строки | Назначение |
|---|---|---|
| `__main__.py` | 133 | CLI (click): парсинг `--config/--mode/--port/--data-source/--reindex` и т.д., сборка overrides, валидация, запуск `create_server(...).run(...)` по транспорту |
| `config.py` | 311 | `AppConfig` + под-конфиги (Server/Platform/Search/Embeddings/Reranker/Storage/Index/Docs). Мерж YAML < env (`MCP_BSL_*`) < CLI, валидация |
| `server.py` | 554 | FastMCP-сервер: 9 MCP-инструментов, ленивая инициализация семантики (`_LazySemanticState`), инструкции для AI, обработка ошибок |

### 2.2. `domain/` — бизнес-слой

| Файл | Строки | Назначение |
|---|---|---|
| `entities.py` | 76 | Frozen-сущности: `ParameterDefinition`, `Signature`, `MethodDefinition`, `PropertyDefinition`, `PlatformTypeDefinition`, унифицированный `Definition` (union) + ключи дедупликации |
| `enums.py` | 41 | `ApiType` (METHOD/PROPERTY/TYPE/CONSTRUCTOR) с русско-английским маппингом строк |
| `exceptions.py` | 21 | Иерархия исключений (`DomainException`, `PlatformContextLoadException`, `PlatformTypeNotFoundException`, `TypeMemberNotFoundException` и др.) |
| `value_objects.py` | 72 | `SearchQuery`, `PlatformVersion` (парсинг/сортировка 8.XX.XX) + `find_closest_version` (выбор ближайшей версии) |
| `services.py` | 117 | `ContextSearchService` — оркестратор: search, get_info, find_member*, find_constructors; валидация и лимиты |
| `docs_service.py` | 129 | `DocsInfoService` — строгая типизация BSL + coding guideline, ленивый парсинг тем, полнотекстовый поиск |

### 2.3. `infrastructure/hbk/` — парсер бинарного формата HBK

| Файл | Строки | Назначение |
|---|---|---|
| `container_reader.py` | 136 | Чтение бинарного контейнера HBK (mmap, заголовок, UTF-16LE имена, тела файлов) |
| `content_reader.py` | 88 | Распаковка `PackBlock` → TOC (bracket-формат) и `FileStorage` → ZIP HTML-страниц; `HbkContext.read_page` |
| `context_reader.py` | 52 | Оркестратор: собирает глобальные методы/свойства, типы и перечисления через visitor |
| `models.py` | 100 | Промежуточные модели (`ObjectInfo`, `MethodInfo`, `PropertyInfo`, `EnumInfo`, `SignatureInfo`, `Page`) |
| `pages_visitor.py` | 243 | Visitor: классификация страниц (global context, enum catalog, type catalog, properties/methods/ctors) и обход дерева |
| `toc/tokenizer.py` | 81 | Токенизация TOC-файла bracket-структуры |
| `toc/toc.py` | 85 | Модель `Toc` + навигация по узлам ТОС |
| `toc/toc_parser.py` | 161 | Парсинг оглавления в дерево `Toc` |
| `parsers/base.py` | 22 | Базовый HTML-парсер (BeautifulSoup) |
| `parsers/html_handler.py` | 207 | Разбор структуры HTML-страниц ХП (заголовки V8SH_heading/chapter и т.д.) |
| `parsers/pages_parser.py` | 50 | Разбор страницы на сущности (диспетчер по типу страницы) |
| `parsers/object_parser.py` | 39 | Парсинг определения типа/объекта |
| `parsers/method_parser.py` | 117 | Парсинг метода (сигнатуры, параметры, возвращаемый тип) |
| `parsers/property_parser.py` | 50 | Парсинг свойства (тип, read-only) |
| `parsers/constructor_parser.py` | 77 | Парсинг конструкторов |
| `parsers/enum_parser.py` / `enum_value_parser.py` | 36/36 | Парсинг перечислений и значений перечислений |

### 2.4. `infrastructure/json_loader/` — альтернативный источник

| Файл | Строки | Назначение |
|---|---|---|
| `json_context_loader.py` | 129 | Загрузка предварительно экспортированного контекста из JSON (методы/свойства/типы/конструкторы), поддержка комбинированного `context.json` |

### 2.5. `infrastructure/search/` — поисковые движки

| Файл | Строки | Назначение |
|---|---|---|
| `indexes.py` | 77 | `HashIndex`, `StartWithIndex` — in-memory поисковые индексы |
| `strategies.py` | 339 | 4 стратегии keyword-поиска: CompoundTypeSearch, TypeMemberSearch, RegularSearch, WordOrderSearch |
| `engine.py` | 174 | `SimpleSearchEngine` — keyword-движок поверх стратегий и индексов |
| `semantic_engine.py` | 288 | `SemanticSearchEngine` — эмбеддинг → ANN-поиск в Qdrant embedded → опциональный rerank; ленивое построение индекса с fingerprint |
| `hybrid_engine.py` | 144 | `HybridSearchEngine` — параллельно keyword+semantic, RRF-слияние (k=60) + rerank |

### 2.6. `infrastructure/embeddings/` — ML-модели

| Файл | Строки | Назначение |
|---|---|---|
| `provider.py` | 200 | `EmbeddingProvider` — фабрика (`local` sentence-transformers / `openai-compatible`), кэширование моделей |
| `reranker.py` | 177 | `Reranker` — cross-encoder (local / API), переранжирование по релевантности |
| `document_builder.py` | 194 | `DocumentBuilder` — сущности → эмбеддинг-тексты + Qdrant payload (uuid5-точки) |

### 2.7. `infrastructure/storage/` — хранилище и репозиторий

| Файл | Строки | Назначение |
|---|---|---|
| `storage.py` | 105 | `PlatformContextStorage` — thread-safe lazy загрузка, построение индекса членов, маппинг `member_owner` |
| `repository.py` | 34 | `PlatformRepository` — фасад: search, find_type/method/property/member |
| `loader.py` | 50 | `PlatformContextLoader` — поиск `shcntx_ru.hbk` (прямой + рекурсивный) и запуск HBK-чтения |
| `mapper.py` | 64 | Маппинг HBK-моделей (Info) в доменные сущности |
| `version_discovery.py` | 153 | `VersionDiscovery` — обнаружение версий платформы в каталоге (3 layout-схемы), `PlatformVersionInfo` |

### 2.8. `presentation/` и `docinfo/`

| Файл | Строки | Назначение |
|---|---|---|
| `presentation/formatter.py` | 257 | `MarkdownFormatter` — сериализация Definition в Markdown-таблицы для ответов MCP |
| `docinfo/strict-types.md` | — | Встроенная документация по строгой типизации BSL |
| `docinfo/guideline.md` | — | Встроенные рекомендации по стилю кода |

---

## 3. MCP-инструменты (server.py)

| Инструмент | Назначение |
|---|---|
| `search` | Поиск по API: keyword / semantic / hybrid, фильтр по типу, limit 1–50 |
| `info` | Детальная информация по точному имени + типу |
| `get_member` | Метод/свойство конкретного типа |
| `get_members` | Полный список методов и свойств типа (пагинация limit/offset) |
| `get_constructors` | Сигнатуры конструкторов типа |
| `get_platform_info` | Активная и доступные версии платформы |
| `get_coding_guideline` | Рекомендации по стилю кода BSL |
| `get_strict_typing_info` | Документация по строгой типизации BSL (`topic='topics'` — список тем) |
| `search_strict_typing` | Текстовый поиск по документации строгой типизации с контекстом |

---

## 4. Описание структуры

Проект построен по **слоистой архитектуре** (clean/hexagonal-lite): `domain` → `infrastructure` → `presentation`, собранных в FastMCP-сервере.

- **Входная точка** — `__main__.py` (CLI) + `config.py`: конфигурация собирается с приоритетом YAML < `MCP_BSL_*` env < CLI-аргументы, проходит валидацию и передаёт `AppConfig` в `create_server`.
- **Доменный слой** (`domain/`) не зависит от инфраструктуры: frozen-сущности, перечисления `ApiType`, value-objectы (`SearchQuery`, `PlatformVersion`), сервисы `ContextSearchService` и `DocsInfoService`, иерархия исключений.
- **Инфраструктура** разделена на 5 блоков:
  1. `hbk/` — полный пайплайн чтения бинарного HBK: контейнер → TOC + FileStorage → visitor → HTML-парсеры;
  2. `json_loader/` — альтернативный источник данных (pre-exported JSON);
  3. `storage/` — lazy-хранилище (`PlatformContextStorage`), фасад-репозиторий, маппер и обнаружение версий;
  4. `search/` — три движка: keyword (`SimpleSearchEngine`, 4 стратегии), semantic (Qdrant + embeddings), hybrid (RRF + rerank);
  5. `embeddings/` — ML-обвязка: эмбеддер, реранкер, сборщик документов для Qdrant.
- **Презентация** — `presentation/formatter.py` превращает `Definition` в Markdown-таблицы.
- **Встроенная документация** — `docinfo/` (strict-types.md, guideline.md), подгружается через `DocsInfoService`.
- **Интеграция сервера**: `server.py` регистрирует 9 MCP-инструментов; семантические/гибридные компоненты инициализируются лениво при первом запросе; поддержка транспортов stdio / sse / streamable-http через `server.run(transport=...)`.