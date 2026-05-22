"""Unit tests for the DuckDB analytics sidecar — view layer (Phase 11)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from ev_mcp.analytics import AnalyticsClient, AnalyticsError
from ev_mcp.settings import Settings


def test_v_latest_returns_latest_snapshot_only(analytics: AnalyticsClient) -> None:
    """v_latest 는 최신 snapshot_date 만 — ME=200 (older 는 180)."""
    rows = analytics.query(
        "SELECT busi_id, COUNT(*) FROM v_latest WHERE del_yn='N' "
        "GROUP BY busi_id ORDER BY busi_id",
        [],
    )
    counts = {r[0]: r[1] for r in rows}
    assert counts["ME"] == 200
    assert counts["EV"] == 150


def test_v_all_spans_every_snapshot(analytics: AnalyticsClient) -> None:
    """v_all 은 모든 관측 — 2개 snapshot_date."""
    rows = analytics.query(
        "SELECT DISTINCT snapshot_date FROM v_all ORDER BY snapshot_date", []
    )
    assert len(rows) == 2


def test_empty_snapshot_dir_raises(settings: Settings, tmp_path: Path) -> None:
    """스냅샷 0개 디렉터리 → 친절한 에러."""
    empty = tmp_path / "empty"
    empty.mkdir()
    settings.snapshot_source = "local"
    settings.snapshot_dir = empty
    client = AnalyticsClient(settings)
    with pytest.raises(AnalyticsError, match="스냅샷"):
        client.query("SELECT 1 FROM v_all LIMIT 1", [])


def test_r2_without_credentials_raises(settings: Settings) -> None:
    """snapshot_source='r2' 인데 R2_BUCKET 미설정 → 명확한 에러."""
    settings.snapshot_source = "r2"
    settings.r2_bucket = None
    client = AnalyticsClient(settings)
    with pytest.raises(AnalyticsError, match="R2_BUCKET"):
        client.query("SELECT 1 FROM v_all LIMIT 1", [])


def test_unknown_source_raises(settings: Settings) -> None:
    """snapshot_source 오타 → 유효값 안내."""
    settings.snapshot_source = "redis"
    client = AnalyticsClient(settings)
    with pytest.raises(AnalyticsError, match=r"local|r2"):
        client.query("SELECT 1 FROM v_all LIMIT 1", [])


def test_redact_masks_known_secrets(settings: Settings) -> None:
    """_redact 는 R2 자격증명 값을 '***' 로 치환."""
    settings.r2_secret_access_key = SecretStr("super-secret-value-12345")
    client = AnalyticsClient(settings)
    scrubbed = client._redact("error contains super-secret-value-12345 inline")
    assert "super-secret-value-12345" not in scrubbed
    assert "***" in scrubbed


def test_close_is_idempotent(analytics: AnalyticsClient) -> None:
    """close() 두 번 호출해도 raise 안 함."""
    analytics.close()
    analytics.close()
