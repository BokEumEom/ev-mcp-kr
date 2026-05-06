"""In-memory short-lived cache for live charger status.

Phase 6 moved the bulk charger inventory to SQLite (see :mod:`ev_mcp.store`).
What remains here is the per-request status cache: ``getChargerStatus`` is a
live endpoint and a 60-second cache around it cuts redundant calls without
serving stale data.

Thread-safety: ``asyncio.Lock`` per cache key so a thundering herd of MCP
requests for the same charger only triggers ONE upstream call.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog

from .models import ChargerStatusRow
from .settings import Settings

logger = structlog.get_logger(__name__)


@dataclass
class _Entry[T]:
    value: T
    fetched_at: float


@dataclass
class StatusCache:
    """Short-lived cache for getChargerStatus responses."""

    ttl_s: int
    _store: dict[tuple[object, ...], _Entry[list[ChargerStatusRow]]] = field(default_factory=dict)
    _locks: dict[tuple[object, ...], asyncio.Lock] = field(default_factory=dict)

    def _is_fresh(self, entry: _Entry[list[ChargerStatusRow]], now: float) -> bool:
        return (now - entry.fetched_at) < self.ttl_s

    def _lock_for(self, key: tuple[object, ...]) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def get_or_fetch(
        self,
        key: tuple[object, ...],
        fetch: Callable[[], Awaitable[list[ChargerStatusRow]]],
    ) -> list[ChargerStatusRow]:
        now = time.monotonic()
        cached = self._store.get(key)
        if cached and self._is_fresh(cached, now):
            return cached.value
        async with self._lock_for(key):
            cached = self._store.get(key)
            now = time.monotonic()
            if cached and self._is_fresh(cached, now):
                return cached.value
            value = await fetch()
            self._store[key] = _Entry(value=value, fetched_at=now)
            self._gc(now)
            return value

    def _gc(self, now: float) -> None:
        """Drop entries older than 10x TTL and their locks. Bounded growth."""
        cutoff = self.ttl_s * 10
        stale = [k for k, e in self._store.items() if (now - e.fetched_at) > cutoff]
        for k in stale:
            self._store.pop(k, None)
            self._locks.pop(k, None)

    def invalidate(self) -> None:
        self._store.clear()
        self._locks.clear()


@dataclass
class Caches:
    """Wrapper that the FastMCP server holds and tools share."""

    status: StatusCache


def build_caches(settings: Settings) -> Caches:
    return Caches(status=StatusCache(ttl_s=settings.status_ttl))
