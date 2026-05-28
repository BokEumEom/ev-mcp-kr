"""Unit tests for the snapshot_diff tool (Phase 11)."""

from __future__ import annotations

import pytest

from ev_mcp.context import ToolContext
from ev_mcp.tools.analytics_snapshot_diff import snapshot_diff


async def test_diff_default_dates_compares_two_latest(ctx: ToolContext) -> None:
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


async def test_diff_explicit_dates(ctx: ToolContext) -> None:
    """명시한 from/to 날짜로 비교 — synced_at 양쪽 모두 노출."""
    result = snapshot_diff(from_date="2026-05-20", to_date="2026-05-22", ctx=ctx)
    assert result.appeared == 20
    assert result.from_synced_at == "2026-05-20T03:00:00+00:00"
    assert result.to_synced_at == "2026-05-22T03:00:00+00:00"


async def test_diff_unknown_date_raises(ctx: ToolContext) -> None:
    """존재하지 않는 명시 날짜 → ValueError + 사용 가능 날짜 안내."""
    with pytest.raises(ValueError, match="스냅샷이 없습니다"):
        snapshot_diff(from_date="2024-01-01", to_date="2026-05-22", ctx=ctx)


async def test_diff_requires_two_snapshots(ctx_single_snapshot: ToolContext) -> None:
    """스냅샷이 1개뿐이면 ValueError."""
    with pytest.raises(ValueError, match="2개"):
        snapshot_diff(ctx=ctx_single_snapshot)
