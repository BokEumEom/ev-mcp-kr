from __future__ import annotations

import pytest
import respx

from ev_mcp.context import ToolContext
from ev_mcp.models import ChargerInfo
from ev_mcp.tools.operator import list_chargers_by_operator

from .fixtures.sample_responses import GET_CHARGER_INFO_OK, make_info_page


def _seed(ctx: ToolContext) -> None:
    rows = [
        ChargerInfo.model_validate(it)
        for it in GET_CHARGER_INFO_OK["response"]["body"]["items"]["item"]
    ]
    ctx.caches.station_info.seed_for_testing(rows)


@pytest.mark.asyncio
async def test_list_by_operator_korean_name(ctx: ToolContext) -> None:
    _seed(ctx)
    async with respx.mock(base_url=ctx.settings.api_base_url, assert_all_called=False):
        results = await list_chargers_by_operator(operator="기후에너지환경부", ctx=ctx)
    assert all(r.busi_id == "ME" for r in results)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_list_by_operator_with_region(ctx: ToolContext) -> None:
    _seed(ctx)
    async with respx.mock(base_url=ctx.settings.api_base_url, assert_all_called=False):
        results = await list_chargers_by_operator(
            operator="에버온", region="서울특별시", ctx=ctx
        )
    assert all(r.busi_id == "EV" and r.sido_code == "11" for r in results)


@pytest.mark.asyncio
async def test_list_by_operator_falls_back_to_api(ctx: ToolContext) -> None:
    payload = make_info_page(total_count=1, page_no=1, num_of_rows=200)
    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        route = router.get("/getChargerInfo").respond(json=payload)
        results = await list_chargers_by_operator(operator="에버온", ctx=ctx)
    assert route.call_count == 1
    assert all(r.busi_id == "EV" for r in results)


@pytest.mark.asyncio
async def test_list_by_operator_invalid(ctx: ToolContext) -> None:
    with pytest.raises(ValueError, match="operator"):
        await list_chargers_by_operator(operator="", ctx=ctx)
    with pytest.raises(ValueError, match="unknown operator"):
        await list_chargers_by_operator(operator="존재하지않는회사", ctx=ctx)
