"""Tool: find_chargers_nearby — 좌표/주소 기준 반경 내 충전기 검색."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

import structlog

from ..context import ToolContext
from ..domain import ChargerNearby, ChargerSummary
from ..geocode import Geocoder, GeocoderError, GeocoderUnavailable
from ..models import ChargerInfo, ChargerStatusCode

logger = structlog.get_logger(__name__)

EARTH_RADIUS_KM = 6371.0
DEFAULT_RADIUS_KM = 2.0
MAX_RADIUS_KM = 20.0
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# Korea-only sanity check (very loose). VWorld geocoder + accidental foreign
# coords would otherwise scan the global bbox of an empty index.
KR_LAT_MIN, KR_LAT_MAX = 33.0, 38.7
KR_LNG_MIN, KR_LNG_MAX = 124.5, 132.0

# Over-fetch from store so post-haversine filter still has enough rows.
NEARBY_FETCH_FACTOR = 6


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometers."""
    lat1_r, lat2_r = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


async def find_chargers_nearby(
    *,
    lat: float | None = None,
    lng: float | None = None,
    address: str | None = None,
    radius_km: float = DEFAULT_RADIUS_KM,
    charger_type: list[str] | None = None,
    available_only: bool = False,
    limit: int = DEFAULT_LIMIT,
    ctx: ToolContext,
) -> list[ChargerNearby]:
    """좌표 또는 주소 기준으로 반경 내 충전기 검색.

    좌표(lat, lng) 직접 주거나 address 만 줘도 됨 (address 는 VWorld 지오코더 사용).
    영속 SQLite 인벤토리의 idx_lat_lng 로 bounding box prefilter, 결과에 haversine
    적용해 정확한 거리 필터.

    Parameters
    ----------
    lat, lng:
        WGS84 좌표. 둘 다 있으면 address 무시.
    address:
        한국어 주소 (도로명 우선, 지번 가능). VWORLD_KEY 미설정 시 ValueError.
    radius_km:
        반경 km. 기본 2.0, 최대 20.0.
    charger_type:
        충전기 타입 코드 리스트.
    available_only:
        True 면 stat=2 (충전대기) 만.
    limit:
        최대 반환 개수. 기본 20, 최대 100.

    예시
    ----
    "강남역 근처 1km 안에 사용 가능한 DC콤보 충전기 알려줘"
        → address="서울 강남구 강남대로 396", radius_km=1.0,
          charger_type=["04","06"], available_only=True

    "내 위치 (37.50, 127.03) 부근 5km 충전기"
        → lat=37.50, lng=127.03, radius_km=5.0
    """
    if radius_km <= 0 or radius_km > MAX_RADIUS_KM:
        raise ValueError(f"radius_km must be in (0, {MAX_RADIUS_KM}]")
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")

    if lat is None or lng is None:
        if not address:
            raise ValueError("either (lat, lng) or address is required")
        async with Geocoder(ctx.settings) as geo:
            try:
                geocoded = await geo.geocode(address)
            except GeocoderUnavailable as e:
                raise ValueError(
                    f"address geocoding unavailable: {e}. "
                    "Provide lat/lng directly or set VWORLD_KEY in .env."
                ) from None
            except GeocoderError as e:
                raise ValueError(str(e)) from None
        lat, lng = geocoded.lat, geocoded.lng

    if not (KR_LAT_MIN <= lat <= KR_LAT_MAX and KR_LNG_MIN <= lng <= KR_LNG_MAX):
        raise ValueError(
            f"좌표 ({lat}, {lng}) 가 한국 영역 밖입니다. "
            "한국 내 좌표 또는 주소를 입력해주세요."
        )

    candidates = ctx.store.near_lat_lng(
        lat, lng, radius_km=radius_km, limit=limit * NEARBY_FETCH_FACTOR
    )

    type_set = set(charger_type) if charger_type else None
    scored: list[tuple[float, ChargerInfo]] = []
    out: list[ChargerNearby] = []
    for r in candidates:
        if type_set is not None and r.chger_type not in type_set:
            continue
        if available_only and r.stat != ChargerStatusCode.AVAILABLE:
            continue
        d = haversine_km(lat, lng, r.lat, r.lng)
        if d > radius_km:
            continue
        scored.append((d, r))

    scored.sort(key=lambda t: t[0])
    for d, r in scored[:limit]:
        summary = ChargerSummary.from_info(r)
        out.append(ChargerNearby(**summary.model_dump(), distance_km=round(d, 3)))
    return out
