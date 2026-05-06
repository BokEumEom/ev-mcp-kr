"""Tool: list_chargers_by_operator — 운영기관(busiId)으로 충전기 목록."""

from __future__ import annotations

from ..codes_lookup import resolve_busi_id, resolve_sido
from ..context import ToolContext
from ..domain import ChargerSummary
from ..models import ChargerInfo

DEFAULT_LIMIT = 50
MAX_LIMIT = 100  # token-budget guard


async def list_chargers_by_operator(
    *,
    operator: str,
    region: str | None = None,
    limit: int = DEFAULT_LIMIT,
    ctx: ToolContext,
) -> list[ChargerSummary]:
    """운영기관 별 충전기 목록.

    캐시(24h)가 있으면 메모리에서 필터; 없으면 upstream 을 (가능한) zcode 필터로
    호출 후 클라이언트 측에서 운영기관 필터.

    Parameters
    ----------
    operator:
        "환경부" / "기후에너지환경부" / "ME" / "에버온" 등. 한국어 매칭은 부분일치.
    region:
        선택. "서울특별시" 또는 zcode "11" 로 추가 시도 필터.
    limit:
        최대 반환 개수. 기본 50, 최대 100.

    예시
    ----
    "환경부가 운영하는 서울 충전기 목록 보여줘"
        → operator="기후에너지환경부", region="서울특별시"
    "에버온 충전기 알려줘"
        → operator="에버온"
    """
    if not operator:
        raise ValueError("operator is required")
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")

    busi_id = resolve_busi_id(operator)
    if busi_id is None:
        raise ValueError(f"unknown operator: {operator!r}")

    zcode: str | None = None
    if region:
        zcode = resolve_sido(region)
        if zcode is None:
            raise ValueError(f"unknown region: {region!r}")

    rows: list[ChargerInfo]
    if ctx.caches.station_info.is_fresh():
        rows = ctx.caches.station_info.by_busi_id.get(busi_id, [])
        if zcode:
            rows = [r for r in rows if r.zcode == zcode]
    else:
        _, fetched = await ctx.client.get_charger_info(
            zcode=zcode,
            num_of_rows=min(max(limit * 8, 500), 2000),
        )
        rows = [r for r in fetched if r.busi_id == busi_id]

    return [ChargerSummary.from_info(r) for r in rows[:limit]]
