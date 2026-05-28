"""Unit tests for the snapshot_diff tool (Phase 11)."""

from __future__ import annotations

import pytest

from ev_mcp.tools.analytics_snapshot_diff import snapshot_diff


def test_diff_default_dates_compares_two_latest(ctx) -> None:  # type: ignore[no-untyped-def]
    """기본 인자 → 최근 2개 관측(2026-05-20 vs 2026-05-22) 비교.

    픽스처: older ME=180, latest ME=200 → ME 20대 신규.
    (stat 패턴은 두 스냅샷이 동일 규칙이라 stat_changed 는 겹치는 충전기에서 0)
    """
    result = snapshot_diff(ctx=ctx)
    assert result.from_date == "2026-05-20"
    assert result.to_date == "2026-05-22"
    assert result.appeared == 20
    assert result.disappeared == 0
    assert result.net_change == 20


def test_diff_explicit_dates(ctx) -> None:  # type: ignore[no-untyped-def]
    """명시한 from/to 날짜로 비교."""
    result = snapshot_diff(from_date="2026-05-20", to_date="2026-05-22", ctx=ctx)
    assert result.appeared == 20
    assert result.from_synced_at == "2026-05-20T03:00:00+00:00"


def test_diff_requires_two_snapshots(ctx_single_snapshot) -> None:  # type: ignore[no-untyped-def]
    """스냅샷이 1개뿐이면 ValueError."""
    with pytest.raises(ValueError, match="2개"):
        snapshot_diff(ctx=ctx_single_snapshot)
