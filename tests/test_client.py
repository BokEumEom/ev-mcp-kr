from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from ev_mcp.client import EvChargerClient, EvChargerError
from ev_mcp.models import ChargerStatusCode
from ev_mcp.settings import Settings

from .fixtures.sample_responses import (
    GET_CHARGER_INFO_ERROR,
    GET_CHARGER_INFO_OK,
    GET_CHARGER_STATUS_OK,
    GET_CHARGER_STATUS_SINGLE_ITEM_DICT,
    make_info_page,
)


@pytest.mark.asyncio
async def test_get_charger_info_success(settings: Settings) -> None:
    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").respond(json=GET_CHARGER_INFO_OK)
        async with EvChargerClient(settings) as client:
            header, items = await client.get_charger_info(num_of_rows=10)
    assert header.result_code == "00"
    assert header.total_count == 2
    assert len(items) == 2
    assert items[0].stat_id == "28260005"
    assert items[0].stat == ChargerStatusCode.AVAILABLE


@pytest.mark.asyncio
async def test_get_charger_info_propagates_service_key(settings: Settings) -> None:
    async with respx.mock(base_url=settings.api_base_url) as router:
        route = router.get("/getChargerInfo").respond(json=GET_CHARGER_INFO_OK)
        async with EvChargerClient(settings) as client:
            await client.get_charger_info()
    sent_url = str(route.calls.last.request.url)
    assert "serviceKey=" in sent_url
    assert "dataType=JSON" in sent_url


@pytest.mark.asyncio
async def test_get_charger_info_error_result_code_raises(settings: Settings) -> None:
    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").respond(json=GET_CHARGER_INFO_ERROR)
        async with EvChargerClient(settings) as client:
            with pytest.raises(EvChargerError) as exc_info:
                await client.get_charger_info()
    assert exc_info.value.result_code == "30"


@pytest.mark.asyncio
async def test_get_charger_status_success(settings: Settings) -> None:
    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerStatus").respond(json=GET_CHARGER_STATUS_OK)
        async with EvChargerClient(settings) as client:
            _, items = await client.get_charger_status()
    assert len(items) == 1
    assert items[0].stat == ChargerStatusCode.AVAILABLE


@pytest.mark.asyncio
async def test_get_charger_status_handles_single_item_dict(settings: Settings) -> None:
    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerStatus").respond(json=GET_CHARGER_STATUS_SINGLE_ITEM_DICT)
        async with EvChargerClient(settings) as client:
            _, items = await client.get_charger_status()
    assert len(items) == 1
    assert items[0].stat == ChargerStatusCode.CHARGING


@pytest.mark.asyncio
async def test_iter_all_charger_info_pagination(settings: Settings) -> None:
    total = 25
    page_size = 10
    pages = {
        1: make_info_page(total, 1, page_size),
        2: make_info_page(total, 2, page_size),
        3: make_info_page(total, 3, page_size),
    }

    def respond(request: httpx.Request) -> httpx.Response:
        page_no = int(request.url.params["pageNo"])
        return httpx.Response(200, json=pages[page_no])

    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").mock(side_effect=respond)
        all_ids: list[str] = []
        async with EvChargerClient(settings) as client:
            async for charger in client.iter_all_charger_info(page_size=page_size):
                all_ids.append(charger.stat_id)
    assert len(all_ids) == total
    assert all_ids[0] == "00000001"
    assert all_ids[-1] == f"{total:08d}"


@pytest.mark.asyncio
async def test_period_validation(settings: Settings) -> None:
    async with EvChargerClient(settings) as client:
        with pytest.raises(ValueError, match="period"):
            await client.get_charger_status(period=15)
        with pytest.raises(ValueError, match="num_of_rows"):
            await client.get_charger_info(num_of_rows=10_000)


