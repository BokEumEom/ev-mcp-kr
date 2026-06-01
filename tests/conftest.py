from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import duckdb
import pytest

from ev_mcp.analytics import AnalyticsClient
from ev_mcp.cache import build_caches
from ev_mcp.client import EvChargerClient
from ev_mcp.context import ToolContext
from ev_mcp.settings import Settings
from ev_mcp.store import ChargerStore


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    """Isolated Settings instance — never reads a developer's real .env / shell key.

    db_path is forced to :memory: so build_server() in tests doesn't touch the
    developer's data/chargers.db. snapshot_dir is forced under tmp_path so a sync
    smoke test never writes into the real data/snapshots/ (which would pollute the
    analytics v_latest view).
    """
    monkeypatch.setenv("SERVICE_KEY", "TEST_KEY_NOT_REAL")
    monkeypatch.delenv("VWORLD_KEY", raising=False)
    monkeypatch.setenv("DB_PATH", ":memory:")
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def analytics_snapshot_dir(tmp_path: Path) -> Path:
    """다중 날짜 스냅샷 Parquet 디렉터리 픽스처.

    2개 스냅샷을 만든다:
    - 2026-05-20 (older): ME=180, EV=150, KM=120, TINY=50
    - 2026-05-22 (latest): ME=200, EV=150, KM=120, TINY=50

    latest 스냅샷이 기존 운영자 분석 테스트의 기대값(ME=200 등)을 유지하고,
    older 스냅샷이 v_all / snapshot_diff 테스트에 두 번째 날짜를 제공한다.
    """
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    conn = duckdb.connect(":memory:")
    try:
        def build(date: str, me_total: int) -> None:
            rows: list[tuple[Any, ...]] = []

            def gen(busi_id: str, busi_nm: str, total: int, downtime: int,
                    unmonitored: int, zcode: str, zscode: str) -> None:
                for i in range(total):
                    if i < downtime:
                        stat = "4"
                    elif i < downtime + unmonitored:
                        stat = "9"
                    elif i < downtime + unmonitored + 5:
                        stat = "2"
                    else:
                        stat = "3"
                    ctype = "04" if i % 2 == 0 else "02"
                    rows.append((
                        f"{busi_id}-S{i:04d}", f"{busi_id}-C{i:04d}",
                        busi_id, busi_nm, stat, ctype, zcode, zscode, "N",
                        date, f"{date}T03:00:00+00:00", 0,
                    ))

            gen("ME", "환경부", me_total, 10, 15, "11", "11680")
            gen("EV", "에버온", 150, 60, 0, "11", "11680")
            gen("KM", "카카오", 120, 30, 0, "41", "41460")
            gen("TINY", "소형운영자", 50, 5, 0, "41", "41460")
            rows.append((
                "DEAD-S", "DEAD-C", "ME", "환경부", "4", "04",
                "11", "11680", "Y", date, f"{date}T03:00:00+00:00", 0,
            ))
            conn.execute("DROP TABLE IF EXISTS t")
            conn.execute(
                """
                CREATE TABLE t (
                    stat_id VARCHAR, chger_id VARCHAR, busi_id VARCHAR,
                    busi_nm VARCHAR, stat VARCHAR, chger_type VARCHAR,
                    zcode VARCHAR, zscode VARCHAR, del_yn VARCHAR,
                    snapshot_date DATE, synced_at VARCHAR, row_count INTEGER
                )
                """
            )
            conn.executemany(
                "INSERT INTO t VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
            )
            out = snap_dir / f"chargers_{date}.parquet"
            conn.execute(f"COPY t TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")

        build("2026-05-20", me_total=180)
        build("2026-05-22", me_total=200)
    finally:
        conn.close()
    return snap_dir


@pytest.fixture
def analytics(settings: Settings, analytics_snapshot_dir: Path) -> AnalyticsClient:
    """AnalyticsClient pointed at the fixture snapshot directory."""
    settings.snapshot_source = "local"
    settings.snapshot_dir = analytics_snapshot_dir
    return AnalyticsClient(settings)


@pytest.fixture
async def ctx(
    settings: Settings,
    analytics: AnalyticsClient,
) -> AsyncIterator[ToolContext]:
    """ToolContext fixture used by tool-level tests.

    Each test gets a fresh in-memory SQLite store so tests don't bleed state.
    """
    store = ChargerStore(":memory:")
    try:
        async with EvChargerClient(settings) as client:
            yield ToolContext(
                settings=settings,
                client=client,
                store=store,
                caches=build_caches(settings),
                analytics=analytics,
            )
    finally:
        store.close()
        analytics.close()


@pytest.fixture
def analytics_single_snapshot_dir(tmp_path: Path) -> Path:
    """스냅샷 1개뿐인 디렉터리 — 시계열 툴의 부족-데이터 엣지 검증용."""
    snap_dir = tmp_path / "single"
    snap_dir.mkdir()
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(
            """
            CREATE TABLE t (
                stat_id VARCHAR, chger_id VARCHAR, busi_id VARCHAR,
                busi_nm VARCHAR, stat VARCHAR, chger_type VARCHAR,
                zcode VARCHAR, zscode VARCHAR, del_yn VARCHAR,
                snapshot_date DATE, synced_at VARCHAR, row_count INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO t VALUES "
            "('S1','C1','ME','환경부','2','04','11','11680','N',"
            "DATE '2026-05-22','2026-05-22T03:00:00+00:00',1)"
        )
        out = snap_dir / "chargers_2026-05-22.parquet"
        conn.execute(f"COPY t TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        conn.close()
    return snap_dir


@pytest.fixture
async def ctx_single_snapshot(
    settings: Settings,
    analytics_single_snapshot_dir: Path,
) -> AsyncIterator[ToolContext]:
    """ToolContext whose analytics points at a single-snapshot directory."""
    settings.snapshot_source = "local"
    settings.snapshot_dir = analytics_single_snapshot_dir
    analytics = AnalyticsClient(settings)
    store = ChargerStore(":memory:")
    try:
        async with EvChargerClient(settings) as client:
            yield ToolContext(
                settings=settings, client=client, store=store,
                caches=build_caches(settings), analytics=analytics,
            )
    finally:
        store.close()
        analytics.close()


@pytest.fixture
async def ctx_empty_snapshot(
    settings: Settings,
    tmp_path: Path,
) -> AsyncIterator[ToolContext]:
    """ToolContext whose analytics points at an empty snapshot directory."""
    empty = tmp_path / "empty_snaps"
    empty.mkdir()
    settings.snapshot_source = "local"
    settings.snapshot_dir = empty
    analytics = AnalyticsClient(settings)
    store = ChargerStore(":memory:")
    try:
        async with EvChargerClient(settings) as client:
            yield ToolContext(
                settings=settings, client=client, store=store,
                caches=build_caches(settings), analytics=analytics,
            )
    finally:
        store.close()
        analytics.close()
