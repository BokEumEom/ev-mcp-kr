from __future__ import annotations

import pytest

from ev_mcp.context import ToolContext
from ev_mcp.models import ChargerInfo
from ev_mcp.tools.region import search_chargers_by_region

from .fixtures.sample_responses import GET_CHARGER_INFO_OK


def _seed(ctx: ToolContext) -> None:
    rows = [
        ChargerInfo.model_validate(it)
        for it in GET_CHARGER_INFO_OK["response"]["body"]["items"]["item"]
    ]
    ctx.store.seed_for_testing(rows)


@pytest.mark.asyncio
async def test_search_by_region_uses_store_indexes(ctx: ToolContext) -> None:
    _seed(ctx)
    results = await search_chargers_by_region(
        sido="서울특별시", sigungu="강남구", ctx=ctx
    )
    assert len(results) == 1
    assert results[0].sigungu_label == "강남구"


@pytest.mark.asyncio
async def test_search_by_region_resolves_short_sido(ctx: ToolContext) -> None:
    _seed(ctx)
    results = await search_chargers_by_region(sido="서울", ctx=ctx)
    assert all(r.sido_code == "11" for r in results)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_search_by_region_filters(ctx: ToolContext) -> None:
    _seed(ctx)
    results = await search_chargers_by_region(
        sido="서울특별시",
        charger_type=["04"],
        available_only=False,
        ctx=ctx,
    )
    assert all(r.chger_type_code == "04" for r in results)


@pytest.mark.asyncio
async def test_search_by_region_returns_empty_when_no_data(ctx: ToolContext) -> None:
    """Phase 6: server is read-only over the store. Empty store → empty result."""
    results = await search_chargers_by_region(sido="서울특별시", ctx=ctx)
    assert results == []


@pytest.mark.asyncio
async def test_search_by_region_invalid_input(ctx: ToolContext) -> None:
    with pytest.raises(ValueError, match="sido"):
        await search_chargers_by_region(sido="", ctx=ctx)
    with pytest.raises(ValueError, match="unknown sido"):
        await search_chargers_by_region(sido="평양시", ctx=ctx)
    with pytest.raises(ValueError, match="limit"):
        await search_chargers_by_region(sido="서울특별시", limit=0, ctx=ctx)
