"""Address → (lat, lng) via VWorld (KR government geocoder).

Free, no signup beyond an API key. We never require it: if ``VWORLD_KEY`` is
unset, :class:`Geocoder.geocode` raises :class:`GeocoderUnavailable` which
upstream tools catch and translate into "address lookup not configured —
please pass lat/lng instead".
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from .settings import Settings

logger = structlog.get_logger(__name__)

VWORLD_BASE_URL = "https://api.vworld.kr/req/address"


class GeocoderUnavailable(RuntimeError):
    """Raised when no geocoder is configured (VWORLD_KEY unset) or upstream is down."""


class GeocoderError(RuntimeError):
    """Geocoder responded but the address could not be resolved."""


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lng: float
    matched_address: str


class Geocoder:
    """Async VWorld geocoder. Use as an async context manager."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=settings.request_timeout_s)

    @property
    def is_configured(self) -> bool:
        return self._settings.vworld_key is not None

    async def __aenter__(self) -> Geocoder:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _redact(self, text: object) -> str:
        s = str(text)
        if self._settings.vworld_key is None:
            return s
        key = self._settings.vworld_key.get_secret_value()
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

    async def geocode(self, address: str) -> GeocodeResult:
        if self._settings.vworld_key is None:
            raise GeocoderUnavailable(
                "VWORLD_KEY is not configured. Pass lat/lng directly, "
                "or set VWORLD_KEY in .env."
            )
        params = {
            "service": "address",
            "request": "getcoord",
            "version": "2.0",
            "crs": "epsg:4326",
            "address": address,
            "refine": "true",
            "simple": "false",
            "format": "json",
            "type": "road",  # 도로명 우선
            "key": self._settings.vworld_key.get_secret_value(),
        }
        try:
            resp = await self._client.get(VWORLD_BASE_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise GeocoderUnavailable(
                f"vworld HTTP {e.response.status_code}: {self._redact(e)}"
            ) from None
        except httpx.TransportError as e:
            raise GeocoderUnavailable(f"vworld transport error: {self._redact(e)}") from None

        try:
            payload: dict[str, Any] = resp.json()
        except ValueError:
            raise GeocoderUnavailable(
                f"vworld returned non-JSON body: {self._redact(resp.text[:200])!r}"
            ) from None

        result = self._extract(payload)
        if result is not None:
            return result
        # Retry with parcel (지번) addressing — common for old-style addresses.
        params["type"] = "parcel"
        try:
            resp = await self._client.get(VWORLD_BASE_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise GeocoderUnavailable(
                f"vworld parcel retry failed: {self._redact(e)}"
            ) from None
        result = self._extract(payload)
        if result is None:
            raise GeocoderError(f"could not resolve address: {address!r}")
        return result

    @staticmethod
    def _extract(payload: dict[str, Any]) -> GeocodeResult | None:
        response = payload.get("response", {})
        status = response.get("status")
        if status != "OK":
            return None
        result = response.get("result", {})
        point = result.get("point", {}) if isinstance(result, dict) else {}
        try:
            lat = float(point["y"])
            lng = float(point["x"])
        except (KeyError, TypeError, ValueError):
            return None
        matched = (
            result.get("text") or result.get("matched_address") or ""
            if isinstance(result, dict)
            else ""
        )
        return GeocodeResult(lat=lat, lng=lng, matched_address=str(matched))
