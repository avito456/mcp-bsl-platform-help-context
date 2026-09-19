"""Search indexes for fast lookup."""

from __future__ import annotations

from bisect import bisect_left
from typing import Callable, Generic, TypeVar

T = TypeVar("T")

_KeyFn = Callable[[T], str | list[str]]


def _norm(value: str) -> str:
    return value.lower()


def _iter_keys(key_fn_result: str | list[str]) -> list[str]:
    """Normalize a key function result into a list of lowercased keys."""
    keys = key_fn_result if isinstance(key_fn_result, list) else [key_fn_result]
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = _norm(key)
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


class HashIndex(Generic[T]):
    """Case-insensitive exact lookup using a dict with multiple keys per item."""

    def __init__(self) -> None:
        self._data: dict[str, list[T]] = {}

    def load(self, items: list[T], key_fn: _KeyFn) -> None:
        self._data = {}
        for item in items:
            for key in _iter_keys(key_fn(item)):
                self._data.setdefault(key, []).append(item)

    def get(self, key: str) -> list[T]:
        return self._data.get(_norm(key), [])

    @property
    def size(self) -> int:
        return len(self._data)

    def is_empty(self) -> bool:
        return len(self._data) == 0


class StartWithIndex(Generic[T]):
    """Prefix-based search using a sorted list + bisect.

    Each item is registered under every key it exposes, so a single
    prefix query matches items through any of their aliases.
    """

    def __init__(self) -> None:
        self._keys: list[str] = []
        self._values: list[T] = []

    def load(self, items: list[T], key_fn: _KeyFn) -> None:
        pairs: list[tuple[str, T]] = []
        for item in items:
            for key in _iter_keys(key_fn(item)):
                pairs.append((key, item))
        pairs.sort(key=lambda x: x[0])
        self._keys = [p[0] for p in pairs]
        self._values = [p[1] for p in pairs]

    def get(self, prefix: str) -> list[T]:
        prefix = prefix.lower()
        left = bisect_left(self._keys, prefix)
        results: list[T] = []
        seen: set[int] = set()
        for i in range(left, len(self._keys)):
            if self._keys[i].startswith(prefix):
                item = self._values[i]
                if id(item) not in seen:
                    seen.add(id(item))
                    results.append(item)
            else:
                break
        return results

    @property
    def size(self) -> int:
        return len(self._keys)

    def is_empty(self) -> bool:
        return len(self._keys) == 0


class Indexes:
    """Composite index manager holding property/method/type indexes."""

    def __init__(
        self,
        properties: HashIndex | StartWithIndex,
        methods: HashIndex | StartWithIndex,
        types: HashIndex | StartWithIndex,
    ) -> None:
        self.properties = properties
        self.methods = methods
        self.types = types