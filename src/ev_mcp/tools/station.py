"""Tool: get_station_details — 충전소 ID 로 전체 정보 조회."""

from __future__ import annotations

import re

from ..client import EvChargerError
from ..context import ToolContext
from ..domain import StationDetails

STAT_ID_MAX_LEN = 8
_STAT_ID_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


async def get_station_details(*, stat_id: str, ctx: ToolContext) -> StationDetails:
    """충전소 ID 로 그 충전소의 모든 충전기 정보를 한 번에 반환.

    내부적으로 캐시(24h)를 먼저 확인하고, 없으면 upstream getChargerInfo 를 statId
    필터로 직접 호출합니다. 한 충전소에는 보통 2~6 대의 충전기가 있고, 응답에는
    각 충전기의 타입·상태·운영시간이 모두 포함됩니다.

    Parameters
    ----------
    stat_id:
        충전소 ID (8자리, 예: "28260005")

    예시
    ----
    "충전소 28260005 정보 알려줘"
        → stat_id="28260005"
    """
    if not _STAT_ID_RE.fullmatch(stat_id):
        raise ValueError(f"stat_id must be 1..{STAT_ID_MAX_LEN} alphanumeric chars")

    if ctx.caches.station_info.is_fresh():
        rows = ctx.caches.station_info.by_stat_id.get(stat_id, [])
        if rows:
            return StationDetails.from_chargers(rows)

    _, items = await ctx.client.get_charger_info(stat_id=stat_id, num_of_rows=50)
    if not items:
        raise EvChargerError(
            f"충전소 ID {stat_id!r} 를 찾을 수 없습니다.",
            result_code="NOT_FOUND",
        )
    return StationDetails.from_chargers(items)
