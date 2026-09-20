"""FastMCP server with platform context tools."""

from __future__ import annotations

import functools
import importlib.resources as pkg_resources
import logging
import re
import threading
from pathlib import Path
from typing import Any, Callable

from mcp_bsl_context.config import AppConfig
from mcp_bsl_context.domain.docs_service import DocsInfoService, DocsLoadException
from mcp_bsl_context.domain.entities import Definition
from mcp_bsl_context.domain.exceptions import (
    DomainException,
    PlatformContextLoadException,
    PlatformTypeNotFoundException,
    TypeMemberNotFoundException,
)
from mcp_bsl_context.domain.services import ContextSearchService
from mcp_bsl_context.domain.value_objects import PlatformVersion, find_closest_version
from mcp_bsl_context.infrastructure.search.engine import SimpleSearchEngine
from mcp_bsl_context.infrastructure.storage.loader import PlatformContextLoader
from mcp_bsl_context.infrastructure.storage.repository import PlatformRepository
from mcp_bsl_context.infrastructure.storage.storage import PlatformContextStorage
from mcp_bsl_context.infrastructure.storage.version_discovery import (
    PlatformVersionInfo,
    VersionDiscovery,
)
from mcp_bsl_context.presentation.formatter import MarkdownFormatter

logger = logging.getLogger(__name__)

MIN_LIMIT = 1
MAX_LIMIT = 50
DEFAULT_LIMIT = 10
VALID_MODES = {"keyword", "semantic", "hybrid"}
DEFAULT_MEMBERS_LIMIT = 20

# Cap for how long a semantic/hybrid call waits for the models to become
# ready before degrading to a keyword fallback (see _LazySemanticState).
# Bounded so the request always completes well inside MCP client timeouts
# instead of blocking forever on model loading.
SEMANTIC_READY_WAIT_TIMEOUT = 15.0

SERVER_INSTRUCTIONS = (
    "Этот MCP-сервер предоставляет доступ к документации API платформы "
    "1С:Предприятие. Инструкции по использованию инструментов:\n"
    "1. Начинайте с инструмента search для нахождения нужных элементов API. "
    "Используйте конкретные термины 1С (русские или английские), например "
    "'НайтиПоСсылкам', 'ТаблицаЗначений.Добавить'.\n"
    "2. Результаты search возвращают точные имена элементов в таблицах. "
    "Используйте их как есть при последующих вызовах info/get_member(s). "
    "Шаблонные типы справочников/документов имеют вид "
    "'СправочникОбъект.<Имя справочника>' — подставляйте имя целиком, "
    "включая угловые скобки и '<Имя справочника>'.\n"
    "3. После нахождения элемента получайте полную документацию через info "
    "по точному имени.\n"
    "4. Для обзора всех методов/свойств типа сначала вызовите get_members, "
    "затем get_member для конкретного метода или свойства. Первым вызовом "
    "get_members возвращается до 20 членов — используйте параметры limit и "
    "offset для постраничного просмотра полного списка.\n"
    "5. Для создания объектов используйте get_constructors.\n"
    "6. Поиск поддерживает три режима: keyword (быстрый, по именам — "
    "рекомендуется для точных имён API), semantic и hybrid (для запросов на "
    "естественном языке, например 'как добавить строку в таблицу значений'). "
    "По умолчанию используется режим из конфигурации (hybrid).\n"
    "7. Для вопросов о строгой типизации BSL используйте "
    "get_strict_typing_info (сначала topic='topics' для списка тем), для "
    "рекомендаций по стилю кода — get_coding_guideline.\n"
    "8. get_platform_info сообщает версию платформы, для которой доступна "
    "документация.\n"
    "9. Если поиск не дал результатов, посмотрите предложенные варианты "
    "(Возможно, вы имели в виду) или попробуйте другой режим/более общий "
    "термин; не выдумывайте имена API, которых нет в ответах.\n"
    "10. health сообщает статус сервера и готовность режимов поиска. "
    "Первый semantic/hybrid-запрос может занять несколько минут "
    "(инициализация моделей); при недоступности семантики search вернёт "
    "результаты keyword с пометкой."
)


