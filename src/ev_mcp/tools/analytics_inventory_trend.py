"""Tool: inventory_trend — 관측일별 충전기 인벤토리 곡선.

Phase 11 (시계열 분석 기반). v_all 위에서 snapshot_date 별로 집계.
delta_total(직전 관측 대비 증감)은 Python 에서 계산한다.
"""

from __future__ import annotations

from ..context import ToolContext
from ..domain import InventoryTrendRow
from ._analytics_shared import DC_CODES

DEFAULT_LIMIT = 30
MAX_LIMIT = 90
AVAILABLE_CODE = "2"

_QUERY_TEMPLATE = """
    SELECT
        CAST(snapshot_date AS VARCHAR) AS snapshot_date,
        ANY_VALUE(synced_at) AS synced_at,
        COUNT(*) AS total_chargers,
        SUM(CASE WHEN chger_type IN ({dc_placeholders}) THEN 1 ELSE 0 END) AS dc_count,
        SUM(CASE WHEN stat = ? THEN 1 ELSE 0 END) AS available_count,
        COUNT(DISTINCT busi_id) AS distinct_operators
    FROM v_all
    WHERE del_yn = 'N'
    GROUP BY snapshot_date
    ORDER BY snapshot_date DESC
    LIMIT ?
"""


def inventory_trend(
    *,
    limit: int = DEFAULT_LIMIT,
    ctx: ToolContext,
) -> list[InventoryTrendRow]:
    """관측일별 충전기 인벤토리 추세 — 총수/DC/가용/운영자 수 + 직전 대비 증감.

    Phase 11 의 시계열 분석 툴. Parquet 스냅샷 관측열(v_all) 위에서 집계.
    스냅샷은 불규칙 관측열이므로 날짜 간격이 일정하지 않을 수 있다. 각 행의
    synced_at 을 함께 보면 "추세"가 실제 데이터 변화인지 확인할 수 있다.

    Parameters
    ----------
    limit:
        반환할 최근 관측 수. 기본 30, 최대 90.

    Returns
    -------
    list[InventoryTrendRow]
        snapshot_date 오름차순. 첫 행 delta_total 은 None (직전 관측 없음).

    예시
    ----
    "충전기 수가 어떻게 늘고 있어?"
        → 인자 없이 호출.

    "최근 7개 관측만"
        → limit=7
    """
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit 은 1~{MAX_LIMIT} 사이여야 합니다 (받은 값: {limit})")

    dc_placeholders = ",".join(["?"] * len(DC_CODES))
    sql = _QUERY_TEMPLATE.format(dc_placeholders=dc_placeholders)
    rows = ctx.analytics.query(sql, [*DC_CODES, AVAILABLE_CODE, limit])

    # 쿼리는 DESC (최근 우선) 로 LIMIT 을 걸었으니, 오름차순으로 뒤집어 delta 계산.
    ordered = list(reversed(rows))
    result: list[InventoryTrendRow] = []
    prev_total: int | None = None
    for r in ordered:
        total = int(r[2])
        result.append(
            InventoryTrendRow(
                snapshot_date=str(r[0]),
                synced_at=str(r[1]),
                total_chargers=total,
                dc_count=int(r[3]),
                available_count=int(r[4]),
                distinct_operators=int(r[5]),
                delta_total=None if prev_total is None else total - prev_total,
            )
        )
        prev_total = total
    return result
