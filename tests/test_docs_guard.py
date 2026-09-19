"""Guard: API-looking names used in docs must be real elements.

An AI assistant copies example names straight out of tool descriptions and
README into info/get_member calls, so any made-up name in the docs becomes a
failure. This test scans the docstrings/texts and fails on unknown names.

Non-API tokens (internal class names, framing terms) live in ALLOWLIST.
Skipped when the real HBK data is not present.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC_FILES = [
    ROOT / "mcp_bsl_context" / "server.py",
    ROOT / "README.md",
    ROOT / "CLAUDE.md",
]
HBK = ROOT / "8.3.27.72" / "shcntx_ru.hbk"

pytestmark = pytest.mark.skipif(
    not HBK.exists(), reason="real HBK data not present"
)

# Known made-up API examples that have previously leaked into the docs.
FORBIDDEN_EXAMPLES = ["НайтиПоСсылке"]

# Architecture/class names and framing terms that legitimately appear in
# README/CLAUDE/docstrings but are not 1C API elements.
ALLOWLIST = {
    "ApiType",
    "AppConfig",
    "BeautifulSoup",
    "CamelCase",
    "CatalogRef",
    "CompoundTypeSearch",
    "ContextSearchService",
    "DiTy",
    "DocsInfoService",
    "DocsLoadException",
    "DocumentBuilder",
    "DomainException",
    "EmbeddingProvider",
    "FileStorage",
    "HashIndex",
    "HuggingFace",
    "HybridSearchEngine",
    "ImportError",
    "JsonContextLoader",
    "LazySemanticState",
    "MarkdownFormatter",
    "MethodDefinition",
    "PackBlock",
    "ParameterDefinition",
    "PascalCase",
    "PlatformContextLoadException",
    "PlatformContextLoader",
    "PlatformContextStorage",
    "PlatformRepository",
    "PlatformTypeDefinition",
    "PlatformTypeNotFoundException",
    "PlatformVersion",
    "PlatformVersionInfo",
    "PropertyDefinition",
    "RegularSearch",
    "RuntimeError",
    "SafeSkill",
    "SearchOptions",
    "SearchQuery",
    "SemanticSearchEngine",
    "SimpleSearchEngine",
    "StartWithIndex",
    "TypeMemberNotFoundException",
    "TypeMemberSearch",
    "ValueError",
    "VersionDiscovery",
    "WordOrderSearch",
    "СправочникОбъект",
    "СправочникСсылка",
}

TOKEN_RE = re.compile(r"[А-ЯЁA-Z][а-яёa-z]+(?:[А-ЯЁA-Z][а-яёa-z]+)+")


def _real_names() -> set[str]:
    logging.disable(logging.CRITICAL)
    from mcp_bsl_context.infrastructure.storage.loader import PlatformContextLoader
    from mcp_bsl_context.infrastructure.storage.storage import PlatformContextStorage

    s = PlatformContextStorage(PlatformContextLoader(), HBK.parent)
    s.ensure_loaded()
    names: set[str] = set()
    for d in [*s.methods, *s.properties, *s.types]:
        names.add(d.name.lower())
        if d.name_en:
            names.add(d.name_en.lower())
    return names


@pytest.fixture(scope="module")
def real_names() -> set[str]:
    return _real_names()


@pytest.mark.parametrize("path", DOC_FILES)
def test_no_forbidden_examples(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for banned in FORBIDDEN_EXAMPLES:
        assert banned not in text, f"{banned!r} found in {path}"


@pytest.mark.parametrize("path", DOC_FILES)
def test_docs_only_mention_real_api_names(path: Path, real_names: set[str]) -> None:
    text = path.read_text(encoding="utf-8")
    unknown: set[str] = set()
    for m in TOKEN_RE.finditer(text):
        token = m.group(0)
        if token not in ALLOWLIST and token.lower() not in real_names:
            unknown.add(token)
    assert not unknown, f"non-API names in {path}: {sorted(unknown)}"