class _LazySemanticState:
    """Lazy-loaded semantic/hybrid search components.

    Models and Qdrant are not initialized until the first
    semantic or hybrid search request.  This avoids loading
    heavy ML models when only keyword search is used.
    """

    def __init__(
        self,
        config: AppConfig,
        storage: PlatformContextStorage,
        keyword_engine: SimpleSearchEngine,
    ) -> None:
        self._config = config
        self._storage = storage
        self._keyword_engine = keyword_engine
        self._semantic_engine = None
        self._hybrid_engine = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._warmup_started = False
        self._initialized = False
        self._init_error: str | None = None

    def _ensure_initialized(self) -> None:
        if self._initialized:
            if self._init_error:
                raise RuntimeError(self._init_error)
            return
        with self._lock:
            if self._initialized:
                if self._init_error:
                    raise RuntimeError(self._init_error)
                return
            try:
                self._do_init()
            except ImportError as exc:
                # Missing dependencies are permanent — cache the failure.
                self._init_error = (
                    f"Failed to initialize semantic search: {exc}. "
                    "Use mode='keyword' or install dependencies: "
                    "pip install 'mcp-bsl-context[local]'"
                )
                self._initialized = True
                self._ready.set()
                raise RuntimeError(self._init_error) from exc
            except Exception as exc:
                # Transient failures (network, API timeouts) are NOT cached:
                # the next request will retry initialization.
                logger.exception(
                    "Semantic search initialization failed; will retry on next request"
                )
                raise RuntimeError(
                    f"Failed to initialize semantic search: {exc}. "
                    "Try again or use mode='keyword'."
                ) from exc
            self._initialized = True
            self._ready.set()

    def _run_init_in_background(self) -> None:
        """Run initialization in a daemon thread (used for background warmup)."""
        try:
            self._ensure_initialized()
        except Exception as exc:
            # Transient/persistent failures are logged here; the flag is reset
            # so a later request can retry initialization from scratch.
            with self._lock:
                self._warmup_started = False
            logger.warning("Background warmup failed (keyword mode still works): %s", exc)

    def start_background_warmup(self) -> None:
        """Eagerly load models and prebuild the index in a background thread.

        Non-blocking: the server keeps serving requests (handshake, keyword
        search) while the models load. This avoids stalling the MCP client on
        the first semantic/hybrid call, which previously exceeded client
        timeouts and broke the connection.
        """
        if self._initialized or self._warmup_started:
            return
        with self._lock:
            if self._initialized or self._warmup_started:
                return
            self._warmup_started = True
            logger.info("Starting background warmup of semantic search...")
            threading.Thread(
                target=self._run_init_in_background,
                name="semantic-warmup",
                daemon=True,
            ).start()

    def _wait_readiness(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for initialization to finish.

        Returns True when the semantic search became ready or failed
        permanently; False if still initializing after the timeout.
        """
        self.start_background_warmup()
        return self._ready.wait(timeout)

    def _ensure_initialized_bounded(self, timeout: float) -> None:
        """Initialize semantic search without blocking beyond ``timeout``.

        Starts initialization in the background if needed and waits up to
        ``timeout`` for it to complete. If the models are still loading after
        the deadline, raises RuntimeError so the caller degrades gracefully
        (e.g. keyword fallback) instead of exceeding the MCP client timeout.
        """
        if self._initialized:
            if self._init_error:
                raise RuntimeError(self._init_error)
            return
        if not self._wait_readiness(timeout):
            raise RuntimeError(
                "Semantic search is still initializing (models are loading "
                "in the background). Try again in a few seconds or use "
                "mode='keyword'."
            )
        if self._init_error:
            raise RuntimeError(self._init_error)

    @property
    def status(self) -> str:
        """Human-readable semantic readiness for the ``health`` tool."""
        if self._init_error:
            return f"failed: {self._init_error}"
        if self._initialized:
            return "ready"
        if self._warmup_started:
            return "initializing… (модели и индекс загружаются в фоне)"
        return "not-initialized (first semantic/hybrid call will load models and index)"

    def initialize(self) -> None:
        """Eagerly load models and ensure the index is ready.

        Blocking — used at startup when a forced reindex is requested
        (``--reindex``), so the semantic index is (re)built before the first
        client request. For the non-blocking variant see
        ``start_background_warmup``.
        """
        self._ensure_initialized()

    def _do_init(self) -> None:
        from mcp_bsl_context.infrastructure.embeddings.provider import (
            create_embedding_provider,
        )
        from mcp_bsl_context.infrastructure.embeddings.reranker import (
            create_reranker,
        )
        from mcp_bsl_context.infrastructure.search.hybrid_engine import (
            HybridSearchEngine,
        )
        from mcp_bsl_context.infrastructure.search.semantic_engine import (
            SemanticSearchEngine,
        )

        cache_dir = self._config.storage.models_cache
        logger.info("Initializing semantic search components...")

        embedder = create_embedding_provider(
            self._config.embeddings, cache_dir=cache_dir
        )
        reranker = create_reranker(
            self._config.reranker, cache_dir=cache_dir
        )

        self._semantic_engine = SemanticSearchEngine(
            embedding_provider=embedder,
            qdrant_path=self._config.storage.qdrant_path,
            reranker=reranker,
        )

        # Force reindex if configured
        self._semantic_engine.ensure_ready(
            self._storage,
            force_reindex=self._config.index.reindex,
        )

        self._hybrid_engine = HybridSearchEngine(
            keyword_engine=self._keyword_engine,
            semantic_engine=self._semantic_engine,
            reranker=reranker,
        )
        logger.info("Semantic search components ready")

    def semantic_search(
        self,
        query: str,
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[Definition]:
        self._ensure_initialized_bounded(SEMANTIC_READY_WAIT_TIMEOUT)
        return self._semantic_engine.search(
            query, self._storage, limit=limit, type_filter=type_filter
        )

    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[Definition]:
        self._ensure_initialized_bounded(SEMANTIC_READY_WAIT_TIMEOUT)
        return self._hybrid_engine.search(
            query, self._storage, limit=limit, type_filter=type_filter
        )


def create_server(config: AppConfig):
    """Create and configure the MCP server.

    Args:
        config: Application configuration (YAML + env + CLI merged).
    """
    from fastmcp import FastMCP

    config.validate()

    mcp = FastMCP("mcp-bsl-context", instructions=SERVER_INSTRUCTIONS)

    # Wire dependencies
    loader = PlatformContextLoader()

    if config.platform.data_source == "json":
        storage = _create_json_storage(config.platform.json_path)
        version_info = PlatformVersionInfo(
            active_version=None,
            active_hbk_path=None,
            available_versions=[],
        )
    else:
        storage, version_info = _create_hbk_storage(loader, config)

    keyword_engine = SimpleSearchEngine(storage)
    repository = PlatformRepository(keyword_engine)
    service = ContextSearchService(repository)
    formatter = MarkdownFormatter()

    def _format_lookup_error(exc: DomainException) -> str:
        text = formatter.format_error(exc)
        if isinstance(
            exc, (PlatformTypeNotFoundException, TypeMemberNotFoundException)
        ):
            text += (
                "\n\n**Подсказка:** элемент не найден по точному имени. Найдите "
                "точное имя через `search` (по фрагменту имени или с фильтром "
                "`type_filter=type`) и используйте его как есть. Шаблонные типы "
                "справочников/документов задаются полностью, например "
                "`СправочникОбъект.<Имя справочника>`."
            )
        return text

    def _safe_call(domain_handler: Callable[[DomainException], str]) -> Callable:
        """Wrap a tool so unexpected exceptions never leak a traceback to the client."""
        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> str:
                try:
                    return fn(*args, **kwargs)
                except DomainException as e:
                    return domain_handler(e)
                except RuntimeError as e:
                    return f"**Error:** {e}"
                except Exception:
                    logger.exception("Unexpected error in tool '%s'", fn.__name__)
                    return (
                        "**Внутренняя ошибка:** произошла непредвиденная ошибка. "
                        "Попробуйте ещё раз или используйте режим keyword."
                    )
            return wrapper
        return decorator

    # Lazy-loaded semantic/hybrid components
    semantic_state = _LazySemanticState(config, storage, keyword_engine)

    # Forced reindex: eagerly build the semantic index before serving requests
    if config.index.reindex:
        logger.info("--reindex requested: building semantic index at startup...")
        semantic_state.initialize()

    # Warmup: load models and prepare the index WITHOUT blocking the handshake.
    # Models load in a background thread; non-fatal — keyword search keeps
    # working if semantic is unavailable.
    if config.index.warmup and not config.index.reindex:
        semantic_state.start_background_warmup()

    @mcp.tool()
    @_safe_call(lambda e: formatter.format_error(e))
    def search(
        query: str,
        mode: str | None = None,
        type_filter: str | None = None,
        limit: int | None = None,
    ) -> str:
        """Поиск по документации API платформы 1С:Предприятие.

        Поддерживает keyword (по ключевым словам), semantic (векторный) и hybrid (комбинированный) режимы.
        Для лучших результатов используйте конкретные термины 1С (русские или английские),
        например: 'НайтиПоСсылкам', 'FindByRef', 'ТаблицаЗначений.Добавить'.
        Для семантического поиска подходят запросы на естественном языке:
        'как добавить строку в таблицу значений'.

        Args:
            query: Поисковый запрос — имя метода/типа/свойства или текст на естественном языке
            mode: Режим поиска: 'keyword' (быстрый, по именам), 'semantic' (по смыслу), 'hybrid' (оба + rerank). По умолчанию из конфигурации
            type_filter: Фильтр по типу элемента: 'method', 'property' или 'type'
            limit: Максимальное количество результатов (1–50, по умолчанию 10)

        Примечания:
            - keyword-режим возвращает точные имена API — используйте их как есть
              в info/get_member(s).
            - Шаблонные типы справочников/документов указываются как
              'СправочникОбъект.<Имя справочника>' (с угловыми скобками).
            - semantic/hybrid-режимы понимают запросы на естественном языке.

        EN: Search 1C platform API docs by a Russian or English term, a type name,
        or a 'Type.Member' query (e.g. 'ТаблицаЗначений.Добавить'). keyword mode
        returns exact API names for use in info/get_member/get_members.
        If nothing matched, closest-known names are suggested.
        """
        effective_mode = mode or config.search.default_mode
        if effective_mode not in VALID_MODES:
            return formatter.format_error(
                ValueError(
                    f"Invalid search mode: '{effective_mode}'. "
                    f"Use: {', '.join(sorted(VALID_MODES))}"
                )
            )

        effective_limit = DEFAULT_LIMIT
        if limit is not None:
            effective_limit = max(MIN_LIMIT, min(limit, MAX_LIMIT))

        fallback_note = ""
        if effective_mode == "keyword":
            results = service.search_all(query, type_filter, effective_limit)
        else:
            try:
                if effective_mode == "semantic":
                    results = semantic_state.semantic_search(
                        query, limit=effective_limit, type_filter=type_filter
                    )
                else:  # hybrid
                    results = semantic_state.hybrid_search(
                        query, limit=effective_limit, type_filter=type_filter
                    )
            except RuntimeError as exc:
                # Semantic/hybrid unavailable — degrade to keyword and say so,
                # so the model isn't misled into thinking a semantic search ran.
                logger.warning(
                    "%s search unavailable (%s); falling back to keyword",
                    effective_mode,
                    exc,
                )
                results = service.search_all(query, type_filter, effective_limit)
                fallback_note = (
                    "\n_Режим %s недоступен (%s); показаны результаты "
                    "keyword-поиска._\n" % (effective_mode, exc)
                )
        if fallback_note:
            return (
                formatter.format_query(query)
                + formatter.format_search_results(results, member_owner=storage.member_owner)
                + fallback_note
            )
        output = (
            formatter.format_query(query)
            + formatter.format_search_results(
                results, member_owner=storage.member_owner
            )
        )
        if not results and not re.search(r"[. :]", query.strip()) and len(query.strip()) >= 3:
            # Nothing found and the query looks like a plain identifier —
            # offer closest-known names ("did you mean ...?").
            suggestions = keyword_engine.suggest(query)
            if suggestions:
                lines = [
                    "**Не найдено точных совпадений. Возможно, вы имели в виду:**"
                ]
                lines += [f"- `{s}`" for s in suggestions]
                lines.append(
                    "_Уточните запрос или вызовите info для одного из имён выше._"
                )
                output += "\n" + "\n".join(lines)
        return output

    @mcp.tool()
    @_safe_call(_format_lookup_error)
    def info(name: str, type_filter: str | None = None) -> str:
        """Получить детальную информацию о конкретном элементе API платформы 1С.

        Возвращает полное описание, сигнатуры, параметры, возвращаемое значение.
        Используйте точное имя элемента (полученное через search).

        Args:
            name: Точное имя элемента (например, 'НайтиПоСсылкам', 'FindByRef', 'ТаблицаЗначений')
            type_filter: Тип элемента: 'method' (метод), 'property' (свойство) или 'type' (тип).
                Необязателен — при отсутствии тип определяется автоматически
                (метод → свойство → тип); при неоднозначности будет возвращён список вариантов.

        EN: Get detailed info about an API element by exact name (Russian or
        English). type_filter is optional; ambiguity is reported back.
        """
        definition = service.get_info(name, type_filter)
        return formatter.format_member(definition)

    @mcp.tool()
    @_safe_call(_format_lookup_error)
    def get_member(type_name: str, member_name: str) -> str:
        """Получить информацию о методе или свойстве конкретного типа платформы 1С.

        Args:
            type_name: Имя типа (например, 'ТаблицаЗначений', 'ValueTable'). Для шаблонных типов — полное имя, например 'СправочникОбъект.<Имя справочника>'
            member_name: Имя метода или свойства внутри типа (например, 'Добавить', 'Количество')

        EN: Get a method or property of a specific type by exact names
        (Russian or English; owner type name plus member name, e.g. 'ValueTable','Add').
        """
        definition = service.find_member_by_type_and_name(type_name, member_name)
        return formatter.format_member(definition, type_name)

    @mcp.tool()
    @_safe_call(_format_lookup_error)
    def get_members(
        type_name: str,
        limit: int = DEFAULT_MEMBERS_LIMIT,
        offset: int = 0,
    ) -> str:
        """Получить методы и свойства типа платформы 1С (с постраничным выводом).

        Возвращает структурированный список методов и свойств для указанного
        типа с пагинацией: по умолчанию первые 20 членов; при наличии ещё
        элементов добавляется строка '…and N more members'.

        Args:
            type_name: Имя типа (например, 'ТаблицаЗначений', 'ValueTable', 'СправочникОбъект'). Для шаблонных типов — полное имя, например 'СправочникОбъект.<Имя справочника>'
            limit: Максимальное количество выводимых членов (1–100, по умолчанию 20)
            offset: Смещение для постраничного просмотра (по умолчанию 0)

        EN: List methods and properties of a type, paged (limit/offset).
        Accepts type names in Russian or English.
        """
        members = service.find_type_members(type_name)
        effective_limit = max(1, min(limit, 100))
        effective_offset = max(0, offset)
        return formatter.format_type_members(
            members, limit=effective_limit, offset=effective_offset
        )

    @mcp.tool()
    @_safe_call(_format_lookup_error)
    def get_constructors(type_name: str) -> str:
        """Получить сигнатуры конструкторов для создания экземпляров типа платформы 1С.

        Возвращает все варианты конструкторов с параметрами и описаниями.

        Args:
            type_name: Имя типа (например, 'ТаблицаЗначений', 'ValueTable', 'Массив'). Для шаблонных типов — полное имя, например 'СправочникОбъект.<Имя справочника>'

        EN: Get constructor signatures for instantiating a 1C platform type.
        Accepts type names in Russian or English (e.g. 'Массив' or 'Array').
        """
        constructors = service.find_constructors(type_name)
        return formatter.format_constructors(constructors, type_name)

    @mcp.tool()
    @_safe_call(lambda e: formatter.format_error(e))
    def get_platform_info() -> str:
        """Получить информацию о текущей версии платформы 1С и доступных версиях.

        Возвращает активную версию, путь к HBK-файлу и список всех
        обнаруженных версий платформы.

        EN: Report the active 1C platform version, HBK path, and all detected versions.
        """
        parts: list[str] = []

        if version_info.active_version:
            parts.append(f"**Active version:** {version_info.active_version}")
        else:
            parts.append("**Active version:** unknown")

        if version_info.active_hbk_path and str(version_info.active_hbk_path):
            parts.append(f"**HBK path:** `{version_info.active_hbk_path}`")

        if version_info.available_versions:
            sorted_versions = sorted(version_info.available_versions, reverse=True)
            parts.append(f"\n**Available versions ({len(sorted_versions)}):**")
            for v in sorted_versions:
                marker = " **(active)**" if v == version_info.active_version else ""
                parts.append(f"- {v}{marker}")
        else:
            parts.append("\n*Single-version mode — no other versions discovered.*")

        return "\n".join(parts)

    @mcp.tool()
    @_safe_call(lambda e: formatter.format_error(e))
    def health() -> str:
        """Получить статус сервера и готовность поисковых режимов.

        Полезен перед первым semantic/hybrid-запросом: семантика лениво
        инициализируется (скачивание моделей и сборка индекса) при первом
        обращении, что может занимать минуты. Возвращает версию платформы,
        источник данных, статистику контекста и состояние семантики.

        EN: Server readiness — platform version, data source, context stats
        (counts), and semantic-search state (not-initialized/failed/ready).

        """
        try:
            storage.ensure_loaded()
            semantic_status = semantic_state.status
            loaded = "yes"
        except Exception as exc:
            semantic_status = "n/a"
            loaded = "no"
        parts: list[str] = ["## Server health\n"]
        parts.append(f"**Platform version:** {version_info.active_version or 'unknown'}")
        parts.append(f"**Data source:** {config.platform.data_source}")
        parts.append(
            f"**Context loaded:** {loaded}"
            f" — {len(storage.methods)} methods, "
            f"{len(storage.properties)} properties, "
            f"{len(storage.types)} types"
        )
        parts.append(f"**Semantic search:** {semantic_status}")
        parts.append(f"**Default search mode:** {config.search.default_mode}")
        if config.index.reindex:
            parts.append("**Index:** forced rebuild on startup")
        elif config.index.warmup:
            parts.append("**Index:** warmup on startup")
        return "\n".join(parts)

    # --- Documentation tools (strict typing, coding guidelines) ---

    docs_service = _create_docs_service(config)

    @mcp.tool()
    @_safe_call(lambda e: formatter.format_error(e))
    def get_coding_guideline() -> str:
        """Получить рекомендации по стилю кода BSL (1С:Предприятие).

        Возвращает полный набор рекомендаций по написанию качественного кода 1С.

        EN: Get BSL (1C:Enterprise) coding-style guidelines and best practices.
        """
        return docs_service.get_guideline()

    @mcp.tool()
    @_safe_call(lambda e: formatter.format_error(e))
    def get_strict_typing_info(topic: str) -> str:
        """Получить документацию по строгой типизации BSL по теме.

        Строгая типизация позволяет контролировать типы в коде 1С:Предприятия 8
        с помощью аннотации @strict-types и типизирующих комментариев.

        Используйте topic='topics' для получения списка всех доступных тем.

        Args:
            topic: Название темы (например, 'overview', 'arrays', 'constructor-functions')
                   или 'topics' для списка всех тем.

        EN: Get strict-typing docs for a topic ('topics' lists available topics).
        """
        return docs_service.get_strict_typing_info(topic)

    @mcp.tool()
    @_safe_call(lambda e: formatter.format_error(e))
    def search_strict_typing(query: str) -> str:
        """Поиск по документации строгой типизации BSL.

        Выполняет текстовый поиск по всем разделам документации строгой типизации
        и возвращает совпадения с контекстом.

        Args:
            query: Поисковый запрос (например, 'Массив', 'конструктор', 'ТаблицаЗначений')

        EN: Text-search strict-typing docs; returns matching sections with context.
        """
        return docs_service.search_strict_typing(query)

    return mcp


def _create_hbk_storage(
    loader: PlatformContextLoader,
    config: AppConfig,
) -> tuple[PlatformContextStorage, PlatformVersionInfo]:
    """Discover versions, resolve the active one, create storage."""
    platform_path = Path(config.platform.path)

    discovery = VersionDiscovery()
    discovered = discovery.discover(platform_path)

    if not discovered:
        raise PlatformContextLoadException(
            f"No HBK files found in '{platform_path}'"
        )

    # Separate versioned and unversioned discoveries
    versioned = [d for d in discovered if d.version is not None]

    if config.platform.version:
        # User requested a specific version — find closest match
        target = PlatformVersion.parse(config.platform.version)
        if target is None:
            raise PlatformContextLoadException(
                f"Invalid version format: '{config.platform.version}'. Expected: 8.X.X"
            )
        if versioned:
            closest = find_closest_version(target, [d.version for d in versioned])
            resolved = next(d for d in versioned if d.version == closest)
            logger.info("Requested version %s, resolved to %s", target, closest)
        else:
            resolved = discovered[0]
            logger.warning(
                "Version %s requested but no version info available, using single HBK",
                target,
            )
    else:
        # Default: pick maximum version
        if versioned:
            resolved = max(versioned, key=lambda d: d.version)
            logger.info("Auto-selected latest version: %s", resolved.version)
        else:
            resolved = discovered[0]

    storage = PlatformContextStorage(loader, resolved.platform_dir)
    version_info_result = PlatformVersionInfo(
        active_version=resolved.version,
        active_hbk_path=resolved.hbk_path,
        available_versions=[d.version for d in versioned],
    )

    return storage, version_info_result


def _create_json_storage(json_path: str) -> PlatformContextStorage:
    """Create a storage pre-loaded from JSON files."""
    from mcp_bsl_context.infrastructure.json_loader.json_context_loader import JsonContextLoader

    json_loader = JsonContextLoader()
    methods, properties, types = json_loader.load_all(Path(json_path))

    return PlatformContextStorage.from_loaded_data(methods, properties, types)


def _load_docs_content(custom_path: str | None, default_filename: str) -> str:
    """Load documentation content from custom path or bundled default."""
    if custom_path:
        path = Path(custom_path)
        if not path.is_file():
            raise DocsLoadException(f"Файл документации не найден: {custom_path}")
        return path.read_text(encoding="utf-8")

    ref = pkg_resources.files("mcp_bsl_context.docinfo").joinpath(default_filename)
    return ref.read_text(encoding="utf-8")


def _create_docs_service(config: AppConfig) -> DocsInfoService:
    """Create DocsInfoService with content from config paths or bundled defaults."""
    strict_types_content = _load_docs_content(
        config.docs.strict_types_path, "strict-types.md"
    )
    guideline_content = _load_docs_content(
        config.docs.guideline_path, "guideline.md"
    )
    return DocsInfoService(strict_types_content, guideline_content)
