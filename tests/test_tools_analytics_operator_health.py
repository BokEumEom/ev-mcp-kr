"""Tests for analyze_operator_health (Phase 10, ADR-001)."""

from __future__ import annotations

import pytest

from ev_mcp.context import ToolContext
from ev_mcp.tools.analytics_operator_health import analyze_operator_health


async def test_happy_path_returns_top_by_downtime_ratio(ctx: ToolContext) -> None:
    """fixture: EV=40%, KM=25%, ME=5%, TINY (excluded by min_chargers)."""
    rows = analyze_operator_health(limit=10, min_chargers=100, ctx=ctx)
    assert len(rows) == 3  # TINY (50 chargers) excluded by min_chargers
    # EV has highest downtime ratio
    assert rows[0].busi_id == "EV"
    assert rows[0].downtime_count == 60
    assert rows[0].total_chargers == 150
    assert rows[0].downtime_ratio == pytest.approx(0.4, rel=0.01)
    assert rows[0].unmonitored_count == 0  # EV has no stat='9'
    # Available_now = stat='2' rows
    assert rows[0].available_now == 5
    # Last row is ME (lowest downtime ratio, even though it has unmonitored)
    assert rows[-1].busi_id == "ME"


async def test_unmonitored_separate_from_downtime(ctx: ToolContext) -> None:
    """ME has 10 stat='4' (downtime) + 15 stat='9' (unmonitored) out of 200.

    Critical regression test for the Stage 10.4 data quality fix:
    stat='9' must NOT inflate downtime_ratio. They are tracked separately.
    """
    rows = analyze_operator_health(limit=10, min_chargers=100, ctx=ctx)
    me = next(r for r in rows if r.busi_id == "ME")
    # downtime is only stat IN ('1','4','5') — here just the 10 stat='4'
    assert me.downtime_count == 10
    assert me.downtime_ratio == pytest.approx(0.05, rel=0.01)
    # unmonitored is stat='9' — tracked but does NOT count toward downtime
    assert me.unmonitored_count == 15
    assert me.unmonitored_ratio == pytest.approx(0.075, rel=0.01)
    # total_chargers must be 200, not 200 - 15 (unmonitored are still real chargers)
    assert me.total_chargers == 200


async def test_min_chargers_filters_small_operators(ctx: ToolContext) -> None:
    """min_chargers=40 should include TINY (50 chargers)."""
    rows = analyze_operator_health(limit=10, min_chargers=40, ctx=ctx)
    assert any(r.busi_id == "TINY" for r in rows)


async def test_limit_caps_results(ctx: ToolContext) -> None:
    """limit=2 returns only the top 2."""
    rows = analyze_operator_health(limit=2, min_chargers=100, ctx=ctx)
    assert len(rows) == 2
    assert rows[0].busi_id == "EV"


async def test_rejects_invalid_limit(ctx: ToolContext) -> None:
    """limit=0 or > 50 → ValueError."""
    with pytest.raises(ValueError, match="limit"):
        analyze_operator_health(limit=0, ctx=ctx)
    with pytest.raises(ValueError, match="limit"):
        analyze_operator_health(limit=100, ctx=ctx)


async def test_rejects_invalid_min_chargers(ctx: ToolContext) -> None:
    """min_chargers=0 → ValueError."""
    with pytest.raises(ValueError, match="min_chargers"):
        analyze_operator_health(min_chargers=0, ctx=ctx)


async def test_del_yn_y_rows_excluded(ctx: ToolContext) -> None:
    """fixture has 1 row with del_yn='Y' for ME — total_chargers must remain 200, not 201."""
    rows = analyze_operator_health(limit=10, min_chargers=100, ctx=ctx)
    me = next(r for r in rows if r.busi_id == "ME")
    assert me.total_chargers == 200
