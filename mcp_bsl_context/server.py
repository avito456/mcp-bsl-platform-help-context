"""FastMCP server with platform context tools."""

from __future__ import annotations

import importlib.resources as pkg_resources
import functools
import logging
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

SERVER_INSTRUCTIONS = (
    "Этот MCP-сервер предоставляет доступ к документации API платформы "
    "1С:Предприятие. Инструкции по использованию инструментов:\n"
    "1. Начинайте с инструмента search для нахождения нужных элементов API. "
    "Используйте конкретные термины 1С (русские или английские), например "
    "'НайтиПоСсылке', 'ТаблицаЗначений.Добавить'.\n"
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
    "9. Если поиск не дал результатов, попробуйте другой режим или более "
    "общий термин; не выдумывайте имена API, которых нет в ответах."
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

    def initialize(self) -> None:
        """Eagerly load models and ensure the index is ready.

        Used at startup when a forced reindex is requested (``--reindex``),
        so the semantic index is (re)built before the first client request.
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
        self._ensure_initialized()
        return self._semantic_engine.search(
            query, self._storage, limit=limit, type_filter=type_filter
        )

    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[Definition]:
        self._ensure_initialized()
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
        например: 'НайтиПоСсылке', 'FindByRef', 'ТаблицаЗначений.Добавить'.
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

        if effective_mode == "keyword":
            results = service.search_all(query, type_filter, effective_limit)
        elif effective_mode == "semantic":
            results = semantic_state.semantic_search(
                query, limit=effective_limit, type_filter=type_filter
            )
        else:  # hybrid
            results = semantic_state.hybrid_search(
                query, limit=effective_limit, type_filter=type_filter
            )
        return (
            formatter.format_query(query)
            + formatter.format_search_results(
                results, member_owner=storage.member_owner
            )
        )

    @mcp.tool()
    @_safe_call(_format_lookup_error)
    def info(name: str, type_filter: str) -> str:
        """Получить детальную информацию о конкретном элементе API платформы 1С.

        Возвращает полное описание, сигнатуры, параметры, возвращаемое значение.
        Используйте точное имя элемента (полученное через search).

        Args:
            name: Точное имя элемента (например, 'НайтиПоСсылке', 'FindByRef', 'ТаблицаЗначений')
            type_filter: Тип элемента: 'method' (метод), 'property' (свойство) или 'type' (тип)
        """
        definition = service.get_info(name, type_filter)
        return formatter.format_member(definition)

    @mcp.tool()
    @_safe_call(_format_lookup_error)
    def get_member(type_name: str, member_name: str) -> str:
        """Получить информацию о методе или свойстве конкретного типа платформы 1С.

        Args:
            type_name: Имя типа (например, 'СправочникСсылка', 'CatalogRef', 'ТаблицаЗначений'). Для шаблонных типов — полное имя, например 'СправочникОбъект.<Имя справочника>'
            member_name: Имя метода или свойства внутри типа (например, 'Добавить', 'Количество')
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
        """
        constructors = service.find_constructors(type_name)
        return formatter.format_constructors(constructors, type_name)

    @mcp.tool()
    @_safe_call(lambda e: formatter.format_error(e))
    def get_platform_info() -> str:
        """Получить информацию о текущей версии платформы 1С и доступных версиях.

        Возвращает активную версию, путь к HBK-файлу и список всех
        обнаруженных версий платформы.
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

    # --- Documentation tools (strict typing, coding guidelines) ---

    docs_service = _create_docs_service(config)

    @mcp.tool()
    @_safe_call(lambda e: formatter.format_error(e))
    def get_coding_guideline() -> str:
        """Получить рекомендации по стилю кода BSL (1С:Предприятие).

        Возвращает полный набор рекомендаций по написанию качественного кода 1С.
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
