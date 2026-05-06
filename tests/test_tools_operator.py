from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from ev_mcp.context import ToolContext
from ev_mcp.models import ChargerInfo
from ev_mcp.tools.operator import COLD_PATH_PAGE_SIZE, list_chargers_by_operator

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


def _full_page_response(rows: list[dict[str, Any]], *, page_no: int, total_count: int) -> dict:
    return {
        "response": {
            "header": {
                "resultCode": "00",
                "resultMsg": "NORMAL SERVICE.",
                "totalCount": total_count,
                "pageNo": page_no,
                "numOfRows": COLD_PATH_PAGE_SIZE,
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
async def test_cold_path_paginates_until_minor_operator_found(ctx: ToolContext) -> None:
    """Regression: cache cold (warming failed) + minor operator (CV/EV/...) used
    to return 0 rows because cold-path fetched only page 1 (ME-dominant) and
    filtered client-side. Fix: paginate until limit met or totalCount reached.

    Simulates: page 1 = full ME page (no EV), page 2 = EV rows. Asserts both
    pages are fetched and EV results returned.
    """
    page1_me = [_row(stat_id=f"ME{i:06d}", busi_id="ME", busi_nm="기후에너지환경부")
                for i in range(COLD_PATH_PAGE_SIZE)]
    page2_ev = [_row(stat_id=f"EV{i:06d}", busi_id="EV", busi_nm="에버온")
                for i in range(3)]
    total = COLD_PATH_PAGE_SIZE + len(page2_ev)

    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        route = router.get("/getChargerInfo")
        route.side_effect = [
            httpx.Response(200, json=_full_page_response(page1_me, page_no=1, total_count=total)),
            httpx.Response(200, json={
                "response": {
                    "header": {
                        "resultCode": "00",
                        "resultMsg": "NORMAL SERVICE.",
                        "totalCount": total,
                        "pageNo": 2,
                        "numOfRows": COLD_PATH_PAGE_SIZE,
                    },
                    "body": {"items": {"item": page2_ev}},
                }
            }),
        ]

        assert ctx.caches.station_info.is_fresh() is False
        results = await list_chargers_by_operator(operator="에버온", ctx=ctx)

    assert route.call_count == 2, f"expected 2 page fetches, got {route.call_count}"
    assert len(results) == len(page2_ev), f"expected {len(page2_ev)} EV rows, got {len(results)}"
    assert all(r.busi_id == "EV" for r in results)


@pytest.mark.asyncio
async def test_cold_path_stops_when_limit_satisfied(ctx: ToolContext) -> None:
    """ME 가 페이지 1 에 충분히 많으면 페이지 2 안 뽑음 (불필요한 호출 회피)."""
    page1_me = [_row(stat_id=f"ME{i:06d}", busi_id="ME", busi_nm="기후에너지환경부")
                for i in range(COLD_PATH_PAGE_SIZE)]

    async with respx.mock(base_url=ctx.settings.api_base_url) as router:
        route = router.get("/getChargerInfo").respond(
            json=_full_page_response(page1_me, page_no=1, total_count=COLD_PATH_PAGE_SIZE * 5),
        )
        assert ctx.caches.station_info.is_fresh() is False
        results = await list_chargers_by_operator(operator="ME", limit=10, ctx=ctx)

    assert route.call_count == 1, f"limit=10 should stop after page 1 (got {route.call_count})"
    assert len(results) == 10
    assert all(r.busi_id == "ME" for r in results)


@pytest.mark.asyncio
async def test_list_by_operator_invalid(ctx: ToolContext) -> None:
    with pytest.raises(ValueError, match="operator"):
        await list_chargers_by_operator(operator="", ctx=ctx)
    with pytest.raises(ValueError, match="unknown operator"):
        await list_chargers_by_operator(operator="존재하지않는회사", ctx=ctx)
