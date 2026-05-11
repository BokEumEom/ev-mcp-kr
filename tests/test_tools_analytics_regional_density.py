"""Tests for regional_density (Phase 10, ADR-001)."""

from __future__ import annotations

import pytest

from ev_mcp.context import ToolContext
from ev_mcp.tools.analytics_regional_density import regional_density


async def test_happy_path_sigungu_grouping(ctx: ToolContext) -> None:
    """fixture: zscode 11680 (ME+EV = 350), 41460 (KM+TINY = 170)."""
    rows = regional_density(group_by="sigungu", limit=10, ctx=ctx)
    assert len(rows) == 2
    # Largest zscode first
    assert rows[0].zscode == "11680"
    assert rows[0].total_chargers == 350  # ME(200) + EV(150)
    assert rows[0].distinct_operators == 2
    # Each operator alternates DC/AC half-half → DC ratio ≈ 0.5
    assert rows[0].dc_ratio == pytest.approx(0.5, rel=0.05)
    assert rows[1].zscode == "41460"
    assert rows[1].total_chargers == 170


async def test_sido_grouping_aggregates_across_sigungu(ctx: ToolContext) -> None:
    """group_by='sido' collapses zscode → zcode level."""
    rows = regional_density(group_by="sido", limit=10, ctx=ctx)
    counts = {r.zcode: r.total_chargers for r in rows}
    assert counts["11"] == 350  # ME + EV
    assert counts["41"] == 170  # KM + TINY
    for r in rows:
        assert r.zscode is None
        assert r.sigungu_label is None


async def test_rejects_invalid_group_by(ctx: ToolContext) -> None:
    """group_by='gu' → ValueError."""
    with pytest.raises(ValueError, match="group_by"):
        regional_density(group_by="gu", ctx=ctx)


async def test_rejects_invalid_limit(ctx: ToolContext) -> None:
    """limit out of bounds → ValueError."""
    with pytest.raises(ValueError, match="limit"):
        regional_density(limit=0, ctx=ctx)
    with pytest.raises(ValueError, match="limit"):
        regional_density(limit=51, ctx=ctx)


async def test_del_yn_y_excluded(ctx: ToolContext) -> None:
    """del_yn='Y' fixture row must not inflate counts."""
    rows = regional_density(group_by="sigungu", limit=10, ctx=ctx)
    z11 = next(r for r in rows if r.zscode == "11680")
    # If del_yn='Y' had been counted, total would be 351.
    assert z11.total_chargers == 350
