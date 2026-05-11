"""Unit tests for the DuckDB analytics sidecar (Phase 10, ADR-001)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from ev_mcp.analytics import AnalyticsClient, AnalyticsError
from ev_mcp.settings import Settings


def test_query_returns_rows(analytics: AnalyticsClient) -> None:
    """Happy path — query against the fixture snapshot returns expected counts."""
    rows = analytics.query(
        "SELECT busi_id, COUNT(*) FROM {source} WHERE del_yn='N' GROUP BY busi_id ORDER BY busi_id",
        [],
    )
    counts = {r[0]: r[1] for r in rows}
    assert counts["ME"] == 200
    assert counts["EV"] == 150
    assert counts["KM"] == 120
    assert counts["TINY"] == 50


def test_query_requires_source_placeholder(analytics: AnalyticsClient) -> None:
    """Caller must include {source} — guard against forgotten placeholder."""
    with pytest.raises(AnalyticsError, match="source"):
        analytics.query("SELECT COUNT(*) FROM chargers", [])


def test_missing_local_snapshot_raises(settings: Settings, tmp_path: Path) -> None:
    """snapshot_source='local' with non-existent path → clear error."""
    settings.snapshot_source = "local"
    settings.snapshot_path = tmp_path / "does_not_exist.parquet"
    client = AnalyticsClient(settings)
    with pytest.raises(AnalyticsError, match="존재하지 않습니다"):
        client.query("SELECT 1 FROM {source} LIMIT 1", [])


def test_r2_without_credentials_raises(settings: Settings) -> None:
    """snapshot_source='r2' but R2_BUCKET missing → clear error, no leakage."""
    settings.snapshot_source = "r2"
    settings.r2_bucket = None
    client = AnalyticsClient(settings)
    with pytest.raises(AnalyticsError, match="R2_BUCKET"):
        client.query("SELECT 1 FROM {source} LIMIT 1", [])


def test_unknown_source_raises(settings: Settings) -> None:
    """Typo in snapshot_source → clear error listing valid values."""
    settings.snapshot_source = "redis"
    client = AnalyticsClient(settings)
    with pytest.raises(AnalyticsError, match=r"local|r2"):
        client.query("SELECT 1 FROM {source} LIMIT 1", [])


def test_redact_masks_known_secrets(settings: Settings) -> None:
    """_redact replaces R2 credential values with '***'."""
    settings.r2_secret_access_key = SecretStr("super-secret-value-12345")
    client = AnalyticsClient(settings)
    scrubbed = client._redact("error contains super-secret-value-12345 inline")
    assert "super-secret-value-12345" not in scrubbed
    assert "***" in scrubbed


def test_close_is_idempotent(analytics: AnalyticsClient) -> None:
    """close() twice should not raise — important for lifespan teardown."""
    analytics.close()
    analytics.close()  # second call is a no-op
