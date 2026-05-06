"""Tools: get_charger_status, recent_status_changes."""

from __future__ import annotations

import re

from ..client import EvChargerError
from ..codes_lookup import resolve_sido, resolve_sigungu
from ..context import ToolContext
from ..domain import StatusChange
from ..models import ChargerStatusRow

DEFAULT_LIMIT = 50
MAX_LIMIT = 100  # token-budget guard
DEFAULT_PERIOD_MIN = 5
MAX_PERIOD_MIN = 10
STAT_ID_MAX_LEN = 8
CHGER_ID_LEN = 2
_STAT_ID_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")
_CHGER_ID_RE = re.compile(r"^[A-Za-z0-9]{2}$")


async def get_charger_status(
    *,
    stat_id: str,
    chger_id: str,
    ctx: ToolContext,
) -> StatusChange:
    """특정 충전기의 실시간 상태 조회.

    캐시(60s) 우선, 없으면 upstream getChargerStatus 직접 호출.

    Parameters
    ----------
    stat_id: 충전소 ID (8자리, 예: "28260005")
    chger_id: 충전기 ID (2자리, 예: "02")

    예시
    ----
    "충전소 28260005 의 02번 충전기 지금 상태 알려줘"
        → stat_id="28260005", chger_id="02"
    """
    if not _STAT_ID_RE.fullmatch(stat_id):
        raise ValueError(f"stat_id must be 1..{STAT_ID_MAX_LEN} alphanumeric chars")
    if not _CHGER_ID_RE.fullmatch(chger_id):
        raise ValueError(f"chger_id must be exactly {CHGER_ID_LEN} alphanumeric chars")

    key = ("status_one", stat_id, chger_id)

    async def fetch() -> list[ChargerStatusRow]:
        _, items = await ctx.client.get_charger_status(stat_id=stat_id, chger_id=chger_id)
        return items

    items = await ctx.caches.status.get_or_fetch(key, fetch)
    if not items:
        raise EvChargerError(
            f"충전기 {stat_id}/{chger_id} 를 찾을 수 없습니다.",
            result_code="NOT_FOUND",
        )
    return StatusChange.from_row(items[0])


async def recent_status_changes(
    *,
    period_min: int = DEFAULT_PERIOD_MIN,
    region: str | None = None,
    sigungu: str | None = None,
    limit: int = DEFAULT_LIMIT,
    ctx: ToolContext,
) -> list[StatusChange]:
    """최근 N분(1~10) 사이 상태가 갱신된 충전기 목록.

    upstream getChargerStatus 의 ``period`` 파라미터 사용. 60초 캐시.

    Parameters
    ----------
    period_min: 1~10 분 (기본 5).
    region: 선택. "서울" 또는 "11" 같은 zcode.
    sigungu: 선택. "강남구" 또는 "11680" zscode.
    limit: 최대 반환 개수. 기본 50, 최대 100.

    예시
    ----
    "최근 5분 사이 서울에서 상태가 바뀐 충전기 알려줘"
        → period_min=5, region="서울특별시"
    """
    if not 1 <= period_min <= MAX_PERIOD_MIN:
        raise ValueError(f"period_min must be 1..{MAX_PERIOD_MIN}")
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")

    zcode: str | None = None
    if region:
        zcode = resolve_sido(region)
        if zcode is None:
            raise ValueError(f"unknown region: {region!r}")
    zscode: str | None = None
    if sigungu:
        zscode = resolve_sigungu(sigungu)
        if zscode is None:
            raise ValueError(f"unknown sigungu: {sigungu!r}")

    # NOTE: period 가 이미 서버측 시간필터라 fetch 자체가 좁혀짐. 하지만 응답이
    # statId 정렬이라 num_of_rows=100 으론 ME(환경부) 가 다 점유 → 다른 운영기관
    # 0건. period=5 면 전국 수천 행 정도일 테니 9999 로 키워 다양성 보존.
    key = ("status_recent", period_min, zcode, zscode)

    async def fetch() -> list[ChargerStatusRow]:
        _, items = await ctx.client.get_charger_status(
            period=period_min,
            zcode=zcode,
            zscode=zscode,
            num_of_rows=9999,
        )
        return items

    rows = await ctx.caches.status.get_or_fetch(key, fetch)
    return [StatusChange.from_row(r) for r in rows[:limit]]
