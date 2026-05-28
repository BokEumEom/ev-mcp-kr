"""Unit tests for the inventory_trend tool (Phase 11)."""

from __future__ import annotations

import pytest

from ev_mcp.analytics import AnalyticsError
from ev_mcp.context import ToolContext
from ev_mcp.tools.analytics_inventory_trend import inventory_trend


async def test_trend_returns_row_per_observation(ctx: ToolContext) -> None:
    """관측일별 1행 — 픽스처는 2개 스냅샷.

    오름차순 정렬, 첫 행 delta_total=None, 둘째 행은 직전 대비 증감.
    older 총계는 latest 보다 ME 20 적음 → delta_total = 20.
    """
    rows = inventory_trend(ctx=ctx)
    assert len(rows) == 2
    assert rows[0].snapshot_date == "2026-05-20"
    assert rows[0].delta_total is None
    assert rows[1].snapshot_date == "2026-05-22"
    assert rows[1].total_chargers - rows[0].total_chargers == 20
    assert rows[1].delta_total == 20


async def test_trend_single_snapshot_has_null_delta(ctx_single_snapshot: ToolContext) -> None:
    """스냅샷 1개 → 1행, delta_total None."""
    rows = inventory_trend(ctx=ctx_single_snapshot)
    assert len(rows) == 1
    assert rows[0].delta_total is None


async def test_trend_empty_dir_raises(ctx_empty_snapshot: ToolContext) -> None:
    """스냅샷 0개 → AnalyticsError (레이어에서)."""
    with pytest.raises(AnalyticsError, match="스냅샷"):
        inventory_trend(ctx=ctx_empty_snapshot)


async def test_trend_invalid_limit_raises(ctx: ToolContext) -> None:
    """limit 범위(1~90) 초과 → ValueError."""
    with pytest.raises(ValueError, match="1~90"):
        inventory_trend(limit=0, ctx=ctx)
    with pytest.raises(ValueError, match="1~90"):
        inventory_trend(limit=91, ctx=ctx)
