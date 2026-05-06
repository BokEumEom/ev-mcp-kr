"""FastMCP server entry point — wires the 7 tools, code resources, /health, CORS.

Run locally:

    ev-mcp                       # uses .env, binds 127.0.0.1:8000
    HOST=0.0.0.0 PORT=8000 ev-mcp  # container

Streamable HTTP transport is mounted at ``/mcp`` (FastMCP default).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import urllib.parse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import structlog
import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .cache import Caches, build_caches
from .client import EvChargerClient
from .codes_lookup import (
    busi_id_table,
    charger_type_table,
    kind_detail_table,
    kind_table,
    sido_table,
    sigungu_table,
    stat_table,
)
from .context import ToolContext
from .domain import ChargerNearby, ChargerSummary, StationDetails, StatusChange
from .settings import Settings, load_settings
from .tools.codes import CodeCategory
from .tools.codes import lookup_codes as _lookup_codes
from .tools.nearby import find_chargers_nearby as _find_nearby
from .tools.operator import list_chargers_by_operator as _list_by_operator
from .tools.region import search_chargers_by_region as _search_region
from .tools.station import get_station_details as _station_details
from .tools.status import get_charger_status as _charger_status
from .tools.status import recent_status_changes as _recent_changes

logger = structlog.get_logger(__name__)

READ_ONLY = {"readOnlyHint": True}


_LOGGING_CONFIGURED = False


class _SecretRedactingFilter(logging.Filter):
    """Strip SERVICE_KEY / VWORLD_KEY (raw + URL-encoded) from EVERY log record.

    Catches third-party loggers (httpx, uvicorn, asyncio) that might echo the
    full request URL with our service-key in the query string.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        variants: set[str] = set()
        for secret in (settings.service_key, settings.vworld_key):
            if secret is None:
                continue
            raw = secret.get_secret_value()
            if not raw:
                continue
            variants.add(raw)
            variants.add(urllib.parse.quote(raw, safe=""))
            variants.add(urllib.parse.quote_plus(raw))
        # Sort longest-first so we replace longer encoded variants before any
        # substring of them appears in another variant.
        self._variants = sorted((v for v in variants if v), key=len, reverse=True)

    def _scrub(self, text: str) -> str:
        for v in self._variants:
            if v and v in text:
                text = text.replace(v, "***")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._variants:
            return True
        # IMPORTANT: structlog's ProcessorFormatter expects ``record.msg`` to be
        # a dict (the structlog event dict). We MUST preserve type — only scrub
        # string values inside it, never call str() on the whole record.
        with contextlib.suppress(Exception):
            msg = record.msg
            if isinstance(msg, dict):
                record.msg = {
                    k: self._scrub(v) if isinstance(v, str) else v
                    for k, v in msg.items()
                }
            elif isinstance(msg, str):
                record.msg = self._scrub(msg)
        if record.args:
            with contextlib.suppress(Exception):
                if isinstance(record.args, dict):
                    record.args = {
                        k: self._scrub(v) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        self._scrub(a) if isinstance(a, str) else a
                        for a in record.args
                    )
        return True


def configure_logging(level: str, settings: Settings | None = None) -> None:
    """Wire structlog AND stdlib logging (uvicorn/asyncio/etc.) into one JSON sink.

    Idempotent: subsequent calls are no-ops so library mode (FastMCP stdio
    embedded into another process) doesn't blow away the host's logging.

    A :class:`_SecretRedactingFilter` is installed on the root handler so any
    logger anywhere in the process (httpx, uvicorn, asyncio, third-party) gets
    its SERVICE_KEY automatically scrubbed before serialization.
    """
    global _LOGGING_CONFIGURED  # noqa: PLW0603 — idempotency guard, single writer
    if _LOGGING_CONFIGURED:
        return
    log_level = getattr(logging, level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
    ]

    # structlog → ProcessorFormatter (so stdlib + structlog share the JSON renderer).
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    if settings is not None:
        handler.addFilter(_SecretRedactingFilter(settings))

    root = logging.getLogger()
    # Reset any existing handlers (uvicorn pre-installs colorized text handlers).
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(log_level)

    _LOGGING_CONFIGURED = True

    # Force uvicorn's named loggers to propagate to root (otherwise they'd keep their own).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
        lg.setLevel(log_level)

    # httpx logs every request at INFO and includes the FULL URL — that means
    # the SERVICE_KEY query param shows up in plaintext. Pin httpx to WARNING so
    # only failures surface, and trust the redaction filter for any leftovers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_server(settings: Settings | None = None) -> tuple[FastMCP, ToolContext]:
    """Construct the FastMCP server and the ToolContext it wraps.

    Returns both so callers (tests, lifespan handlers) can introspect.
    """
    s = settings or load_settings()
    configure_logging(s.log_level, settings=s)
    client = EvChargerClient(s)
    caches = build_caches(s)
    ctx = ToolContext(settings=s, client=client, caches=caches)

    mcp = FastMCP(
        name="ev-mcp",
        version="0.1.0",
        instructions=(
            "한국환경공단 전기자동차 충전소 정보 OpenAPI v1.23 을 노출합니다. "
            "사용자 위치 기반 검색은 find_chargers_nearby, 시도/시군구 검색은 "
            "search_chargers_by_region, 실시간 상태는 get_charger_status 를 사용하세요."
        ),
    )
    _register_tools(mcp, ctx)
    _register_resources(mcp)
    return mcp, ctx


