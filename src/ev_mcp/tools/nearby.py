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


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometers."""
    lat1_r, lat2_r = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def _bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """Cheap pre-filter box around (lat, lng). Returns (lat_min, lat_max, lng_min, lng_max)."""
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * max(cos(radians(lat)), 0.01))
    return (lat - lat_delta, lat + lat_delta, lng - lng_delta, lng + lng_delta)


async def find_chargers_nearby(  # noqa: PLR0912
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

    - 좌표(lat, lng) 직접 주거나 address 만 줘도 됨 (address 는 VWorld 지오코더 사용).
    - 캐시(24h)가 있으면 메모리에서 haversine 필터; 없으면 사용자 위치의 시도(zcode)
      범위로 upstream 호출 후 클라이언트 측 필터.

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

    rows: list[ChargerInfo]
    if ctx.caches.station_info.is_fresh():
        rows = ctx.caches.station_info.all_rows
    else:
        zcode = _nearest_zcode(lat, lng)
        if zcode is None:
            raise ValueError(
                f"좌표 ({lat}, {lng}) 가 한국 영역 밖입니다. "
                "한국 내 좌표 또는 주소를 입력해주세요."
            )
        _, rows = await ctx.client.get_charger_info(zcode=zcode, num_of_rows=9999)

    lat_min, lat_max, lng_min, lng_max = _bounding_box(lat, lng, radius_km)
    type_set = set(charger_type) if charger_type else None

    candidates: list[tuple[float, ChargerInfo]] = []
    for r in rows:
        if not (lat_min <= r.lat <= lat_max and lng_min <= r.lng <= lng_max):
            continue
        if type_set is not None and r.chger_type not in type_set:
            continue
        if available_only and r.stat != ChargerStatusCode.AVAILABLE:
            continue
        d = haversine_km(lat, lng, r.lat, r.lng)
        if d <= radius_km:
            candidates.append((d, r))

    candidates.sort(key=lambda t: t[0])
    out: list[ChargerNearby] = []
    for d, r in candidates[:limit]:
        summary = ChargerSummary.from_info(r)
        out.append(ChargerNearby(**summary.model_dump(), distance_km=round(d, 3)))
    return out


# Cheap region resolution: bounding-box approximations of each sido.
# Wrong on borders, but the bulk fetch overshoots anyway (radius is the final filter).
_SIDO_BOXES: dict[str, tuple[float, float, float, float]] = {
    "11": (37.40, 37.70, 126.76, 127.18),  # 서울
    "26": (35.05, 35.40, 128.85, 129.30),  # 부산
    "27": (35.75, 36.05, 128.45, 128.80),  # 대구
    "28": (37.30, 37.78, 126.30, 126.80),  # 인천
    "29": (35.05, 35.30, 126.70, 127.00),  # 광주
    "30": (36.20, 36.45, 127.30, 127.60),  # 대전
    "31": (35.45, 35.70, 129.10, 129.45),  # 울산
    "36": (36.40, 36.65, 127.20, 127.40),  # 세종
    "41": (37.00, 38.30, 126.40, 127.85),  # 경기
    "43": (36.50, 37.30, 127.30, 128.85),  # 충북
    "44": (35.95, 37.10, 126.10, 127.65),  # 충남
    "46": (33.95, 35.50, 125.85, 127.80),  # 전남
    "47": (35.50, 37.20, 128.00, 130.00),  # 경북
    "48": (34.50, 35.95, 127.50, 129.20),  # 경남
    "50": (33.10, 33.60, 126.10, 126.95),  # 제주
    "51": (37.00, 38.65, 127.50, 130.00),  # 강원
    "52": (35.30, 36.30, 126.60, 127.95),  # 전북
}


def _nearest_zcode(lat: float, lng: float) -> str | None:
    for code, (lat_min, lat_max, lng_min, lng_max) in _SIDO_BOXES.items():
        if lat_min <= lat <= lat_max and lng_min <= lng <= lng_max:
            return code
    return None
