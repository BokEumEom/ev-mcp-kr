"""Async httpx client for the data.go.kr EvCharger OpenAPI v1.23.

Two operations are exposed:
- get_charger_info: ``getChargerInfo``
- get_charger_status: ``getChargerStatus``

Both use ``dataType=JSON`` exclusively (the spec also supports XML, but JSON
keeps parsing simple and matches what FastMCP serializes downstream).

Security note
-------------
data.go.kr's gateway is known to echo the full request URL (including
``serviceKey``) in error bodies, and httpx's exception ``__str__`` includes the
request URL. Every code path that touches an exception or a raw response body
runs it through :func:`_redact` so the SERVICE_KEY never leaves the process in
logs, traces, or MCP responses.
"""

from __future__ import annotations

import asyncio
import random
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog
from pydantic import ValidationError

from .models import ChargerInfo, ChargerStatusRow, ResultHeader
from .settings import Settings

logger = structlog.get_logger(__name__)

OK_RESULT_CODE = "00"
MAX_NUM_OF_ROWS = 9999  # spec hard limit
MIN_STATUS_PERIOD_MIN = 1
MAX_STATUS_PERIOD_MIN = 10  # spec hard limit on the `period` query param
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
PAGINATION_PAGE_GUARD = 1000  # 9999 rows * 1000 pages = 10M rows, way past any real total


class EvChargerError(RuntimeError):
    """Upstream API returned a non-zero resultCode or a transport failure."""

    def __init__(self, message: str, *, result_code: str | None = None) -> None:
        super().__init__(message)
        self.result_code = result_code


def _unwrap_items(payload: dict[str, Any]) -> tuple[ResultHeader, list[dict[str, Any]]]:
    """Normalize the JSON envelope shapes data.go.kr returns.

    Some endpoints wrap as ``{"response": {"header": {...}, "body": {"items": {"item": [...]}}}}``
    and others (when there is exactly one row) collapse ``item`` to a dict instead of a list.
    The flat ``{"resultCode": ..., "items": {"item": [...]}}`` shape from the spec sample is
    also supported.
    """

    if "response" in payload:
        payload = payload["response"]

    if "header" in payload:
        header_dict = payload["header"]
        body = payload.get("body") or {}
        items_obj = body.get("items") if isinstance(body, dict) else None
    else:
        header_dict = {
            "resultCode": payload.get("resultCode"),
            "resultMsg": payload.get("resultMsg"),
            "pageNo": payload.get("pageNo"),
            "numOfRows": payload.get("numOfRows"),
            "totalCount": payload.get("totalCount"),
        }
        items_obj = payload.get("items")

    items_raw: list[dict[str, Any]] = []
    if isinstance(items_obj, dict):
        item = items_obj.get("item")
        if isinstance(item, list):
            items_raw = item
        elif isinstance(item, dict):
            items_raw = [item]
    elif isinstance(items_obj, list):
        items_raw = items_obj

    try:
        header = ResultHeader.model_validate(header_dict)
    except ValidationError as e:
        raise EvChargerError(f"malformed response header: {e}") from e
    return header, items_raw


