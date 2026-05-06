"""Tool: search_chargers_by_region — 시도/시군구로 충전기 검색."""

from __future__ import annotations

from ..codes_lookup import resolve_sido, resolve_sigungu
from ..context import ToolContext
from ..domain import ChargerSummary
from ..models import ChargerInfo, ChargerStatusCode

DEFAULT_LIMIT = 50
MAX_LIMIT = 100  # token-budget guard


async def search_chargers_by_region(
    *,
    sido: str,
    sigungu: str | None = None,
    charger_type: list[str] | None = None,
    available_only: bool = False,
    limit: int = DEFAULT_LIMIT,
    ctx: ToolContext,
) -> list[ChargerSummary]:
    """시도(/시군구) 단위로 충전기를 찾습니다.

    영속 SQLite 인벤토리의 idx_zcode/idx_zscode 룩업. 추가 필터 (충전기 타입,
    available_only) 는 결과 셋에서 후처리. fetch 는 limit 의 4 배까지 받고 거른 뒤
    limit 만큼 반환.

    Parameters
    ----------
    sido:
        "서울특별시" 같은 한국어 또는 zcode "11". 부분 일치도 허용 ("서울" → 11).
    sigungu:
        "강남구" 같은 한국어 또는 zscode "11680". 동명이 여러 개일 때만 코드 필요.
    charger_type:
        충전기 타입 코드 리스트 (예: ["04", "06"] = DC콤보, DC차데모+AC3상+DC콤보).
    available_only:
        True 면 stat=2 (충전대기) 인 충전기만 반환.
    limit:
        최대 반환 개수. 기본 50, 최대 100.

    예시
    ----
    "서울 강남구에 사용 가능한 DC콤보 충전기 알려줘"
        → sido="서울특별시", sigungu="강남구",
          charger_type=["04","06"], available_only=True

    "제주도 충전기 어디 있어?"
        → sido="제주특별자치도"
    """
    if not sido:
        raise ValueError("sido is required")
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")

    zcode = resolve_sido(sido)
    if zcode is None:
        raise ValueError(f"unknown sido: {sido!r}")

    zscode: str | None = None
    if sigungu:
        zscode = resolve_sigungu(sigungu)
        if zscode is None:
            raise ValueError(f"unknown sigungu: {sigungu!r}")

    # over-fetch so post-filtering still leaves room for `limit` results
    fetch_limit = min(max(limit * 4, 100), 1000)
    rows: list[ChargerInfo]
    if zscode:
        rows = ctx.store.by_zscode(zscode, limit=fetch_limit)
    else:
        rows = ctx.store.by_zcode(zcode, limit=fetch_limit)

    type_set = set(charger_type) if charger_type else None
    out: list[ChargerSummary] = []
    for r in rows:
        if type_set is not None and r.chger_type not in type_set:
            continue
        if available_only and r.stat != ChargerStatusCode.AVAILABLE:
            continue
        out.append(ChargerSummary.from_info(r))
        if len(out) >= limit:
            break
    return out
