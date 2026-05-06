from __future__ import annotations

from typing import Any

import pytest
import respx

from ev_mcp.cache import build_caches
from ev_mcp.client import EvChargerClient
from ev_mcp.context import ToolContext
from ev_mcp.geocode import VWORLD_BASE_URL
from ev_mcp.models import ChargerInfo
from ev_mcp.settings import Settings
from ev_mcp.store import ChargerStore
from ev_mcp.tools.nearby import find_chargers_nearby, haversine_km


def _make_charger(stat_id: str, lat: float, lng: float, **overrides: Any) -> ChargerInfo:
    base = {
        "statNm": f"station-{stat_id}",
        "statId": stat_id,
        "chgerId": "01",
        "chgerType": "04",
        "addr": "테스트",
        "addrDetail": "",
        "lat": lat,
        "lng": lng,
        "useTime": "24시간 이용가능",
        "busiId": "EV",
        "bnm": "민간",
        "busiNm": "에버온",
        "busiCall": "",
        "stat": "2",
        "statUpdDt": "",
        "lastTsdt": "",
        "lastTedt": "",
        "nowTsdt": "",
        "output": "",
        "method": "",
        "zcode": "11",
        "zscode": "11680",
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
    base.update(overrides)
    return ChargerInfo.model_validate(base)


def test_haversine_known_distance() -> None:
    # 서울 시청과 강남역 사이 약 8.7km (실제 8.5~9.0km)
    d = haversine_km(37.5663, 126.9779, 37.4979, 127.0276)
    assert 8.0 < d < 10.0


@pytest.mark.asyncio
async def test_nearby_filters_radius_and_sorts(ctx: ToolContext) -> None:
    rows = [
        _make_charger("00000001", 37.5000, 127.0300),
        _make_charger("00000002", 37.5050, 127.0350),
        _make_charger("00000003", 37.5663, 126.9779),
        _make_charger("00000004", 33.5000, 126.5000),
    ]
    ctx.store.seed_for_testing(rows)
    results = await find_chargers_nearby(
        lat=37.4979, lng=127.0276, radius_km=2.0, ctx=ctx
    )
    assert [r.stat_id for r in results] == ["00000001", "00000002"]
    assert results[0].distance_km < results[1].distance_km


@pytest.mark.asyncio
async def test_nearby_filters_charger_type_and_available(ctx: ToolContext) -> None:
    rows = [
        _make_charger("S1", 37.500, 127.030, chgerType="04", stat="2"),
        _make_charger("S2", 37.501, 127.031, chgerType="02", stat="2"),
        _make_charger("S3", 37.502, 127.032, chgerType="04", stat="3"),
    ]
    ctx.store.seed_for_testing(rows)
    results = await find_chargers_nearby(
        lat=37.500,
        lng=127.030,
        radius_km=1.0,
        charger_type=["04"],
        available_only=True,
        ctx=ctx,
    )
    assert [r.stat_id for r in results] == ["S1"]


@pytest.mark.asyncio
async def test_nearby_uses_geocoder_when_address_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVICE_KEY", "TEST_KEY_NOT_REAL")
    monkeypatch.setenv("VWORLD_KEY", "VWORLD_TEST_KEY")
    monkeypatch.setenv("DB_PATH", ":memory:")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    rows = [_make_charger("X", 37.4980, 127.0280)]
    caches = build_caches(settings)
    store = ChargerStore(":memory:")
    store.seed_for_testing(rows)

    vworld = {
        "response": {
            "status": "OK",
            "result": {"point": {"x": "127.0276", "y": "37.4979"}, "text": "강남역"},
        }
    }

    try:
        async with respx.mock(assert_all_called=False) as router:
            router.get(VWORLD_BASE_URL).respond(json=vworld)
            async with EvChargerClient(settings) as client:
                ctx = ToolContext(
                    settings=settings, client=client, store=store, caches=caches
                )
                results = await find_chargers_nearby(
                    address="강남역", radius_km=1.0, ctx=ctx
                )
        assert len(results) == 1
        assert results[0].stat_id == "X"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_nearby_address_without_vworld_raises(ctx: ToolContext) -> None:
    rows = [_make_charger("A", 37.5, 127.0)]
    ctx.store.seed_for_testing(rows)
    with pytest.raises(ValueError, match="VWORLD_KEY"):
        await find_chargers_nearby(address="강남역", ctx=ctx)


@pytest.mark.asyncio
async def test_nearby_invalid_input(ctx: ToolContext) -> None:
    with pytest.raises(ValueError, match="radius_km"):
        await find_chargers_nearby(lat=37.5, lng=127.0, radius_km=0, ctx=ctx)
    with pytest.raises(ValueError, match="radius_km"):
        await find_chargers_nearby(lat=37.5, lng=127.0, radius_km=100, ctx=ctx)
    with pytest.raises(ValueError, match="lat, lng"):
        await find_chargers_nearby(ctx=ctx)
    with pytest.raises(ValueError, match="limit"):
        await find_chargers_nearby(lat=37.5, lng=127.0, limit=0, ctx=ctx)


@pytest.mark.asyncio
async def test_nearby_outside_korea_cold_cache_raises(ctx: ToolContext) -> None:
    """Cold cache + out-of-Korea coordinate must NOT trigger nationwide fetch."""
    with pytest.raises(ValueError, match="한국 영역 밖"):
        await find_chargers_nearby(
            lat=40.7128, lng=-74.0060, radius_km=5.0, ctx=ctx
        )