class EvChargerClient:
    """Async client. Use as an async context manager."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=settings.request_timeout_s,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> EvChargerClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def redact(self, text: object) -> str:
        """Strip the SERVICE_KEY out of any string that came from upstream.

        data.go.kr keys are base64-ish, so they may appear in raw, ``urllib.parse.quote``,
        or ``quote_plus`` form depending on which library serialized them.
        """
        s = str(text)
        key = self._settings.service_key.get_secret_value()
        if not key:
            return s
        for variant in {
            key,
            urllib.parse.quote(key, safe=""),
            urllib.parse.quote_plus(key),
        }:
            if variant:
                s = s.replace(variant, "***")
        return s

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, httpx.TransportError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in RETRYABLE_STATUS_CODES
        return False

    async def _request(self, op: str, params: dict[str, Any]) -> dict[str, Any]:
        full_params: dict[str, Any] = {
            "serviceKey": self._settings.service_key.get_secret_value(),
            "dataType": "JSON",
            **{k: v for k, v in params.items() if v not in (None, "")},
        }
        last_exc: Exception | None = None
        for attempt in range(1, self._settings.max_retries + 1):
            try:
                resp = await self._client.get(f"/{op}", params=full_params)
                resp.raise_for_status()
                # Upstream sometimes returns text/xml content-type even with dataType=JSON
                # when the gateway throttles. Trust the body.
                try:
                    payload: dict[str, Any] = resp.json()
                except ValueError:
                    safe_body = self.redact(resp.text[:200])
                    raise EvChargerError(
                        f"non-JSON response from {op} "
                        f"(status={resp.status_code}, body[:200]={safe_body!r})"
                    ) from None
                return payload
            except httpx.HTTPStatusError as e:
                if not self._is_retryable(e):
                    raise EvChargerError(
                        f"{op} HTTP {e.response.status_code}",
                        result_code=str(e.response.status_code),
                    ) from None
                last_exc = e
            except httpx.TransportError as e:
                last_exc = e

            if attempt >= self._settings.max_retries:
                break
            base = 0.5 * (2 ** (attempt - 1))
            backoff = base * (1 + random.random() * 0.3)
            logger.warning(
                "evcharger %s attempt %d failed: %s; retrying in %.2fs",
                op,
                attempt,
                self.redact(last_exc),
                backoff,
            )
            await asyncio.sleep(backoff)
        assert last_exc is not None  # loop only exits via break or successful return
        raise EvChargerError(f"{op} failed after retries: {self.redact(last_exc)}") from None

    async def get_charger_info(
        self,
        *,
        page_no: int = 1,
        num_of_rows: int = 100,
        zcode: str | None = None,
        zscode: str | None = None,
        kind: str | None = None,
        kind_detail: str | None = None,
        stat_id: str | None = None,
        chger_id: str | None = None,
    ) -> tuple[ResultHeader, list[ChargerInfo]]:
        if num_of_rows > MAX_NUM_OF_ROWS:
            raise ValueError(f"num_of_rows must be <= {MAX_NUM_OF_ROWS}")
        payload = await self._request(
            "getChargerInfo",
            {
                "pageNo": page_no,
                "numOfRows": num_of_rows,
                "zcode": zcode,
                "zscode": zscode,
                "kind": kind,
                "kindDetail": kind_detail,
                "statId": stat_id,
                "chgerId": chger_id,
            },
        )
        header, raw_items = _unwrap_items(payload)
        if header.result_code != OK_RESULT_CODE:
            raise EvChargerError(
                f"getChargerInfo error: {header.result_msg}",
                result_code=header.result_code,
            )
        items = [ChargerInfo.model_validate(it) for it in raw_items]
        return header, items

    async def get_charger_status(
        self,
        *,
        page_no: int = 1,
        num_of_rows: int = 100,
        period: int | None = None,
        zcode: str | None = None,
        zscode: str | None = None,
        stat_id: str | None = None,
        chger_id: str | None = None,
    ) -> tuple[ResultHeader, list[ChargerStatusRow]]:
        if period is not None and not MIN_STATUS_PERIOD_MIN <= period <= MAX_STATUS_PERIOD_MIN:
            raise ValueError(
                f"period must be between {MIN_STATUS_PERIOD_MIN} and {MAX_STATUS_PERIOD_MIN} minutes"
            )
        if num_of_rows > MAX_NUM_OF_ROWS:
            raise ValueError(f"num_of_rows must be <= {MAX_NUM_OF_ROWS}")
        payload = await self._request(
            "getChargerStatus",
            {
                "pageNo": page_no,
                "numOfRows": num_of_rows,
                "period": period,
                "zcode": zcode,
                "zscode": zscode,
                "statId": stat_id,
                "chgerId": chger_id,
            },
        )
        header, raw_items = _unwrap_items(payload)
        if header.result_code != OK_RESULT_CODE:
            raise EvChargerError(
                f"getChargerStatus error: {header.result_msg}",
                result_code=header.result_code,
            )
        items = [ChargerStatusRow.model_validate(it) for it in raw_items]
        return header, items

    async def iter_all_charger_info(
        self,
        *,
        page_size: int = MAX_NUM_OF_ROWS,
        zcode: str | None = None,
    ) -> AsyncIterator[ChargerInfo]:
        """Yield every row across all pages. Used by the warm-cache job.

        Stops on any of: empty page, partial page (<page_size), reached totalCount,
        or hitting the absolute page guard.
        """
        page_no = 1
        while True:
            header, items = await self.get_charger_info(
                page_no=page_no,
                num_of_rows=page_size,
                zcode=zcode,
            )
            for it in items:
                yield it
            total = header.total_count or 0
            seen = page_no * page_size
            if not items or len(items) < page_size or seen >= total:
                return
            if page_no >= PAGINATION_PAGE_GUARD:
                logger.warning(
                    "iter_all_charger_info hit page guard at %d (totalCount=%s)",
                    PAGINATION_PAGE_GUARD,
                    total,
                )
                return
            page_no += 1