def _register_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Bind each tool to the FastMCP app, closing over the ToolContext."""

    @mcp.tool(annotations=READ_ONLY)
    async def find_chargers_nearby(
        *,
        lat: float | None = None,
        lng: float | None = None,
        address: str | None = None,
        radius_km: float = 2.0,
        charger_type: list[str] | None = None,
        available_only: bool = False,
        limit: int = 20,
    ) -> list[ChargerNearby]:
        """좌표(lat, lng) 또는 주소(address) 기준 반경 내 충전기 검색.

        한국 내 좌표가 필요합니다. address 만 있으면 VWorld 지오코더로 변환합니다
        (VWORLD_KEY 미설정 시 ValueError). 결과는 거리 오름차순.

        **충전기 타입 코드** (charger_type 인자에 코드 리스트로 전달):
        - "01" DC차데모 / "02" AC완속 / "03" DC차데모+AC3상
        - "04" DC콤보 / "05" DC차데모+DC콤보 / "06" DC차데모+AC3상+DC콤보
        - "07" AC3상 / "08" DC콤보(완속) / "09" NACS / "10" DC콤보+NACS

        급속 충전기만 원하면 charger_type=["01","03","04","05","06","09","10"].
        DC콤보 위주: ["04","06","10"]. 사용 가능한 것만: available_only=True.
        """
        return await _find_nearby(
            lat=lat, lng=lng, address=address, radius_km=radius_km,
            charger_type=charger_type, available_only=available_only,
            limit=limit, ctx=ctx,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_charger_status(*, stat_id: str, chger_id: str) -> StatusChange:
        """특정 충전기(stat_id+chger_id)의 실시간 상태."""
        return await _charger_status(stat_id=stat_id, chger_id=chger_id, ctx=ctx)

    @mcp.tool(annotations=READ_ONLY)
    async def search_chargers_by_region(
        *,
        sido: str,
        sigungu: str | None = None,
        charger_type: list[str] | None = None,
        available_only: bool = False,
        limit: int = 50,
    ) -> list[ChargerSummary]:
        """시도/시군구로 충전기 검색. sido 는 '서울특별시' 또는 zcode '11'."""
        return await _search_region(
            sido=sido, sigungu=sigungu, charger_type=charger_type,
            available_only=available_only, limit=limit, ctx=ctx,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_chargers_by_operator(
        *,
        operator: str,
        region: str | None = None,
        limit: int = 50,
    ) -> list[ChargerSummary]:
        """운영기관(busiId)별 충전기 목록. operator 는 '환경부' 또는 'ME'."""
        return await _list_by_operator(
            operator=operator, region=region, limit=limit, ctx=ctx,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_station_details(*, stat_id: str) -> StationDetails:
        """충전소 ID 의 모든 충전기 + 충전소 정보."""
        return await _station_details(stat_id=stat_id, ctx=ctx)

    @mcp.tool(annotations=READ_ONLY)
    async def recent_status_changes(
        *,
        period_min: int = 5,
        region: str | None = None,
        sigungu: str | None = None,
        limit: int = 50,
    ) -> list[StatusChange]:
        """최근 N분(1~10) 사이 상태 변경된 충전기 목록."""
        return await _recent_changes(
            period_min=period_min, region=region, sigungu=sigungu,
            limit=limit, ctx=ctx,
        )

    @mcp.tool(annotations=READ_ONLY)
    def lookup_codes(*, category: CodeCategory) -> dict[str, str]:
        """공통 코드 테이블 조회. **반드시 category 를 7개 중 하나로 지정**.

        - "sido": 시도 (17개) — 11=서울, 41=경기 …
        - "sigungu": 시군구 zscode (230개) — 11680=강남구 …
        - "charger_type": 충전기 타입 (11개) — 01=DC차데모, 02=AC완속, 04=DC콤보,
          06=DC차데모+AC3상+DC콤보, 07=AC3상, 09=NACS …
        - "stat": 충전기 상태 (8개) — 2=충전대기, 3=충전중, 4=운영중지, 5=점검중 …
        - "busi_id": 운영기관 (180개) — ME=기후에너지환경부, EV=에버온, KM=카카오모빌리티 …
        - "kind": 충전소 구분 대분류 (10개)
        - "kind_detail": 충전소 구분 상세 (56개)

        category 가 빠지면 ValidationError. 자연어 → 코드 매핑이 필요하면 이 도구를
        먼저 호출해 코드를 확인한 뒤 다른 도구의 zcode/charger_type/busi_id 인자에
        넣으세요.
        """
        return _lookup_codes(category=category)


_RESOURCE_TABLES: dict[str, Any] = {
    "sido": sido_table,
    "sigungu": sigungu_table,
    "charger_type": charger_type_table,
    "stat": stat_table,
    "busi_id": busi_id_table,
    "kind": kind_table,
    "kind_detail": kind_detail_table,
}


def _register_resources(mcp: FastMCP) -> None:
    """Expose the static code tables as MCP resources too.

    Single template `codes://{category}` dispatches to each loader.
    """

    @mcp.resource(
        "codes://{category}",
        mime_type="application/json",
        name="codes",
        description="공통 코드 테이블 (sido / sigungu / charger_type / stat / busi_id / kind / kind_detail)",
    )
    def _codes(category: str) -> str:
        loader = _RESOURCE_TABLES.get(category)
        if loader is None:
            allowed = ", ".join(sorted(_RESOURCE_TABLES))
            raise ValueError(f"unknown code category. allowed: {allowed}")
        return json.dumps(loader(), ensure_ascii=False, indent=2)


# ---- Health endpoint + Starlette wrapper -------------------------------------


def _build_health_route(ctx: ToolContext) -> Route:
    async def health(_request: Request) -> JSONResponse:
        cache = ctx.caches.station_info
        body = {
            "ok": True,
            "version": "0.1.0",
            "station_info": {
                "rows": len(cache.all_rows),
                "fresh": cache.is_fresh(),
            },
        }
        return JSONResponse(body)

    return Route("/health", health, methods=["GET"])


def _build_starlette_app(mcp: FastMCP, ctx: ToolContext) -> Starlette:
    """Wrap the FastMCP HTTP app with /health and CORS.

    Cache warm runs as a background task — `/health` becomes 200 immediately so
    Render/Cloud healthchecks don't time out on cold start. The first user
    request hits the cold-cache fallback path until the warm task finishes.
    """

    async def _warm(client: EvChargerClient, caches: Caches) -> None:
        try:
            await caches.station_info.ensure_fresh(client)
            logger.info("cache_warmed", rows=len(caches.station_info.all_rows))
        except Exception as e:
            # Do NOT use logger.exception: traceback frames may contain SERVICE_KEY.
            logger.warning("cache_warm_failed", error=client.redact(e))

    mcp_app = mcp.http_app(transport="streamable-http")

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        # FastMCP's StreamableHTTPSessionManager initializes its task group inside
        # mcp_app.lifespan(). We MUST enter it or every /mcp request will 500 with
        # "Task group is not initialized".
        async with mcp_app.router.lifespan_context(app):
            warm_task = asyncio.create_task(_warm(ctx.client, ctx.caches))
            try:
                yield
            finally:
                warm_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await warm_task
                await ctx.client.aclose()

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=ctx.settings.cors_origin_list,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            allow_credentials=False,
        ),
    ]

    return Starlette(
        debug=False,
        lifespan=lifespan,
        middleware=middleware,
        routes=[
            _build_health_route(ctx),
            Mount("/", app=mcp_app),
        ],
    )


def build_app() -> Starlette:
    """Top-level entry point used by uvicorn / tests."""
    mcp, ctx = build_server()
    return _build_starlette_app(mcp, ctx)


def main(transport: Literal["http", "stdio"] = "http") -> None:
    """Console-script entry. ``ev-mcp`` runs HTTP; pass stdio for local dev."""
    settings = load_settings()
    if transport == "stdio":
        mcp, _ctx = build_server(settings)
        mcp.run(transport="stdio")
        return

    # Configure logging BEFORE uvicorn boots so uvicorn's named loggers route through us.
    configure_logging(settings.log_level, settings=settings)
    uvicorn.run(
        "ev_mcp.server:build_app",
        host=settings.host,
        port=settings.port,
        factory=True,
        log_config=None,  # we own logging via configure_logging()
        # All real traffic goes to POST /mcp with body — access logs would just
        # repeat the same line per request without useful diagnostics, while
        # adding a small risk of leaking proxy-forwarded query params.
        access_log=False,
    )


if __name__ == "__main__":
    main()
