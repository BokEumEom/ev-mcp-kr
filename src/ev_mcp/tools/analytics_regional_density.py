"""Tool: regional_density — 시도/시군구 단위 충전기 밀도 top N.

Phase 10 (ADR-001). Parquet 스냅샷 위에서 시군구별로 충전기 수, 운영자 다양성,
급속 충전기 비율을 집계.

급속 충전기 정의
----------------
``chger_type`` 코드 중 다음을 급속(DC 계열 또는 NACS) 으로 본다:
- "01" DC차데모
- "03" DC차데모+AC3상
- "04" DC콤보
- "05" DC차데모+DC콤보
- "06" DC차데모+AC3상+DC콤보
- "08" DC콤보(완속) — 명칭상 "완속" 이지만 코드 분류상 DC 계열
- "09" NACS
- "10" DC콤보+NACS

"02" AC완속 과 "07" AC3상 은 완속으로 분류해 제외.
"""

from __future__ import annotations

from ..codes_lookup import sido_label, sigungu_label
from ..context import ToolContext
from ..domain import RegionalDensityRow
from ._analytics_shared import DC_CODES

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
GROUP_LEVELS = ("sido", "sigungu")
DEFAULT_GROUP = "sigungu"


_QUERY_SIGUNGU = """
    SELECT
        zcode,
        zscode,
        COUNT(*) AS total_chargers,
        COUNT(DISTINCT busi_id) AS distinct_operators,
        SUM(CASE WHEN chger_type IN ({dc_placeholders}) THEN 1 ELSE 0 END) AS dc_count,
        AVG(CASE WHEN chger_type IN ({dc_placeholders}) THEN 1.0 ELSE 0.0 END) AS dc_ratio
    FROM v_latest
    WHERE del_yn = 'N' AND zscode IS NOT NULL
    GROUP BY zcode, zscode
    ORDER BY total_chargers DESC
    LIMIT ?
"""

_QUERY_SIDO = """
    SELECT
        zcode,
        NULL AS zscode,
        COUNT(*) AS total_chargers,
        COUNT(DISTINCT busi_id) AS distinct_operators,
        SUM(CASE WHEN chger_type IN ({dc_placeholders}) THEN 1 ELSE 0 END) AS dc_count,
        AVG(CASE WHEN chger_type IN ({dc_placeholders}) THEN 1.0 ELSE 0.0 END) AS dc_ratio
    FROM v_latest
    WHERE del_yn = 'N'
    GROUP BY zcode
    ORDER BY total_chargers DESC
    LIMIT ?
"""


def regional_density(
    *,
    group_by: str = DEFAULT_GROUP,
    limit: int = DEFAULT_LIMIT,
    ctx: ToolContext,
) -> list[RegionalDensityRow]:
    """시도 또는 시군구 단위 충전기 밀도 top N — 운영자 다양성 + DC 비율 포함.

    Phase 10 의 DuckDB 분석 사이드카(ADR-001). Parquet 스냅샷 위에서 집계.

    Parameters
    ----------
    group_by:
        "sido" (17개 광역) 또는 "sigungu" (~230개 시군구). 기본 "sigungu".
    limit:
        반환 행 수. 기본 10, 최대 50.

    Returns
    -------
    list[RegionalDensityRow]
        ``total_chargers`` 내림차순 정렬.

    예시
    ----
    "충전기가 가장 많은 시군구 top 10"
        → group_by="sigungu", limit=10

    "광역시도 단위로 급속 충전기 비율"
        → group_by="sido"
    """
    if group_by not in GROUP_LEVELS:
        raise ValueError(f"group_by 는 {GROUP_LEVELS} 중 하나 (받은 값: {group_by!r})")
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit 은 1~{MAX_LIMIT} 사이여야 합니다 (받은 값: {limit})")

    dc_placeholders = ",".join(["?"] * len(DC_CODES))
    template = (_QUERY_SIGUNGU if group_by == "sigungu" else _QUERY_SIDO).format(
        dc_placeholders=dc_placeholders,
    )
    params = [*DC_CODES, *DC_CODES, limit]
    rows = ctx.analytics.query(template, params)

    return [
        RegionalDensityRow(
            zcode=r[0],
            sido_label=sido_label(r[0]),
            zscode=r[1],
            sigungu_label=sigungu_label(r[1]) if r[1] else None,
            total_chargers=int(r[2]),
            distinct_operators=int(r[3]),
            dc_charger_count=int(r[4]),
            dc_ratio=float(r[5]),
        )
        for r in rows
    ]
