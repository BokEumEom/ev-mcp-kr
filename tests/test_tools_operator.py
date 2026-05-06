from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from ev_mcp.context import ToolContext
from ev_mcp.models import ChargerInfo
from ev_mcp.tools.operator import list_chargers_by_operator

from .fixtures.sample_responses import GET_CHARGER_INFO_OK


def _seed(ctx: ToolContext) -> None:
    rows = [
        ChargerInfo.model_validate(it)
        for it in GET_CHARGER_INFO_OK["response"]["body"]["items"]["item"]
    ]
    ctx.caches.station_info.seed_for_testing(rows)


def _row(*, stat_id: str, busi_id: str, busi_nm: str, zcode: str = "11") -> dict[str, Any]:
    return {
        "statNm": f"station-{stat_id}",
        "statId": stat_id,
        "chgerId": "01",
        "chgerType": "04",
        "addr": "테스트 주소",
        "addrDetail": "",
        "lat": "37.5",
        "lng": "127.0",
        "useTime": "24시간 이용가능",
        "busiId": busi_id,
        "bnm": busi_nm,
        "busiNm": busi_nm,
        "busiCall": "",
        "stat": "2",
        "statUpdDt": "20260430000000",
        "lastTsdt": "",
        "lastTedt": "",
        "nowTsdt": "",
        "output": "50",
        "method": "단독",
        "zcode": zcode,
        "zscode": f"{zcode}680",
        "kind": "",
        "kindDetail": "",
        "parkingFree": "",
        "note": "",
        "limitYn": "N",
        "limitDetail": "",
        "delYn": "N",
        "delDetail": "",
        "trafficYn": "N",
        "year": "2024",
        "floorNum": "",
        "floorType": "",
    }


def _page(rows: list[dict[str, Any]], *, page_no: int, total_count: int) -> dict[str, Any]:
    return {
        "response": {
            "header": {
                "resultCode": "00",
                "resultMsg": "NORMAL SERVICE.",
                "totalCount": total_count,
                "pageNo": page_no,
                "numOfRows": len(rows),
            },
            "body": {"items": {"item": rows}},
        }
    }


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
async def test_list_by_operator_warms_cache_when_cold(ctx: ToolContext) -> None:
    """Regression: data.go.kr getChargerInfo lacks a bsId filter, so cold-cache
    page-1 fallback would miss minor operators (anything not 환경부/ME).
    Fix: always go through ensure_fresh + by_busi_id index.

    Simulates a 2-page upstream where page 1 is ME-only and page 2 carries the
    EV rows. The OLD cold-path (single page-1 fetch + client-side filter) would
    return 0 EV rows; the new path warms the cache via iter_all_charger_info,
    indexes both pages, and finds the EV rows.
    """
    page_size = 9999  # matches StationInfoCache.refresh_page_size default
    page1 = [_row(stat_id=f"ME{i:06d}", busi_id="ME", busi_nm="기후에너지환경부") for i in range(3)]
    page2 = [_row(stat_id=f"EV{i:06d}", busi_id="EV", busi_nm="에버온") for i in range(2)]

    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        route = router.get("/getChargerInfo")
        route.side_effect = [
            # page 1: signal more pages by claiming a full page even though we
            # only have 3 rows. iter_all_charger_info stops on partial page or
            # totalCount, so we report total_count=large and num_of_rows=page_size
            # to force a second fetch.
            httpx.Response(
                200,
                json={
                    "response": {
                        "header": {
                            "resultCode": "00",
                            "resultMsg": "NORMAL SERVICE.",
                            "totalCount": page_size + len(page2),
                            "pageNo": 1,
                            "numOfRows": page_size,
                        },
                        "body": {
                            "items": {"item": page1 + [_row(
                                stat_id=f"ME_pad{i:06d}", busi_id="ME", busi_nm="기후에너지환경부"
                            ) for i in range(page_size - len(page1))]},
                        },
                    }
                },
            ),
            httpx.Response(200, json=_page(page2, page_no=2, total_count=page_size + len(page2))),
        ]

        assert ctx.caches.station_info.is_fresh() is False
        results = await list_chargers_by_operator(operator="에버온", ctx=ctx)

    assert ctx.caches.station_info.is_fresh() is True
    assert len(results) == 2, f"expected 2 EV rows from page 2, got {len(results)}"
    assert all(r.busi_id == "EV" for r in results)


@pytest.mark.asyncio
async def test_list_by_operator_invalid(ctx: ToolContext) -> None:
    with pytest.raises(ValueError, match="operator"):
        await list_chargers_by_operator(operator="", ctx=ctx)
    with pytest.raises(ValueError, match="unknown operator"):
        await list_chargers_by_operator(operator="존재하지않는회사", ctx=ctx)