@pytest.mark.asyncio
async def test_retry_on_transport_error(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    async with respx.mock(base_url=settings.api_base_url) as router:
        route = router.get("/getChargerInfo")
        route.side_effect = [
            httpx.ConnectError("boom"),
            httpx.ConnectError("boom"),
            httpx.Response(200, json=GET_CHARGER_INFO_OK),
        ]
        async with EvChargerClient(settings) as client:
            _, items = await client.get_charger_info()
    assert len(items) == 2
    assert route.call_count == 3


# --- regression: review-driven --------------------------------------------------


@pytest.mark.asyncio
async def test_4xx_is_not_retried_and_does_not_leak_service_key(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """401/403 from the gateway must fail fast and never expose SERVICE_KEY."""

    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    async with respx.mock(base_url=settings.api_base_url) as router:
        route = router.get("/getChargerInfo").respond(
            status_code=401,
            text="<error>SERVICE KEY IS NOT REGISTERED</error>",
        )
        async with EvChargerClient(settings) as client:
            with pytest.raises(EvChargerError) as exc_info:
                await client.get_charger_info()
    assert route.call_count == 1  # zero retries
    assert "TEST_KEY_NOT_REAL" not in str(exc_info.value)
    assert exc_info.value.result_code == "401"


@pytest.mark.asyncio
async def test_5xx_is_retried_then_succeeds(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    async with respx.mock(base_url=settings.api_base_url) as router:
        route = router.get("/getChargerInfo")
        route.side_effect = [
            httpx.Response(503, text="upstream busy"),
            httpx.Response(200, json=GET_CHARGER_INFO_OK),
        ]
        async with EvChargerClient(settings) as client:
            _, items = await client.get_charger_info()
    assert len(items) == 2
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_non_json_body_is_redacted(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the gateway echoes our serviceKey in an HTML/XML body, error must mask it."""

    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    leak = (
        '<html>denied for url '
        'http://example/getChargerInfo?serviceKey=TEST_KEY_NOT_REAL&amp;dataType=JSON</html>'
    )
    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").respond(
            status_code=200,
            headers={"content-type": "text/html"},
            text=leak,
        )
        async with EvChargerClient(settings) as client:
            with pytest.raises(EvChargerError) as exc_info:
                await client.get_charger_info()
    msg = str(exc_info.value)
    assert "TEST_KEY_NOT_REAL" not in msg
    assert "***" in msg


@pytest.mark.asyncio
async def test_xml_content_type_with_json_body_still_parses(settings: Settings) -> None:
    """Gateway sometimes returns content-type=text/xml even when body is JSON."""
    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").respond(
            status_code=200,
            headers={"content-type": "text/xml"},
            json=GET_CHARGER_INFO_OK,
        )
        async with EvChargerClient(settings) as client:
            header, items = await client.get_charger_info()
    assert header.result_code == "00"
    assert len(items) == 2


@pytest.mark.asyncio
async def test_missing_body_returns_empty_items(settings: Settings) -> None:
    """`{response: {header: ...}}` with no body must give an empty list, not crash."""
    payload = {
        "response": {
            "header": {
                "resultCode": "00",
                "resultMsg": "NORMAL SERVICE.",
                "totalCount": 0,
                "pageNo": 1,
                "numOfRows": 10,
            }
        }
    }
    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").respond(json=payload)
        async with EvChargerClient(settings) as client:
            _, items = await client.get_charger_info()
    assert items == []


@pytest.mark.asyncio
async def test_empty_string_query_params_are_dropped(settings: Settings) -> None:
    """Caller passing zcode='' must NOT show up as zcode= in the request URL."""
    async with respx.mock(base_url=settings.api_base_url) as router:
        route = router.get("/getChargerInfo").respond(json=GET_CHARGER_INFO_OK)
        async with EvChargerClient(settings) as client:
            await client.get_charger_info(zcode="", zscode=None)
    qs = str(route.calls.last.request.url)
    assert "zcode=" not in qs.replace("zscode=", "")
    assert "zscode=" not in qs


@pytest.mark.asyncio
async def test_pagination_stops_on_partial_page(settings: Settings) -> None:
    """If a page returns fewer rows than page_size, iteration must stop there."""
    page_size = 10
    page1 = make_info_page(total_count=999_999, page_no=1, num_of_rows=page_size)
    # second page deliberately partial — iter must stop after this
    short_page = make_info_page(total_count=999_999, page_no=2, num_of_rows=page_size)
    short_page["response"]["body"]["items"]["item"] = short_page["response"]["body"]["items"][
        "item"
    ][:3]

    pages = {1: page1, 2: short_page}

    def respond(request: httpx.Request) -> httpx.Response:
        page_no = int(request.url.params["pageNo"])
        return httpx.Response(200, json=pages[page_no])

    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").mock(side_effect=respond)
        async with EvChargerClient(settings) as client:
            count = 0
            async for _ in client.iter_all_charger_info(page_size=page_size):
                count += 1
    assert count == 13  # 10 + 3, then bail
