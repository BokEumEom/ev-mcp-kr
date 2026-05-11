from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import duckdb
import pytest

from ev_mcp.analytics import AnalyticsClient
from ev_mcp.cache import build_caches
from ev_mcp.client import EvChargerClient
from ev_mcp.context import ToolContext
from ev_mcp.settings import Settings
from ev_mcp.store import ChargerStore


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Isolated Settings instance — never reads a developer's real .env / shell key.

    db_path is forced to :memory: so build_server() in tests doesn't touch the
    developer's data/chargers.db.
    """
    monkeypatch.setenv("SERVICE_KEY", "TEST_KEY_NOT_REAL")
    monkeypatch.delenv("VWORLD_KEY", raising=False)
    monkeypatch.setenv("DB_PATH", ":memory:")
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def analytics_snapshot(tmp_path: Path) -> Path:
    """Build a tiny Parquet fixture for analytics tests.

    Schema mirrors the production snapshot (subset of columns used by analytics
    queries). 4 operators x 3 regions x varied stat/chger_type → enough to
    exercise GROUP BY semantics without depending on data/chargers.db.
    """
    path = tmp_path / "snapshot.parquet"
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(
            """
            CREATE TABLE chargers (
                stat_id     VARCHAR,
                chger_id    VARCHAR,
                busi_id     VARCHAR,
                busi_nm     VARCHAR,
                stat        VARCHAR,
                chger_type  VARCHAR,
                zcode       VARCHAR,
                zscode      VARCHAR,
                del_yn      VARCHAR
            )
            """
        )
        # ME=환경부 (200건, 비가동 10건=5%, unmonitored 15건),
        # EV=에버온 (150건, 비가동 60건=40%),
        # KM=카카오 (120건, 비가동 30건=25%),
        # TINY=소형 (50건, min_chargers=100 으로 제외)
        rows: list[tuple[str, str, str, str, str, str, str, str, str]] = []

        def gen(
            busi_id: str,
            busi_nm: str,
            total: int,
            downtime: int,
            unmonitored: int,
            zcode: str,
            zscode: str,
        ) -> None:
            for i in range(total):
                if i < downtime:
                    stat = "4"  # 비가동 (운영중지)
                elif i < downtime + unmonitored:
                    stat = "9"  # 모니터링 부재 (상태미확인)
                elif i < downtime + unmonitored + 5:
                    stat = "2"  # 충전대기 (사용 가능)
                else:
                    stat = "3"  # 충전중
                ctype = "04" if i % 2 == 0 else "02"  # half DC, half AC
                rows.append((
                    f"{busi_id}-S{i:04d}", f"{busi_id}-C{i:04d}",
                    busi_id, busi_nm, stat, ctype, zcode, zscode, "N",
                ))

        gen("ME", "환경부", 200, 10, 15, "11", "11680")
        gen("EV", "에버온", 150, 60, 0, "11", "11680")
        gen("KM", "카카오", 120, 30, 0, "41", "41460")
        gen("TINY", "소형운영자", 50, 5, 0, "41", "41460")
        # del_yn='Y' row 도 1개 — WHERE 절 검증
        rows.append(("DEAD-S", "DEAD-C", "ME", "환경부", "4", "04", "11", "11680", "Y"))

        conn.executemany(
            "INSERT INTO chargers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute(f"COPY chargers TO '{path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        conn.close()
    return path


@pytest.fixture
def analytics(settings: Settings, analytics_snapshot: Path) -> AnalyticsClient:
    """AnalyticsClient pointed at the tiny fixture Parquet."""
    settings.snapshot_source = "local"
    settings.snapshot_path = analytics_snapshot
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
