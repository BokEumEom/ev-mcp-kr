from __future__ import annotations

import pytest
import respx

from ev_mcp.context import ToolContext
from ev_mcp.models import ChargerInfo
from ev_mcp.tools.region import search_chargers_by_region

from .fixtures.sample_responses import GET_CHARGER_INFO_OK, make_info_page


def _seed(ctx: ToolContext) -> None:
    rows = [
        ChargerInfo.model_validate(it)
        for it in GET_CHARGER_INFO_OK["response"]["body"]["items"]["item"]
    ]
    ctx.caches.station_info.seed_for_testing(rows)


@pytest.mark.asyncio
async def test_search_by_region_uses_cache_indexes(ctx: ToolContext) -> None:
    _seed(ctx)
    async with respx.mock(
        base_url=ctx.settings.api_base_url, assert_all_called=False
    ) as router:
        route = router.get("/getChargerInfo")
        results = await search_chargers_by_region(
            sido="서울특별시", sigungu="강남구", ctx=ctx
        )
    assert route.call_count == 0
    assert len(results) == 1
    assert results[0].sigungu_label == "강남구"


@pytest.mark.asyncio
async def test_search_by_region_resolves_short_sido(ctx: ToolContext) -> None:
    _seed(ctx)
    async with respx.mock(base_url=ctx.settings.api_base_url, assert_all_called=False):
        results = await search_chargers_by_region(sido="서울", ctx=ctx)
    assert all(r.sido_code == "11" for r in results)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_search_by_region_filters(ctx: ToolContext) -> None:
    _seed(ctx)
    async with respx.mock(base_url=ctx.settings.api_base_url, assert_all_called=False):
        results = await search_chargers_by_region(
            sido="서울특별시",
            charger_type=["04"],
            available_only=False,
            ctx=ctx,
        )
    assert all(r.chger_type_code == "04" for r in results)


@pytest.mark.asyncio
async def test_search_by_region_falls_back_to_api(ctx: ToolContext) -> None:
    payload = make_info_page(total_count=1, page_no=1, num_of_rows=200)
    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        route = router.get("/getChargerInfo").respond(json=payload)
        results = await search_chargers_by_region(sido="서울특별시", ctx=ctx)
    assert route.call_count == 1
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_by_region_invalid_input(ctx: ToolContext) -> None:
    with pytest.raises(ValueError, match="sido"):
        await search_chargers_by_region(sido="", ctx=ctx)
    with pytest.raises(ValueError, match="unknown sido"):
        await search_chargers_by_region(sido="평양시", ctx=ctx)
    with pytest.raises(ValueError, match="limit"):
        await search_chargers_by_region(sido="서울특별시", limit=0, ctx=ctx)
