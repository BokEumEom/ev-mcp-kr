from __future__ import annotations

import pytest
import respx

from ev_mcp.client import EvChargerError
from ev_mcp.context import ToolContext
from ev_mcp.models import ChargerInfo
from ev_mcp.tools.station import get_station_details

from .fixtures.sample_responses import GET_CHARGER_INFO_OK, make_info_page


@pytest.mark.asyncio
async def test_get_station_details_uses_cache_when_fresh(ctx: ToolContext) -> None:
    rows = [
        ChargerInfo.model_validate(it)
        for it in GET_CHARGER_INFO_OK["response"]["body"]["items"]["item"]
    ]
    ctx.caches.station_info.seed_for_testing(rows)

    async with respx.mock(
        base_url=ctx.settings.api_base_url, assert_all_called=False
    ) as router:
        route = router.get("/getChargerInfo")
        details = await get_station_details(stat_id="28260005", ctx=ctx)
    assert route.call_count == 0
    assert details.stat_id == "28260005"
    assert details.stat_nm == "기후대기관"
    assert details.sido_label == "인천광역시"
    assert details.operator_label == "기후에너지환경부"


@pytest.mark.asyncio
async def test_get_station_details_falls_back_to_api(ctx: ToolContext) -> None:
    payload = make_info_page(total_count=1, page_no=1, num_of_rows=50)
    payload["response"]["body"]["items"]["item"][0]["statId"] = "11680001"

    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        route = router.get("/getChargerInfo").respond(json=payload)
        details = await get_station_details(stat_id="11680001", ctx=ctx)
    assert route.call_count == 1
    assert details.stat_id == "11680001"
    assert details.sido_label == "서울특별시"


@pytest.mark.asyncio
async def test_get_station_details_not_found(ctx: ToolContext) -> None:
    empty = make_info_page(total_count=0, page_no=1, num_of_rows=50)
    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        router.get("/getChargerInfo").respond(json=empty)
        with pytest.raises(EvChargerError, match="찾을 수 없습니다"):
            await get_station_details(stat_id="99999999", ctx=ctx)


@pytest.mark.asyncio
async def test_get_station_details_invalid_input(ctx: ToolContext) -> None:
    with pytest.raises(ValueError):
        await get_station_details(stat_id="", ctx=ctx)
    with pytest.raises(ValueError):
        await get_station_details(stat_id="123456789", ctx=ctx)
    with pytest.raises(ValueError, match="alphanumeric"):
        await get_station_details(stat_id="../foo", ctx=ctx)
