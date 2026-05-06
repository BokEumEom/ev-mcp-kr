from __future__ import annotations

import pytest
import respx

from ev_mcp.client import EvChargerError
from ev_mcp.context import ToolContext
from ev_mcp.tools.status import get_charger_status, recent_status_changes

from .fixtures.sample_responses import GET_CHARGER_STATUS_OK


@pytest.mark.asyncio
async def test_get_charger_status_returns_status_change(ctx: ToolContext) -> None:
    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        router.get("/getChargerStatus").respond(json=GET_CHARGER_STATUS_OK)
        result = await get_charger_status(stat_id="28260005", chger_id="02", ctx=ctx)
    assert result.stat_id == "28260005"
    assert result.status_label == "충전대기"
    assert result.operator_label == "기후에너지환경부"


@pytest.mark.asyncio
async def test_get_charger_status_uses_cache(ctx: ToolContext) -> None:
    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        route = router.get("/getChargerStatus").respond(json=GET_CHARGER_STATUS_OK)
        await get_charger_status(stat_id="28260005", chger_id="02", ctx=ctx)
        await get_charger_status(stat_id="28260005", chger_id="02", ctx=ctx)
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_get_charger_status_not_found(ctx: ToolContext) -> None:
    empty = {
        "response": {
            "header": {
                "resultCode": "00",
                "resultMsg": "NORMAL SERVICE.",
                "totalCount": 0,
                "pageNo": 1,
                "numOfRows": 10,
            },
            "body": {"items": ""},
        }
    }
    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        router.get("/getChargerStatus").respond(json=empty)
        with pytest.raises(EvChargerError, match="찾을 수 없습니다"):
            await get_charger_status(stat_id="99999999", chger_id="01", ctx=ctx)


@pytest.mark.asyncio
async def test_get_charger_status_invalid_input(ctx: ToolContext) -> None:
    with pytest.raises(ValueError):
        await get_charger_status(stat_id="", chger_id="01", ctx=ctx)
    with pytest.raises(ValueError):
        await get_charger_status(stat_id="28260005", chger_id="3", ctx=ctx)
    with pytest.raises(ValueError, match="alphanumeric"):
        await get_charger_status(stat_id="../foo", chger_id="01", ctx=ctx)
    with pytest.raises(ValueError, match="alphanumeric"):
        await get_charger_status(stat_id="28260005", chger_id="!!", ctx=ctx)


@pytest.mark.asyncio
async def test_recent_status_changes_with_region(ctx: ToolContext) -> None:
    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        route = router.get("/getChargerStatus").respond(json=GET_CHARGER_STATUS_OK)
        results = await recent_status_changes(
            period_min=5, region="서울특별시", ctx=ctx
        )
    assert route.call_count == 1
    assert len(results) == 1
    qs = str(route.calls.last.request.url)
    assert "period=5" in qs
    assert "zcode=11" in qs


@pytest.mark.asyncio
async def test_recent_status_changes_invalid_period(ctx: ToolContext) -> None:
    with pytest.raises(ValueError, match="period_min"):
        await recent_status_changes(period_min=0, ctx=ctx)
    with pytest.raises(ValueError, match="period_min"):
        await recent_status_changes(period_min=11, ctx=ctx)
