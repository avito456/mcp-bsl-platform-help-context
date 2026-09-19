"""Application configuration with YAML + env vars + CLI override support."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from mcp_bsl_context.domain.exceptions import DomainException

logger = logging.getLogger(__name__)

VALID_SEARCH_MODES = {"keyword", "semantic", "hybrid"}
VALID_DATA_SOURCES = {"hbk", "json"}
VALID_PROVIDERS = {"local", "openai-compatible"}


class ConfigValidationError(DomainException):
    """Raised when the resolved configuration is invalid."""


@dataclass
class ServerConfig:
    mode: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8080
    verbose: bool = False


@dataclass
class PlatformConfig:
    path: str = ""
    version: str | None = None
    data_source: str = "hbk"
    json_path: str | None = None


@dataclass
class SearchConfig:
    default_mode: str = "hybrid"  # hybrid | semantic | keyword


@dataclass
class EmbeddingsConfig:
    provider: str = "local"  # local | openai-compatible
    model: str = "ai-forever/ru-en-RoSBERTa"
    api_url: str | None = None
    api_key: str | None = None


@dataclass
class RerankerConfig:
    enabled: bool = True
    provider: str = "local"  # local | openai-compatible
    model: str = "DiTy/cross-encoder-russian-msmarco"
    api_url: str | None = None
    api_key: str | None = None


@dataclass
class StorageConfig:
    qdrant_path: str = "./data/qdrant"
    models_cache: str = "./data/models"


@dataclass
class IndexConfig:
    reindex: bool = False
    warmup: bool = False  # загрузить модели семантики при старте (не пересобирая индекс)


@dataclass
class DocsConfig:
    strict_types_path: str | None = None
    guideline_path: str | None = None


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    platform: PlatformConfig = field(default_factory=PlatformConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    reranker: RerankerConfig = field(default_factory=RerankerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    docs: DocsConfig = field(default_factory=DocsConfig)

    def validate(self) -> None:
        """Validate the resolved configuration, raising ConfigValidationError.

        Called by the CLI and create_server so misconfigurations fail fast
        with a readable message instead of a confusing runtime error.
        """
        errors: list[str] = []

        if self.search.default_mode not in VALID_SEARCH_MODES:
            errors.append(
                f"search.default_mode='{self.search.default_mode}' is invalid. "
                f"Expected one of: {', '.join(sorted(VALID_SEARCH_MODES))}"
            )
        if self.platform.data_source not in VALID_DATA_SOURCES:
            errors.append(
                f"platform.data_source='{self.platform.data_source}' is invalid. "
                f"Expected one of: {', '.join(sorted(VALID_DATA_SOURCES))}"
            )
        if self.embeddings.provider not in VALID_PROVIDERS:
            errors.append(
                f"embeddings.provider='{self.embeddings.provider}' is invalid. "
                f"Expected one of: {', '.join(sorted(VALID_PROVIDERS))}"
            )
        if self.reranker.provider not in VALID_PROVIDERS:
            errors.append(
                f"reranker.provider='{self.reranker.provider}' is invalid. "
                f"Expected one of: {', '.join(sorted(VALID_PROVIDERS))}"
            )
        if self.platform.data_source == "json" and not self.platform.json_path:
            errors.append(
                "platform.json_path is required when "
                "platform.data_source='json'"
            )
        if self.platform.data_source == "hbk" and not self.platform.path:
            errors.append(
                "platform.path is required when platform.data_source='hbk'"
            )

        if errors:
            raise ConfigValidationError(
                "Invalid configuration:\n- " + "\n- ".join(errors)
            )


# Mapping: env var name -> (section, field)
_ENV_MAPPING: dict[str, tuple[str, str]] = {
    "MCP_BSL_PLATFORM_PATH": ("platform", "path"),
    "MCP_BSL_PLATFORM_VERSION": ("platform", "version"),
    "MCP_BSL_MODE": ("server", "mode"),
    "MCP_BSL_HOST": ("server", "host"),
    "MCP_BSL_PORT": ("server", "port"),
    "MCP_BSL_DATA_SOURCE": ("platform", "data_source"),
    "MCP_BSL_JSON_PATH": ("platform", "json_path"),
    "MCP_BSL_VERBOSE": ("server", "verbose"),
    "MCP_BSL_SEARCH_DEFAULT_MODE": ("search", "default_mode"),
    "MCP_BSL_EMBEDDINGS_PROVIDER": ("embeddings", "provider"),
    "MCP_BSL_EMBEDDINGS_MODEL": ("embeddings", "model"),
    "MCP_BSL_EMBEDDINGS_API_URL": ("embeddings", "api_url"),
    "MCP_BSL_EMBEDDINGS_API_KEY": ("embeddings", "api_key"),
    "MCP_BSL_RERANKER_ENABLED": ("reranker", "enabled"),
    "MCP_BSL_RERANKER_PROVIDER": ("reranker", "provider"),
    "MCP_BSL_RERANKER_MODEL": ("reranker", "model"),
    "MCP_BSL_RERANKER_API_URL": ("reranker", "api_url"),
    "MCP_BSL_RERANKER_API_KEY": ("reranker", "api_key"),
    "MCP_BSL_STORAGE_QDRANT_PATH": ("storage", "qdrant_path"),
    "MCP_BSL_STORAGE_MODELS_CACHE": ("storage", "models_cache"),
    "MCP_BSL_INDEX_REINDEX": ("index", "reindex"),
    "MCP_BSL_INDEX_WARMUP": ("index", "warmup"),
    "MCP_BSL_DOCS_STRICT_TYPES_PATH": ("docs", "strict_types_path"),
    "MCP_BSL_DOCS_GUIDELINE_PATH": ("docs", "guideline_path"),
}


def load_config(
    config_path: str | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> AppConfig:
    """Load configuration with priority: YAML < env vars < CLI overrides.

    Args:
        config_path: Path to YAML config file. None to skip.
        cli_overrides: Dict of CLI overrides in format {"section.field": value}.
            None values are skipped (means CLI option was not provided).
    """
    config = AppConfig()

    # 1. Load from YAML
    if config_path:
        _apply_yaml(config, config_path)

    # 2. Apply env vars
    _apply_env_vars(config)

    # 3. Apply CLI overrides
    if cli_overrides:
        _apply_overrides(config, cli_overrides)

    return config


def _apply_yaml(config: AppConfig, config_path: str) -> None:
    """Load YAML file and apply values to config."""
    path = Path(config_path)
    if not path.is_file():
        logger.warning("Config file not found: %s, using defaults", config_path)
        return

    try:
        import yaml
    except ImportError:
        logger.error("pyyaml not installed. Install with: pip install pyyaml")
        return

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        logger.warning("Config file is not a valid YAML mapping: %s", config_path)
        return

    for section_name, section_data in data.items():
        if not isinstance(section_data, dict):
            continue
        section = getattr(config, section_name, None)
        if section is None:
            logger.warning("Unknown config section: %s", section_name)
            continue
        _set_section_fields(section, section_data)

    logger.info("Loaded config from %s", config_path)


def _apply_env_vars(config: AppConfig) -> None:
    """Apply environment variables to config."""
    for env_name, (section_name, field_name) in _ENV_MAPPING.items():
        value = os.environ.get(env_name)
        if value is None:
            continue
        section = getattr(config, section_name, None)
        if section is None:
            continue
        _set_field_value(section, field_name, value)


def _apply_overrides(config: AppConfig, overrides: dict[str, Any]) -> None:
    """Apply CLI overrides in format {'section.field': value}."""
    for key, value in overrides.items():
        if value is None:
            continue
        parts = key.split(".", 1)
        if len(parts) != 2:
            continue
        section_name, field_name = parts
        section = getattr(config, section_name, None)
        if section is None:
            continue
        _set_field_value(section, field_name, value)


def _set_section_fields(section: Any, data: dict[str, Any]) -> None:
    """Set fields on a section dataclass from a dict."""
    section_fields = {f.name: f for f in fields(section)}
    for key, value in data.items():
        if key not in section_fields:
            logger.warning(
                "Unknown config key '%s' in section %s — ignored",
                key,
                type(section).__name__,
            )
            continue
        if value is not None:
            _set_field_value(section, key, value)


def _set_field_value(obj: Any, field_name: str, value: Any) -> None:
    """Set a field on a dataclass, coercing the value to the correct type."""
    field_info = {f.name: f for f in fields(obj)}.get(field_name)
    if field_info is None:
        return

    coerced = _coerce_value(value, field_info.type)
    if coerced is not None:
        object.__setattr__(obj, field_name, coerced)


def _coerce_value(value: Any, type_hint: str | type | None) -> Any:
    """Coerce a value to match the target type hint.

    Invalid values for int/bool fields (e.g. a typo in an env var) are
    logged and converted to ``None`` so the caller keeps the default
    instead of crashing the whole server on startup.
    """
    if value is None:
        return None

    type_str = str(type_hint) if type_hint else ""
    nullable = "None" in type_str

    if "bool" in type_str:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.lower()
            if normalized in ("true", "1", "yes"):
                return True
            if normalized not in ("false", "0", "no", ""):
                logger.warning(
                    "Invalid boolean value %r — using False", value
                )
            return False
        return bool(value)

    if "int" in type_str:
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid integer value %r — keeping default",
                value,
            )
            return None

    return value
