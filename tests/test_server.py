"""Integration tests for the FastMCP server wiring + Starlette wrapper."""

from __future__ import annotations

import json
import logging as stdlogging

import httpx
import pytest
from httpx import ASGITransport

from ev_mcp import server
from ev_mcp.server import (
    _RESOURCE_TABLES,
    _build_starlette_app,
    build_server,
)
from ev_mcp.settings import Settings


@pytest.mark.asyncio
async def test_build_server_registers_all_tools(settings: Settings) -> None:
    mcp, _ctx = build_server(settings)
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        # Phase 1~9: lookup tools
        "find_chargers_nearby",
        "get_charger_status",
        "search_chargers_by_region",
        "list_chargers_by_operator",
        "get_station_details",
        "recent_status_changes",
        "lookup_codes",
        # Phase 10 (ADR-001): analytics sidecar
        "analyze_operator_health",
        "regional_density",
    }


@pytest.mark.asyncio
async def test_all_tools_have_read_only_annotation(settings: Settings) -> None:
    mcp, _ctx = build_server(settings)
    tools = await mcp.list_tools()
    for t in tools:
        assert t.annotations is not None, f"{t.name} missing annotations"
        assert t.annotations.readOnlyHint is True, f"{t.name} not read-only"


@pytest.mark.asyncio
async def test_resources_template_registered(settings: Settings) -> None:
    mcp, _ctx = build_server(settings)
    templates = await mcp.list_resource_templates()
    template_uris = {t.uri_template for t in templates}
    assert "codes://{category}" in template_uris


@pytest.mark.asyncio
async def test_resource_template_returns_each_table(settings: Settings) -> None:
    mcp, _ctx = build_server(settings)
    for category in _RESOURCE_TABLES:
        result = await mcp.read_resource(f"codes://{category}")
        assert result.contents, f"empty resource for {category}"
        body = result.contents[0].content
        assert isinstance(body, str)
        parsed = json.loads(body)
        assert isinstance(parsed, dict)
        assert len(parsed) > 0


@pytest.mark.asyncio
async def test_lookup_codes_tool_callable(settings: Settings) -> None:
    mcp, _ctx = build_server(settings)
    result = await mcp.call_tool("lookup_codes", {"category": "stat"})
    assert result.structured_content == {
        "0": "알수없음",
        "1": "통신이상",
        "2": "충전대기",
        "3": "충전중",
        "4": "운영중지",
        "5": "점검중",
        "6": "예약중",
        "9": "상태미확인",
    }


@pytest.mark.asyncio
async def test_health_endpoint_reports_store_state(settings: Settings) -> None:
    mcp, ctx = build_server(settings)
    app = _build_starlette_app(mcp, ctx)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["store"]["rows"] == 0
    assert body["store"]["last_synced_at"] is None


@pytest.mark.asyncio
async def test_cors_preflight_allows_claude_origin(settings: Settings) -> None:
    mcp, ctx = build_server(settings)
    app = _build_starlette_app(mcp, ctx)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.options(
            "/health",
            headers={
                "origin": "https://claude.ai",
                "access-control-request-method": "GET",
            },
        )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "https://claude.ai"


@pytest.mark.asyncio
async def test_third_party_logger_secret_redaction(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """ANY logger (httpx, uvicorn, third-party) emitting SERVICE_KEY must be scrubbed."""
    server._LOGGING_CONFIGURED = False
    server.configure_logging("INFO", settings=settings)

    caplog.set_level(stdlogging.INFO)
    other = stdlogging.getLogger("some.third.party")
    other.setLevel(stdlogging.INFO)
    other.info("HTTP GET https://x/y?serviceKey=TEST_KEY_NOT_REAL&dataType=JSON")

    full = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "TEST_KEY_NOT_REAL" not in full

    server._LOGGING_CONFIGURED = False


@pytest.mark.asyncio
async def test_httpx_info_logger_pinned_to_warning(settings: Settings) -> None:
    server._LOGGING_CONFIGURED = False
    server.configure_logging("INFO", settings=settings)
    httpx_logger = stdlogging.getLogger("httpx")
    assert httpx_logger.level == stdlogging.WARNING
    server._LOGGING_CONFIGURED = False


@pytest.mark.asyncio
async def test_mcp_lifespan_initializes_session_manager(settings: Settings) -> None:
    """Regression: FastMCP's task group MUST be initialized via mcp_app.lifespan."""
    mcp, ctx = build_server(settings)
    app = _build_starlette_app(mcp, ctx)

    transport = ASGITransport(app=app)
    # Drive lifespan + send a real MCP request. Without the lifespan fix,
    # FastMCP raises 500 with "Task group is not initialized".
    # 400 is acceptable here — MCP requires `initialize` before `tools/list`,
    # so a "missing session" 400 still proves the task group came up.
    async with (
        httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=True
        ) as ac,
        app.router.lifespan_context(app),
    ):
        resp = await ac.post(
            "/mcp/",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    # The critical thing is that we are NOT getting 500 from the task-group bug.
    assert resp.status_code != 500
    assert resp.status_code < 500
