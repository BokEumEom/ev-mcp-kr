"""Tool: list_chargers_by_operator — 운영기관(busiId)으로 충전기 목록."""

from __future__ import annotations

from ..codes_lookup import resolve_busi_id, resolve_sido
from ..context import ToolContext
from ..domain import ChargerSummary

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

    data.go.kr getChargerInfo 는 운영기관(bsId) 업스트림 필터가 없으므로 항상
    풀 인벤토리 캐시에서 필터. 캐시가 콜드면 ensure_fresh 가 워밍을 트리거하고
    그 동안 호출자는 기다림 (~10-30초, 한 번). 이후 모든 호출은 메모리 룩업.

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

    await ctx.caches.station_info.ensure_fresh(ctx.client)
    rows = ctx.caches.station_info.by_busi_id.get(busi_id, [])
    if zcode:
        rows = [r for r in rows if r.zcode == zcode]

    return [ChargerSummary.from_info(r) for r in rows[:limit]]
