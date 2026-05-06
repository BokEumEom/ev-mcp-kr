"""Tests for the in-memory StatusCache (60s TTL for getChargerStatus).

The bulk inventory cache moved to SQLite (``ev_mcp.store``) in Phase 6 — see
``tests/test_store.py`` for those.
"""

from __future__ import annotations

import asyncio

import pytest
import respx

from ev_mcp.cache import StatusCache, build_caches
from ev_mcp.client import EvChargerClient
from ev_mcp.settings import Settings

from .fixtures.sample_responses import GET_CHARGER_STATUS_OK


@pytest.mark.asyncio
async def test_status_cache_get_or_fetch(settings: Settings) -> None:
    cache = StatusCache(ttl_s=settings.status_ttl)
    calls = 0

    async def fetch() -> list:
        nonlocal calls
        calls += 1
        async with respx.mock(base_url=settings.api_base_url) as router:
            router.get("/getChargerStatus").respond(json=GET_CHARGER_STATUS_OK)
            async with EvChargerClient(settings) as client:
                _, items = await client.get_charger_status()
        return items

    key = ("status", "11", None)
    a = await cache.get_or_fetch(key, fetch)
    b = await cache.get_or_fetch(key, fetch)
    assert calls == 1
    assert a is b


@pytest.mark.asyncio
async def test_status_cache_separate_keys(settings: Settings) -> None:
    cache = StatusCache(ttl_s=settings.status_ttl)
    calls: list[str] = []

    async def make_fetch(label: str):
        async def _f() -> list:
            calls.append(label)
            return []

        return _f

    fa = await make_fetch("A")
    fb = await make_fetch("B")
    await cache.get_or_fetch(("a",), fa)
    await cache.get_or_fetch(("b",), fb)
    await cache.get_or_fetch(("a",), fa)
    assert calls == ["A", "B"]


@pytest.mark.asyncio
async def test_status_cache_invalidate(settings: Settings) -> None:
    cache = StatusCache(ttl_s=settings.status_ttl)
    calls = 0

    async def fetch() -> list:
        nonlocal calls
        calls += 1
        return []

    await cache.get_or_fetch(("k",), fetch)
    cache.invalidate()
    await cache.get_or_fetch(("k",), fetch)
    assert calls == 2


def test_build_caches_uses_settings_ttls(settings: Settings) -> None:
    caches = build_caches(settings)
    assert caches.status.ttl_s == settings.status_ttl


def test_status_cache_invalidate_clears_locks() -> None:
    cache = StatusCache(ttl_s=60)
    cache._locks[("k1",)] = asyncio.Lock()
    cache._locks[("k2",)] = asyncio.Lock()
    assert len(cache._locks) == 2
    cache.invalidate()
    assert len(cache._locks) == 0


@pytest.mark.asyncio
async def test_status_cache_gc_drops_very_stale_entries() -> None:
    cache = StatusCache(ttl_s=1)

    async def fetch() -> list:
        return []

    # Create 3 entries.
    for k in ("a", "b", "c"):
        await cache.get_or_fetch((k,), fetch)
    assert len(cache._store) == 3

    # Manually age them past 10x TTL.
    for entry in cache._store.values():
        entry.fetched_at -= cache.ttl_s * 11

    # Next fetch should trigger GC of all stale entries.
    await cache.get_or_fetch(("d",), fetch)
    # Only the just-fetched 'd' survives; stale a/b/c were swept.
    assert set(cache._store.keys()) == {("d",)}
    assert set(cache._locks.keys()).issubset({("d",)})
