"""Tests for asynchronous semantic warmup (opencode timeout fix).

Verifies that ``_LazySemanticState`` can warm up in the background so the
first semantic/hybrid call does not block on model loading (and thus does
not exceed MCP client timeouts), and that a request arriving before the
models are ready degrades gracefully instead of hanging forever.
"""

from __future__ import annotations

import time

import pytest

from mcp_bsl_context import server
from mcp_bsl_context.config import AppConfig
from mcp_bsl_context.server import _LazySemanticState


class _FakeEngine:
    """Minimal stand-in for SemanticSearchEngine/HybridSearchEngine."""

    def __init__(self, result=None):
        self.result = result if result is not None else []

    def search(self, *args, **kwargs):
        return self.result


def _make_state(init_seconds: float, transient_first: bool = False):
    """Build a state whose ``_do_init`` is stubbed (no real models loaded).

    Returns:
        tuple[state, attempts_counter]
    """
    state = _LazySemanticState(AppConfig(), storage=None, keyword_engine=None)
    attempts = {"n": 0}

    def do_init():  # stub signature matches the real no-arg _do_init(self)
        attempts["n"] += 1
        if transient_first and attempts["n"] == 1:
            raise RuntimeError("transient network failure")
        time.sleep(init_seconds)
        state._semantic_engine = _FakeEngine(result=["ok"])
        state._hybrid_engine = _FakeEngine(result=["ok"])

    state._do_init = do_init  # type: ignore[method-assign]
    return state, attempts


def test_start_background_warmup_is_non_blocking_and_ready():
    state, _ = _make_state(init_seconds=0.3)

    started = time.monotonic()
    state.start_background_warmup()
    elapsed = time.monotonic() - started

    assert elapsed < 0.1, "start_background_warmup must not block the caller"
    assert "initializing" in state.status

    assert state._ready.wait(5.0), "background warmup should finish quickly"
    assert state.status == "ready"


def test_background_warmup_idempotent():
    state, _ = _make_state(init_seconds=0.2)
    state.start_background_warmup()
    state.start_background_warmup()
    assert state._ready.wait(5.0)
    assert state.status == "ready"


def test_bounded_wait_raises_when_init_slower_than_bound():
    state, _ = _make_state(init_seconds=2.0)
    state.start_background_warmup()

    with pytest.raises(RuntimeError, match="still initializing"):
        state._ensure_initialized_bounded(0.1)


def test_bounded_wait_waits_and_returns_when_ready():
    state, _ = _make_state(init_seconds=0.2)

    state._ensure_initialized_bounded(5.0)  # must not raise
    assert state.status == "ready"


def test_semantic_search_degrades_bounded_not_timeout(monkeypatch):
    monkeypatch.setattr(server, "SEMANTIC_READY_WAIT_TIMEOUT", 0.05)
    state, _ = _make_state(init_seconds=1.0)
    state.start_background_warmup()

    # Must raise quickly (bounded) instead of blocking on model loading.
    with pytest.raises(RuntimeError, match="still initializing"):
        state.semantic_search("как добавить строку")


def test_semantic_search_succeeds_when_warmup_ready():
    state, _ = _make_state(init_seconds=0.2)

    results = state.semantic_search("как добавить строку")
    assert results == ["ok"]


def test_transient_failure_is_retried():
    state, attempts = _make_state(init_seconds=0.05, transient_first=True)
    state.start_background_warmup()

    assert not state._ready.wait(0.3), "first attempt must fail"
    assert "not-initialized" in state.status  # retry flag was reset

    state._ensure_initialized_bounded(5.0)  # second attempt succeeds
    assert state.status == "ready"
    assert attempts["n"] == 2


def test_sync_initialize_still_blocking_for_reindex():
    state, _ = _make_state(init_seconds=0.2)
    started = time.monotonic()
    state.initialize()
    elapsed = time.monotonic() - started

    assert elapsed >= 0.2, "synchronous initialize must block until done"
    assert state.status == "ready"