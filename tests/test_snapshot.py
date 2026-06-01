"""Unit tests for snapshot export (Phase 11)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

from ev_mcp.models import ChargerInfo
from ev_mcp.snapshot import write_snapshot
from ev_mcp.store import open_store


def _row(stat_id: str, chger_id: str = "01", stat: str = "2") -> ChargerInfo:
    payload: dict[str, Any] = {
        "statNm": f"station-{stat_id}", "statId": stat_id, "chgerId": chger_id,
        "chgerType": "04", "addr": "테스트 주소", "addrDetail": "",
        "lat": "37.5", "lng": "127.0", "useTime": "24시간",
        "busiId": "ME", "bnm": "환경부", "busiNm": "환경부", "busiCall": "",
        "stat": stat, "statUpdDt": "", "lastTsdt": "", "lastTedt": "", "nowTsdt": "",
        "powerType": "", "output": "50", "method": "단독",
        "zcode": "11", "zscode": "11680", "kind": "", "kindDetail": "",
        "parkingFree": "", "note": "", "limitYn": "N", "limitDetail": "",
        "delYn": "N", "delDetail": "", "trafficYn": "",
        "year": "", "floorNum": "", "floorType": "",
    }
    return ChargerInfo.model_validate(payload)


def _seed_store(db_path: Path, *, synced_at: str, rows: int = 3) -> None:
    store = open_store(db_path)
    try:
        store.seed_for_testing([_row(f"S{i:03d}") for i in range(rows)])
        store.set_state("last_synced_at", synced_at)
    finally:
        store.close()


def test_write_snapshot_creates_parquet_with_extra_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "chargers.db"
    snap_dir = tmp_path / "snapshots"
    _seed_store(db_path, synced_at=datetime(2026, 5, 22, 3, 0, tzinfo=UTC).isoformat(), rows=5)

    out = write_snapshot(db_path, snap_dir, force=False)

    assert out is not None
    assert out.exists()
    conn = duckdb.connect(":memory:")
    try:
        cols = {r[0] for r in conn.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{out}')"
        ).fetchall()}
        assert {"snapshot_date", "synced_at", "row_count"} <= cols
        row = conn.execute(
            f"SELECT COUNT(*), ANY_VALUE(row_count) FROM read_parquet('{out}')"
        ).fetchone()
        assert row is not None
        n, rc = row
        assert n == 5
        assert rc == 5
    finally:
        conn.close()


def test_write_snapshot_skips_when_synced_at_unchanged(tmp_path: Path) -> None:
    db_path = tmp_path / "chargers.db"
    snap_dir = tmp_path / "snapshots"
    synced = datetime(2026, 5, 22, 3, 0, tzinfo=UTC).isoformat()
    _seed_store(db_path, synced_at=synced)

    first = write_snapshot(db_path, snap_dir, force=False)
    assert first is not None
    second = write_snapshot(db_path, snap_dir, force=False)
    assert second is None  # synced_at 동일 → 스킵


def test_write_snapshot_force_overrides_skip(tmp_path: Path) -> None:
    db_path = tmp_path / "chargers.db"
    snap_dir = tmp_path / "snapshots"
    synced = datetime(2026, 5, 22, 3, 0, tzinfo=UTC).isoformat()
    _seed_store(db_path, synced_at=synced)

    write_snapshot(db_path, snap_dir, force=False)
    forced = write_snapshot(db_path, snap_dir, force=True)
    assert forced is not None  # --force → synced_at 동일해도 기록


def test_write_snapshot_raises_for_unsynced_store(tmp_path: Path) -> None:
    db_path = tmp_path / "chargers.db"
    store = open_store(db_path)  # 스키마만 생성, last_synced_at 은 NULL
    store.close()
    with pytest.raises(RuntimeError, match="ev-mcp-sync"):
        write_snapshot(db_path, tmp_path / "snapshots")


def test_write_snapshot_raises_for_empty_store(tmp_path: Path) -> None:
    """synced_at 은 있지만 충전기가 0건 → 빈 Parquet 을 만들지 않고 RuntimeError.

    실 사고(2026-06-01): 빈 store 에서 0행 스냅샷(874B)이 생성돼, snapshot_date 가
    더 최신이라 v_latest 가 그걸 골라 analytics/web 이 빈 데이터를 봄. 그 재발 방지.
    """
    db_path = tmp_path / "chargers.db"
    snap_dir = tmp_path / "snapshots"
    store = open_store(db_path)
    try:
        store.set_state("last_synced_at", datetime(2026, 6, 1, 3, 0, tzinfo=UTC).isoformat())
    finally:
        store.close()
    with pytest.raises(RuntimeError, match="0건"):
        write_snapshot(db_path, snap_dir)
    # 빈 Parquet 이 디렉터리에 남으면 안 됨
    assert not list(snap_dir.glob("*.parquet")) if snap_dir.exists() else True
