"""Tool: analyze_operator_health — 운영자별 비가동률 + 모니터링 부재율 top N.

Phase 10 (ADR-001). Parquet 스냅샷 위에서 GROUP BY busi_id 로 집계.

stat 코드 의미 (`src/ev_mcp/codes/stat.json`):
- ``"1"`` 통신이상   → 가동 불가
- ``"2"`` 충전대기   → 즉시 사용 가능
- ``"3"`` 충전중     → 가동 중 (다른 사용자)
- ``"4"`` 운영중지   → 가동 불가
- ``"5"`` 점검중     → 가동 불가
- ``"9"`` 상태미확인 → **충전기 가동 여부와 별개** — 운영자가 실시간 상태를
  데이터고고개알 API 로 보고하지 않는 상태. 통신 단절일 수도, 단순 미연동일 수도 있음.

따라서 진짜 "비가동" 은 ``stat IN ('1','4','5')`` (DOWNTIME_CODES).
``stat='9'`` 는 별도 (UNMONITORED_CODE) — 데이터 자체가 부재.

운영 현실 (실 스냅샷 검증, 2026-05-11):
- 전체 충전기의 약 3.3% 가 ``stat='9'``.
- 일부 운영자 (예: 미래에스디 400대 전체, 에너넷 281대 전체) 가 전 충전기가 ``stat='9'``
  → 그 운영자의 충전기들이 모두 멈춰있는 게 아니라, 운영자가 실시간 상태를 보고
  안 하는 케이스. ``downtime_ratio`` 와 ``unmonitored_ratio`` 를 분리해 둘 다 노출.
"""

from __future__ import annotations

from ..codes_lookup import busi_id_label
from ..context import ToolContext
from ..domain import OperatorHealthRow

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
DEFAULT_MIN_CHARGERS = 100
DOWNTIME_CODES = ("1", "4", "5")  # 통신이상 / 운영중지 / 점검중
UNMONITORED_CODE = "9"  # 상태미확인 — 모니터링 부재 (별도)
AVAILABLE_CODE = "2"


_QUERY_TEMPLATE = """
    SELECT
        busi_id,
        ANY_VALUE(busi_nm) AS busi_nm,
        COUNT(*) AS total_chargers,
        SUM(CASE WHEN stat = ? THEN 1 ELSE 0 END) AS available_now,
        SUM(CASE WHEN stat IN (?, ?, ?) THEN 1 ELSE 0 END) AS downtime_count,
        AVG(CASE WHEN stat IN (?, ?, ?) THEN 1.0 ELSE 0.0 END) AS downtime_ratio,
        SUM(CASE WHEN stat = ? THEN 1 ELSE 0 END) AS unmonitored_count,
        AVG(CASE WHEN stat = ? THEN 1.0 ELSE 0.0 END) AS unmonitored_ratio
    FROM {source}
    WHERE del_yn = 'N'
    GROUP BY busi_id
    HAVING COUNT(*) >= ?
    ORDER BY downtime_ratio DESC, total_chargers DESC
    LIMIT ?
"""


def analyze_operator_health(
    *,
    limit: int = DEFAULT_LIMIT,
    min_chargers: int = DEFAULT_MIN_CHARGERS,
    ctx: ToolContext,
) -> list[OperatorHealthRow]:
    """운영자별 실제 비가동률(``stat IN ('1','4','5')``) top N + 모니터링 부재율 동반.

    Phase 10 의 DuckDB 분석 사이드카(ADR-001). Parquet 스냅샷 기준 (일별, 최신).

    **비가동 정의:**
    "1" 통신이상 / "4" 운영중지 / "5" 점검중 의 합. 즉 *실제 사용 불가* 상태만.
    "9" 상태미확인 은 **별도** — 운영자가 실시간 상태를 보고 안 하는 경우
    (충전기 자체는 정상일 수 있음). ``unmonitored_ratio`` 로 동반 노출.

    Parameters
    ----------
    limit:
        반환할 최대 운영자 수. 기본 10, 최대 50.
    min_chargers:
        통계적 의미를 위해 이 수 이상의 충전기를 가진 운영자만 포함. 기본 100.

    Returns
    -------
    list[OperatorHealthRow]
        ``downtime_ratio`` 내림차순. 동률이면 ``total_chargers`` 내림차순.
        각 행에 ``unmonitored_ratio`` 도 포함 — 같이 봐야 진짜 운영 품질 판단 가능.

    예시
    ----
    "운영자별로 충전기가 가장 자주 고장나는 곳 top 10"
        → limit=10 (기본). 결과의 unmonitored_ratio 가 높으면 "데이터 부재로 판단 보류"
          라고 해석.

    "큰 운영자(500대 이상)만 비가동률 비교"
        → min_chargers=500
    """
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit 은 1~{MAX_LIMIT} 사이여야 합니다 (받은 값: {limit})")
    if min_chargers < 1:
        raise ValueError(f"min_chargers 는 1 이상이어야 합니다 (받은 값: {min_chargers})")

    rows = ctx.analytics.query(
        _QUERY_TEMPLATE,
        [
            AVAILABLE_CODE,
            *DOWNTIME_CODES,
            *DOWNTIME_CODES,
            UNMONITORED_CODE,
            UNMONITORED_CODE,
            min_chargers,
            limit,
        ],
    )

    return [
        OperatorHealthRow(
            busi_id=r[0],
            busi_nm=r[1] or "",
            operator_label=busi_id_label(r[0]),
            total_chargers=int(r[2]),
            available_now=int(r[3]),
            downtime_count=int(r[4]),
            downtime_ratio=float(r[5]),
            unmonitored_count=int(r[6]),
            unmonitored_ratio=float(r[7]),
        )
        for r in rows
    ]
