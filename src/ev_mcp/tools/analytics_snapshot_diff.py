"""Tool: snapshot_diff — 두 스냅샷 날짜 사이 충전기 변화 집계.

Phase 11 (시계열 분석 기반). v_all 위에서 from/to 두 관측을 충전기 고유키
(stat_id + chger_id)로 full outer join 한다.
"""

from __future__ import annotations

from ..context import ToolContext
from ..domain import SnapshotDiff

_OBSERVATIONS_QUERY = """
    SELECT snapshot_date, ANY_VALUE(synced_at) AS synced_at
    FROM v_all
    GROUP BY snapshot_date
    ORDER BY snapshot_date
"""

MIN_SNAPSHOTS_REQUIRED = 2  # 비교하려면 관측이 최소 2개

_DIFF_QUERY = """
    WITH f AS (
        SELECT stat_id, chger_id, stat FROM v_all
        WHERE snapshot_date = ? AND del_yn = 'N'
    ),
    t AS (
        SELECT stat_id, chger_id, stat FROM v_all
        WHERE snapshot_date = ? AND del_yn = 'N'
    )
    SELECT
        COUNT(*) FILTER (WHERE f.chger_id IS NULL) AS appeared,
        COUNT(*) FILTER (WHERE t.chger_id IS NULL) AS disappeared,
        COUNT(*) FILTER (
            WHERE f.chger_id IS NOT NULL AND t.chger_id IS NOT NULL
              AND f.stat IS DISTINCT FROM t.stat
        ) AS stat_changed
    FROM f
    FULL OUTER JOIN t ON f.stat_id = t.stat_id AND f.chger_id = t.chger_id
"""


def snapshot_diff(
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    ctx: ToolContext,
) -> SnapshotDiff:
    """두 스냅샷 날짜 사이 충전기 변화 — 신규/제거/상태변경 집계.

    Phase 11 의 시계열 분석 툴. Parquet 스냅샷 관측열(v_all) 위에서 from/to
    두 날짜를 충전기 고유키로 비교한다.

    Parameters
    ----------
    from_date:
        비교 시작 날짜 ("YYYY-MM-DD"). None 이면 직전(끝에서 두 번째) 관측.
    to_date:
        비교 끝 날짜 ("YYYY-MM-DD"). None 이면 최신 관측.

    Returns
    -------
    SnapshotDiff
        appeared(신규)·disappeared(제거)·stat_changed(상태변경)·net_change.
        각 관측의 synced_at 도 포함 — 두 관측이 같은 synced_at 이면 "변화 0"
        은 데이터가 안 바뀐 것일 뿐임을 알 수 있다.

    예시
    ----
    "지난 스냅샷 대비 충전기가 얼마나 늘었어?"
        → 인자 없이 호출 (최근 2개 관측 자동 비교).

    "5월 20일과 22일 사이 변화"
        → from_date="2026-05-20", to_date="2026-05-22"
    """
    observations = ctx.analytics.query(_OBSERVATIONS_QUERY, [])
    if len(observations) < MIN_SNAPSHOTS_REQUIRED:
        raise ValueError(
            f"비교하려면 스냅샷이 2개 이상 필요합니다 (현재 {len(observations)}개). "
            "ev-mcp-snapshot 을 며칠에 걸쳐 실행해 관측을 쌓으세요."
        )
    synced_by_date = {str(r[0]): str(r[1]) for r in observations}
    dates = sorted(synced_by_date)

    resolved_from = from_date if from_date is not None else dates[-2]
    resolved_to = to_date if to_date is not None else dates[-1]
    for label, d in (("from_date", resolved_from), ("to_date", resolved_to)):
        if d not in synced_by_date:
            raise ValueError(
                f"{label}={d!r} 에 해당하는 스냅샷이 없습니다. "
                f"사용 가능한 날짜: {dates}"
            )

    row = ctx.analytics.query(_DIFF_QUERY, [resolved_from, resolved_to])[0]
    appeared, disappeared, stat_changed = int(row[0]), int(row[1]), int(row[2])
    return SnapshotDiff(
        from_date=resolved_from,
        to_date=resolved_to,
        from_synced_at=synced_by_date[resolved_from],
        to_synced_at=synced_by_date[resolved_to],
        appeared=appeared,
        disappeared=disappeared,
        stat_changed=stat_changed,
        net_change=appeared - disappeared,
    )
