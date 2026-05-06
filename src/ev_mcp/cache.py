"""In-memory TTL cache for charger info and status.

Two layers:

- :class:`StationInfoCache` — full charger inventory bulk-fetched from
  ``getChargerInfo`` (about 12k-20k rows). Refreshed every ``station_info_ttl``
  seconds. Indexed for fast queries by region / operator / station id.
- :class:`StatusCache` — short-lived (60s) cache for live status responses,
  keyed by query parameters.

Thread-safety: ``asyncio.Lock`` per cache so a thundering herd of MCP requests
on a cold cache only triggers ONE upstream refresh.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog

from .client import EvChargerClient
from .models import ChargerInfo, ChargerStatusRow
from .settings import Settings

logger = structlog.get_logger(__name__)


@dataclass
class _Entry[T]:
    value: T
    fetched_at: float


# data.go.kr 의 게이트웨이가 numOfRows=9999 응답을 60s 넘게 돌리다 504 를 자주 던짐.
# 2000 으로 낮추면 페이지당 응답이 게이트웨이 한계 안. 총 페이지 수 ~250 (totalCount
# 506k 기준) → 워밍 ~100분으로 길어지지만 실패율은 크게 떨어짐. 부분 commit 정책
# (refresh 의 except 분기) 와 합쳐 점진적으로 인덱스 채움.
DEFAULT_REFRESH_PAGE_SIZE = 2000


@dataclass
class StationInfoCache:
    """Bulk inventory of every charger, indexed for query-time lookups."""

    ttl_s: int
    refresh_page_size: int = DEFAULT_REFRESH_PAGE_SIZE
    by_stat_id: dict[str, list[ChargerInfo]] = field(default_factory=dict)
    by_zcode: dict[str, list[ChargerInfo]] = field(default_factory=dict)
    by_zscode: dict[str, list[ChargerInfo]] = field(default_factory=dict)
    by_busi_id: dict[str, list[ChargerInfo]] = field(default_factory=dict)
    all_rows: list[ChargerInfo] = field(default_factory=list)
    fetched_at: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def is_fresh(self, now: float | None = None) -> bool:
        if not self.all_rows:
            return False
        now = now if now is not None else time.monotonic()
        return (now - self.fetched_at) < self.ttl_s

    def _rebuild_indexes(self, rows: list[ChargerInfo]) -> None:
        by_stat: dict[str, list[ChargerInfo]] = defaultdict(list)
        by_zcode: dict[str, list[ChargerInfo]] = defaultdict(list)
        by_zscode: dict[str, list[ChargerInfo]] = defaultdict(list)
        by_busi: dict[str, list[ChargerInfo]] = defaultdict(list)
        for r in rows:
            by_stat[r.stat_id].append(r)
            by_zcode[r.zcode].append(r)
            if r.zscode:
                by_zscode[r.zscode].append(r)
            by_busi[r.busi_id].append(r)
        self.all_rows = rows
        self.by_stat_id = dict(by_stat)
        self.by_zcode = dict(by_zcode)
        self.by_zscode = dict(by_zscode)
        self.by_busi_id = dict(by_busi)

    async def refresh(self, client: EvChargerClient) -> None:
        """Pull every page from upstream, rebuild indexes.

        On failure, partial rows collected so far are still committed if we
        have more than what's currently cached — covering most operators in
        a partial scan beats serving a 0-row index. Errors are re-raised so
        the caller knows the cache is incomplete (is_fresh stays True only
        if the new partial is bigger than the previous index, otherwise the
        previous index is preserved).
        """
        rows: list[ChargerInfo] = []
        try:
            async for r in client.iter_all_charger_info(page_size=self.refresh_page_size):
                rows.append(r)
        except Exception as e:
            previous = len(self.all_rows)
            if len(rows) > previous:
                self._rebuild_indexes(rows)
                self.fetched_at = time.monotonic()
                logger.warning(
                    "station_info refresh aborted at %d rows (was %d); committing partial: %s",
                    len(rows),
                    previous,
                    client.redact(e),
                )
            else:
                logger.warning(
                    "station_info refresh aborted; keeping previous index (%d rows): %s",
                    previous,
                    client.redact(e),
                )
            raise
        self._rebuild_indexes(rows)
        self.fetched_at = time.monotonic()
        logger.info("station_info cache refreshed: %d rows", len(rows))

    def seed_for_testing(self, rows: list[ChargerInfo]) -> None:
        """Test-only: populate the cache without an upstream call."""
        self._rebuild_indexes(rows)
        self.fetched_at = time.monotonic()

    async def ensure_fresh(self, client: EvChargerClient) -> None:
        if self.is_fresh():
            return
        async with self._lock:
            # Double-check after lock acquisition — another waiter may have refreshed.
            if self.is_fresh():
                return
            await self.refresh(client)


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

    station_info: StationInfoCache
    status: StatusCache


def build_caches(settings: Settings) -> Caches:
    return Caches(
        station_info=StationInfoCache(ttl_s=settings.station_info_ttl),
        status=StatusCache(ttl_s=settings.status_ttl),
    )
