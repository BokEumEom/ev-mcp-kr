from __future__ import annotations

import httpx
import pytest
import respx

from ev_mcp.geocode import VWORLD_BASE_URL, Geocoder, GeocoderError, GeocoderUnavailable
from ev_mcp.settings import Settings


@pytest.fixture
def settings_with_vworld(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SERVICE_KEY", "TEST_KEY_NOT_REAL")
    monkeypatch.setenv("VWORLD_KEY", "VWORLD_TEST_KEY")
    return Settings(_env_file=None)  # type: ignore[call-arg]


VWORLD_OK = {
    "response": {
        "service": {"name": "address", "version": "2.0", "operation": "getcoord", "time": "10ms"},
        "status": "OK",
        "input": {"type": "road", "address": "서울 강남구 강남대로 396"},
        "refined": {"text": "서울특별시 강남구 강남대로 396"},
        "result": {
            "crs": "EPSG:4326",
            "point": {"x": "127.029700", "y": "37.499590"},
            "text": "서울특별시 강남구 강남대로 396",
        },
    }
}

VWORLD_NOT_FOUND = {
    "response": {
        "service": {"name": "address"},
        "status": "NOT_FOUND",
    }
}


@pytest.mark.asyncio
async def test_geocode_success(settings_with_vworld: Settings) -> None:
    async with respx.mock() as router:
        router.get(VWORLD_BASE_URL).respond(json=VWORLD_OK)
        async with Geocoder(settings_with_vworld) as g:
            result = await g.geocode("서울 강남구 강남대로 396")
    assert pytest.approx(result.lat, abs=1e-4) == 37.499590
    assert pytest.approx(result.lng, abs=1e-4) == 127.029700
    assert "강남대로" in result.matched_address


@pytest.mark.asyncio
async def test_geocode_unconfigured_raises_unavailable(settings: Settings) -> None:
    """VWORLD_KEY 미설정 → GeocoderUnavailable."""
    async with Geocoder(settings) as g:
        assert g.is_configured is False
        with pytest.raises(GeocoderUnavailable, match="VWORLD_KEY"):
            await g.geocode("any address")


@pytest.mark.asyncio
async def test_geocode_falls_back_to_parcel_then_fails(
    settings_with_vworld: Settings,
) -> None:
    """road 검색 NOT_FOUND → parcel 재시도 → 그래도 NOT_FOUND → GeocoderError."""
    async with respx.mock() as router:
        router.get(VWORLD_BASE_URL).mock(
            side_effect=[
                httpx.Response(200, json=VWORLD_NOT_FOUND),
                httpx.Response(200, json=VWORLD_NOT_FOUND),
            ]
        )
        async with Geocoder(settings_with_vworld) as g:
            with pytest.raises(GeocoderError, match="could not resolve"):
                await g.geocode("not a real address")


@pytest.mark.asyncio
async def test_geocode_http_5xx_raises_unavailable_without_key_leak(
    settings_with_vworld: Settings,
) -> None:
    async with respx.mock() as router:
        router.get(VWORLD_BASE_URL).respond(
            status_code=503,
            text="<error>service unavailable for key=VWORLD_TEST_KEY</error>",
        )
        async with Geocoder(settings_with_vworld) as g:
            with pytest.raises(GeocoderUnavailable) as exc_info:
                await g.geocode("anything")
    assert "VWORLD_TEST_KEY" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_geocode_parcel_retry_5xx_redacts_key(
    settings_with_vworld: Settings,
) -> None:
    """road NOT_FOUND → parcel 503 with key in body must NOT leak the key."""
    async with respx.mock() as router:
        router.get(VWORLD_BASE_URL).mock(
            side_effect=[
                httpx.Response(200, json=VWORLD_NOT_FOUND),
                httpx.Response(503, text="upstream busy for VWORLD_TEST_KEY"),
            ]
        )
        async with Geocoder(settings_with_vworld) as g:
            with pytest.raises(GeocoderUnavailable) as exc_info:
                await g.geocode("anything")
    assert "VWORLD_TEST_KEY" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_geocode_non_json_body_redacts(settings_with_vworld: Settings) -> None:
    async with respx.mock() as router:
        router.get(VWORLD_BASE_URL).respond(
            status_code=200,
            text="<html>denied for VWORLD_TEST_KEY</html>",
        )
        async with Geocoder(settings_with_vworld) as g:
            with pytest.raises(GeocoderUnavailable) as exc_info:
                await g.geocode("anything")
    assert "VWORLD_TEST_KEY" not in str(exc_info.value)
    assert "***" in str(exc_info.value)
