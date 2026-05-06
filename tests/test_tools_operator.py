from __future__ import annotations

from typing import Any

import pytest

from ev_mcp.context import ToolContext
from ev_mcp.models import ChargerInfo
from ev_mcp.tools.operator import list_chargers_by_operator


def _row(*, stat_id: str, busi_id: str, busi_nm: str, zcode: str = "11") -> ChargerInfo:
    payload: dict[str, Any] = {
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
        "statUpdDt": "",
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
    return ChargerInfo.model_validate(payload)


@pytest.mark.asyncio
async def test_list_by_operator_korean_name(ctx: ToolContext) -> None:
    ctx.store.seed_for_testing([
        _row(stat_id="ME0001", busi_id="ME", busi_nm="기후에너지환경부"),
        _row(stat_id="EV0001", busi_id="EV", busi_nm="에버온"),
    ])
    results = await list_chargers_by_operator(operator="기후에너지환경부", ctx=ctx)
    assert all(r.busi_id == "ME" for r in results)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_list_by_operator_with_region(ctx: ToolContext) -> None:
    ctx.store.seed_for_testing([
        _row(stat_id="EV0001", busi_id="EV", busi_nm="에버온", zcode="11"),
        _row(stat_id="EV0002", busi_id="EV", busi_nm="에버온", zcode="26"),
    ])
    results = await list_chargers_by_operator(
        operator="에버온", region="서울특별시", ctx=ctx
    )
    assert len(results) == 1
    assert results[0].sido_code == "11"


@pytest.mark.asyncio
async def test_list_by_operator_minor_operator_returns_results(ctx: ToolContext) -> None:
    """Regression: Phase 6 store-backed lookup MUST surface non-ME operators.

    The Phase 1~5 in-memory cold-path bug returned 0 rows for operators like
    CV/EV when the cache was cold. With the store, this becomes a hash-indexed
    lookup that always works regardless of warming state.
    """
    ctx.store.seed_for_testing([
        _row(stat_id=f"ME{i:06d}", busi_id="ME", busi_nm="기후에너지환경부")
        for i in range(100)
    ] + [
        _row(stat_id=f"CV{i:06d}", busi_id="CV", busi_nm="채비") for i in range(5)
    ])
    results = await list_chargers_by_operator(operator="채비", ctx=ctx)
    assert len(results) == 5
    assert all(r.busi_id == "CV" for r in results)


@pytest.mark.asyncio
async def test_list_by_operator_respects_limit(ctx: ToolContext) -> None:
    ctx.store.seed_for_testing([
        _row(stat_id=f"ME{i:06d}", busi_id="ME", busi_nm="기후에너지환경부")
        for i in range(50)
    ])
    results = await list_chargers_by_operator(operator="ME", limit=10, ctx=ctx)
    assert len(results) == 10


@pytest.mark.asyncio
async def test_list_by_operator_empty_store(ctx: ToolContext) -> None:
    """Empty store → empty result, no exception."""
    results = await list_chargers_by_operator(operator="ME", ctx=ctx)
    assert results == []


@pytest.mark.asyncio
async def test_list_by_operator_invalid(ctx: ToolContext) -> None:
    with pytest.raises(ValueError, match="operator"):
        await list_chargers_by_operator(operator="", ctx=ctx)
    with pytest.raises(ValueError, match="unknown operator"):
        await list_chargers_by_operator(operator="존재하지않는회사", ctx=ctx)
