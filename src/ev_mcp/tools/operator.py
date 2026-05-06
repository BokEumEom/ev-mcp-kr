"""Tool: list_chargers_by_operator — 운영기관(busiId)으로 충전기 목록."""

from __future__ import annotations

from ..codes_lookup import resolve_busi_id, resolve_sido
from ..context import ToolContext
from ..domain import ChargerSummary
from ..models import ChargerInfo

DEFAULT_LIMIT = 50
MAX_LIMIT = 100  # token-budget guard

COLD_PATH_PAGE_SIZE = 2000  # ChargerInfo 한 행 ≈ 1KB → 2MB 한 페이지 (게이트웨이 안전)
COLD_PATH_MAX_PAGES = 10  # 최대 20k 행 — 한국 전체 충전기 ~12-20k 커버


async def list_chargers_by_operator(
    *,
    operator: str,
    region: str | None = None,
    limit: int = DEFAULT_LIMIT,
    ctx: ToolContext,
) -> list[ChargerSummary]:
    """운영기관 별 충전기 목록.

    캐시(24h)가 fresh 면 메모리 인덱스 룩업. 캐시 콜드면 upstream getChargerInfo
    를 페이지 단위로 순회하면서 클라이언트 측에서 운영기관 필터 (data.go.kr 가
    busiId 업스트림 필터를 지원하지 않으므로). 작은 운영기관도 결과 나오도록
    limit 채울 때까지 또는 totalCount 도달까지 페이지 진행.

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

    if ctx.caches.station_info.is_fresh():
        rows = ctx.caches.station_info.by_busi_id.get(busi_id, [])
        if zcode:
            rows = [r for r in rows if r.zcode == zcode]
        return [ChargerSummary.from_info(r) for r in rows[:limit]]

    # Cold path: paginate through getChargerInfo until limit met or pages exhausted.
    matches: list[ChargerInfo] = []
    for page_no in range(1, COLD_PATH_MAX_PAGES + 1):
        header, fetched = await ctx.client.get_charger_info(
            page_no=page_no,
            zcode=zcode,
            num_of_rows=COLD_PATH_PAGE_SIZE,
        )
        if not fetched:
            break
        matches.extend(r for r in fetched if r.busi_id == busi_id)
        if len(matches) >= limit:
            break
        seen = page_no * COLD_PATH_PAGE_SIZE
        total = header.total_count or 0
        if len(fetched) < COLD_PATH_PAGE_SIZE or (total and seen >= total):
            break

    return [ChargerSummary.from_info(r) for r in matches[:limit]]
