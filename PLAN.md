# План: оптимизация и улучшение MCP-сервера (по результатам код-ревью)

Дата: 19.09.2026
Решения по развилкам приняты: полный объём (этапы 1–6), индексация членов типов, синтетические + slow-тесты реального HBK, отпечаток версии+контента для Qdrant, удаление мёртвого кода.

## Состояние на старте

- 216 тестов проходят за ~0.5 с (в CLAUDE.md заявлено 306 — устарело).
- Страницы реального HBK в UTF-8 c BOM `EF BB BF` (не UTF-16LE) — при декодировании `utf-8` остаётся лишний `\ufeff`, нужен `utf-8-sig`.

---

## Этап 1. Корректность поиска

- [ ] `infrastructure/search/engine.py`:104:128-135 — единый ключ дедупликации `(api_type, type_name, name)` вместо `item.name.lower()` (сейчас методы разных типов схлопываются).
- [ ] `infrastructure/search/strategies.py:96-136` — `TypeMemberSearch` учитывает фильтр `api_type` у каждого кандидата (сейчас фильтр игнорируется, `search(..., type=property)` возвращает и методы).
- [ ] `infrastructure/search/hybrid_engine.py:121-124` — `_definition_key` → единая схема `(api_type, type_name, name)` c RR? согласовать с engine.
- [ ] `infrastructure/storage/storage.py:52-56` — реализовать индексацию членов типов (member-index `(type_name, member_name)`) для однословного поиска; убрать пустой цикл-заглушку.
- [ ] `domain/services.py:87-93` — `find_member_by_type_and_name` делегирует в `repository.find_type_member` (сейчас дублируется линейный скан).

## Этап 2. Устойчивость сервера и конфига

- [ ] `mcp_bsl_context/server.py` — декоратор `_safe_call` вокруг всех тулов (DomainException → форматированный ответ, RuntimeError → сообщение, Exception → «Internal error» без стектрейса клиенту). Обернуть и `get_platform_info`.
- [ ] `server.py:57-77` — не кэшировать транзиентные init-ошибки семантики навсегда: различать перманентную (отсутствие зависимостей) и ретраябельную (сеть/API); кэшировать только успех.
- [ ] `config.py` — валидация в `load_config()`/`AppConfig.validate()`: enum-поля (`search.default_mode`, `embeddings.provider`), обязательность `json_path` при `data_source=json`; удалить дублирование из `__main__.py`.
- [ ] `config.py` — `_coerce_value` в try/except → `logger.warning` + default (сейчас опечатка в env валит сервер).
- [ ] `config.py` — warning на неизвестные секции/ключи YAML (тихий игнор опечаток).
- [ ] `server.py:486-500` — класс-метод `PlatformContextStorage.from_loaded_data()` вместо обхода конструктора через `__new__`; импорт `threading` сверху модуля.

## Этап 3. Надёжность семантики и провайдеров

- [ ] `infrastructure/search/semantic_engine.py` — отпечаток версии+контента (UUID5 от версии платформы и отсортированных ключей сущностей) в коллекции; пересборка при несовпадении (сейчас переключение версии платформы при том же `qdrant_path` даёт молча неверные результаты).
- [ ] `semantic_engine.py:142-152,169-172` — заменить `except Exception: pass` на логирование; различать «коллекции нет» (пересоздание) и «клиент сломан» (fail-fast).
- [ ] `semantic_engine.py:160-162` — `_build_index` проверяет, что коллекция реально создана.
- [ ] `infrastructure/embeddings/provider.py` — `httpx.Client` с keep-alive + retry/backoff на 429/5xx; строгая валидация `len(embeddings) == len(texts)` (сейчас молча обрезает точки).
- [ ] `semantic_engine.py:186-189` — валидация длин батчей при upsert; `convert_to_numpy=True`.
- [ ] `infrastructure/embeddings/reranker.py:135` — `item.get("index")` вместо прямого доступа (KeyError при малформированном ответе).
- [ ] `infrastructure/hbk/content_reader.py:36,42` — декодирование `utf-8-sig` (снять BOM).

