from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from ev_mcp.cache import StationInfoCache, StatusCache, build_caches
from ev_mcp.client import EvChargerClient
from ev_mcp.settings import Settings

from .fixtures.sample_responses import GET_CHARGER_STATUS_OK, make_info_page


@pytest.mark.asyncio
async def test_station_info_cache_refresh_indexes(settings: Settings) -> None:
    page1 = make_info_page(total_count=15, page_no=1, num_of_rows=10)
    page2 = make_info_page(total_count=15, page_no=2, num_of_rows=10)
    pages = {1: page1, 2: page2}

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[int(request.url.params["pageNo"])])

    cache = StationInfoCache(ttl_s=settings.station_info_ttl, refresh_page_size=10)
    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").mock(side_effect=respond)
        async with EvChargerClient(settings) as client:
            await cache.ensure_fresh(client)
    assert len(cache.all_rows) == 15
    assert "00000001" in cache.by_stat_id
    assert "11" in cache.by_zcode
    assert "11680" in cache.by_zscode
    assert "EV" in cache.by_busi_id


@pytest.mark.asyncio
async def test_station_info_cache_uses_existing_when_fresh(settings: Settings) -> None:
    """Second ensure_fresh on a fresh cache must NOT trigger an upstream call."""
    cache = StationInfoCache(ttl_s=settings.station_info_ttl)
    async with respx.mock(base_url=settings.api_base_url) as router:
        route = router.get("/getChargerInfo").respond(
            json=make_info_page(total_count=3, page_no=1, num_of_rows=10)
        )
        async with EvChargerClient(settings) as client:
            await cache.ensure_fresh(client)
            await cache.ensure_fresh(client)  # should be a no-op
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_station_info_cache_concurrent_refresh_dedupes(settings: Settings) -> None:
    """Stampede of concurrent ensure_fresh on a cold cache → exactly one upstream call."""
    cache = StationInfoCache(ttl_s=settings.station_info_ttl)
    async with respx.mock(base_url=settings.api_base_url) as router:
        route = router.get("/getChargerInfo").respond(
            json=make_info_page(total_count=2, page_no=1, num_of_rows=10)
        )
        async with EvChargerClient(settings) as client:
            await asyncio.gather(*(cache.ensure_fresh(client) for _ in range(10)))
    assert route.call_count == 1
    assert len(cache.all_rows) == 2


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
    assert caches.station_info.ttl_s == settings.station_info_ttl
    assert caches.status.ttl_s == settings.status_ttl


# --- review-driven regressions -------------------------------------------------


@pytest.mark.asyncio
async def test_station_info_refresh_failure_keeps_previous_index(
    settings: Settings,
) -> None:
    """If a refresh raises mid-iteration, the previous index must survive."""
    cache = StationInfoCache(ttl_s=1, refresh_page_size=10)

    # Seed with a known good state.
    seed_payload = make_info_page(total_count=2, page_no=1, num_of_rows=10)
    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").respond(json=seed_payload)
        async with EvChargerClient(settings) as client:
            await cache.refresh(client)
    assert len(cache.all_rows) == 2
    saved_first_id = cache.all_rows[0].stat_id

    # Force expiry.
    cache.fetched_at = 0.0

    # Next refresh blows up on the second page (after one page of rows accumulated).
    page1 = make_info_page(total_count=20, page_no=1, num_of_rows=10)

    def respond(request: httpx.Request) -> httpx.Response:
        if int(request.url.params["pageNo"]) == 1:
            return httpx.Response(200, json=page1)
        return httpx.Response(503, text="boom")

    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").mock(side_effect=respond)
        async with EvChargerClient(settings) as client:
            with pytest.raises(Exception):  # noqa: B017
                await cache.refresh(client)

    # Original index is still intact — partial state was NOT applied.
    assert len(cache.all_rows) == 2
    assert cache.all_rows[0].stat_id == saved_first_id


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