## Этап 4. Производительность

- [x] `infrastructure/hbk/container_reader.py` — `mmap` вместо `read_bytes()`; срезы через `memoryview`/без лишних копий (сейчас ~3× пиковый расход памяти).
- [x] `content_reader.py:38-42` — lowercase-name-set для O(1) промахов имён (сейчас полный проход при каждом промахе).
- [x] `content_reader.py:76-82` — `_inflate_pack_block`: фильтровать `name.endswith("/")`, брать первый файл с непустым `file_size`, информативная ошибка.
- [x] `strategies.py:190-213` — инвертированный индекс «слово → сущности» для `WordOrderSearch` + ранний выход при насыщении ≥ limit.
- [x] `strategies.py:35` — добавить `ёЁ` в классы символов `_split_words`; precompiled regex в константу.
- [x] `semantic_engine.py`/`hybrid_engine.py` — именованные константы fetch-множителей, одна точка умножения (сейчас амплификация до 9×).
- [x] `hybrid_engine.py:86` — текст для переранжирования брать из payload/с контекстом типа, чтобы совпадал с индексированным.

## Этап 5. Полировка и мёртвый код

- [ ] `presentation/formatter.py` — `_escape_inline()` (`\`, `` ` ``, `*`, `_`, `|`, `[`, `]`, `<`, `>`) для имён/описаний/таблиц; `**Constructors (N):**` (двоеточие); обрезка по границе слова.
- [ ] `domain/docs_service.py:92` — `_plural()` → «совпадение/совпадения/совпадений» (сейчас «1 совпадений»).
- [ ] `server.py` — лимит вывода `get_members` (10–20 + «…ещё M», опциональный `offset`); `SERVER_INSTRUCTIONS` в константу модуля; `type` → `type_filter`; `_format_lookup_error` — по типам исключений, не по тексту сообщения.
- [ ] `__main__.py` — убрать недостижимую click-ветку (click обязательная зависимость); подавление логов MCP через публичный API.
- [ ] `config.py` — дополнить `_ENV_MAPPING` (`search.default_mode`, `embeddings.*`, `reranker.*`, `storage.*`); удалить `IndexConfig.reset_cache`.
- [ ] Удалить мёртвое: `SearchOptions.case_sensitive/exact_match`, `DefinitionNotFoundException`, `ApiType.get_plural_name`, nullable `active_hbk_path` вместо пустого `Path()`.

## Этап 6. Тесты

- [ ] `tests/fixtures/` — хелпер сборки синтетического мини-HBK (header + PackBlock + FileStorage): unit-тесты `container_reader` (обычные + multi-page chains 8.3.27+), `toc_parser` (включая битый/усечённый TOC), `html_handler`, парсеров.
- [ ] `tests/test_real_hbk.py` — slow-тест (@pytest.mark.slow) загрузки `8.3.27.72/shcntx_ru.hbk`: непустые методы/свойства/типы + happy-path поиска.
- [ ] `tests/conftest.py` — единый `FakeStorage` (сейчас 4 копии); стабильный хеш эмбеддингов (md5 вместо рандомизированного `hash()`).
- [ ] Тесты новых фич: member-index (однословный поиск), фильтр `api_type`, дедупликация по типу, инвалидация индекса, экранирование markdown, плюрализация.

---

## Верификация

- После каждого этапа: `uv run python -m pytest -q` (216 существующих + новые; slow через `-m slow`).
- E2E-проверки:
  - keyword «Добавить» находит члены типов (однословный поиск).
  - `search type=property` не возвращает методы.
  - hybrid/semantic без регрессий.

## Риски

- `mmap` затрагивает хрупкий парсер — держать существующие тесты зелёными на каждом шаге.
- Смена ключей дедупликации меняет выдачу — зафиксировать тестами/снапшотами.
- Реальный HBK (40 МБ) — не попадает в обычный прогон CI без маркера `slow`.