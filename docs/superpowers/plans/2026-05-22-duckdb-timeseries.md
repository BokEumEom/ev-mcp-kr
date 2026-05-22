# DuckDB 시계열 분석 기반 (Phase 11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 날짜별 충전기 스냅샷을 로컬에 축적하고, DuckDB analytics 레이어가 다중 스냅샷을 다루게 하여, 첫 시계열 MCP 툴 2개로 시계열 분석 파이프라인을 end-to-end 구축한다.

**Architecture:** `ev-mcp-snapshot` 콘솔이 SQLite store(`data/chargers.db`)를 날짜별 Parquet(`data/snapshots/chargers_YYYY-MM-DD.parquet`)으로 export한다. 각 Parquet에 `snapshot_date`·`synced_at`·`row_count` 컬럼을 임베드. `analytics.py`는 `{source}` placeholder 대신 in-memory DuckDB conn에 `v_all`·`v_latest` named view를 생성한다. 기존 툴은 `v_latest`(최신 스냅샷), 새 시계열 툴은 `v_all`(전체 관측열)을 조회.

**Tech Stack:** Python 3.12+, DuckDB (sqlite extension + read_parquet), Pydantic, FastMCP, pytest. mypy strict, ruff.

**참조 spec:** `docs/superpowers/specs/2026-05-22-duckdb-timeseries-design.md`

---

## File Structure

**신규 파일:**
- `src/ev_mcp/snapshot.py` — 스냅샷 export 로직 + `ev-mcp-snapshot` CLI. `write_snapshot()` 함수 + `main()`.
- `src/ev_mcp/tools/_analytics_shared.py` — 분석 툴 공유 상수 (`DC_CODES`).
- `src/ev_mcp/tools/analytics_snapshot_diff.py` — `snapshot_diff` 툴.
- `src/ev_mcp/tools/analytics_inventory_trend.py` — `inventory_trend` 툴.
- `tests/test_snapshot.py` — 스냅샷 export 테스트.
- `tests/test_analytics_snapshot_diff.py` — `snapshot_diff` 툴 테스트.
- `tests/test_analytics_inventory_trend.py` — `inventory_trend` 툴 테스트.

**수정 파일:**
- `src/ev_mcp/settings.py` — `snapshot_dir` 필드 추가.
- `src/ev_mcp/analytics.py` — view 레이어 전환, `{source}` 제거.
- `src/ev_mcp/domain.py` — `SnapshotDiff`·`InventoryTrendRow` 모델.
- `src/ev_mcp/tools/analytics_operator_health.py` — `FROM {source}` → `FROM v_latest`.
- `src/ev_mcp/tools/analytics_regional_density.py` — `FROM {source}` → `FROM v_latest`, `DC_CODES`를 `_analytics_shared`에서 import.
- `src/ev_mcp/server.py` — 툴 2개 등록.
- `src/ev_mcp/sync.py` — `--snapshot/--no-snapshot` 플래그.
- `tests/conftest.py` — `analytics_snapshot` → `analytics_snapshot_dir` 디렉터리 픽스처로 전환.
- `tests/test_analytics.py` — view 레이어에 맞게 재작성.
- `pyproject.toml` — `ev-mcp-snapshot` 콘솔 엔트리 (의존성 추가 아님).
- `.gitignore` — `data/snapshots/`.
- `docs/PHASE11.md` — Phase 보고서.

---

## Task 1: 스냅샷 export 모듈 (`snapshot.py`)

**Files:**
- Create: `src/ev_mcp/snapshot.py`
- Test: `tests/test_snapshot.py`

배경: `ChargerStore`의 PK는 `(stat_id, chger_id)`. `store.last_synced_at()`는 `datetime | None` 반환 (sync_state 테이블의 `last_synced_at` 키, ISO UTC). `store.total_count()`는 `int`. `store.seed_for_testing(rows)`로 테스트 시드 가능.

- [ ] **Step 1: 테스트 파일 작성**

`tests/test_snapshot.py`:

```python
"""Unit tests for snapshot export (Phase 11)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

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
        n, rc = conn.execute(
            f"SELECT COUNT(*), ANY_VALUE(row_count) FROM read_parquet('{out}')"
        ).fetchone()
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_snapshot.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ev_mcp.snapshot'`

- [ ] **Step 3: `snapshot.py` 구현**

`src/ev_mcp/snapshot.py`:

```python
"""ev-mcp-snapshot — SQLite store → 날짜별 Parquet 스냅샷 (Phase 11).

시계열 분석의 입력 데이터를 만든다. SQLite store 는 upsert 라 마지막 sync 시점의
상태만 담으므로, 스냅샷은 "일별 덤프" 가 아니라 "sync 관측" 이다 — synced_at 이
직전 스냅샷과 같으면 기록을 스킵해 중복 파일을 막는다.

임베드 컬럼
-----------
- snapshot_date (DATE)   — KST export 일자
- synced_at     (VARCHAR)— store.last_synced_at() 의 ISO 문자열 (데이터 신선도)
- row_count     (INTEGER)— export 시점 충전기 수
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from .store import open_store

KST = ZoneInfo("Asia/Seoul")
DEFAULT_DB_PATH = Path("data/chargers.db")
DEFAULT_SNAPSHOT_DIR = Path("data/snapshots")
SNAPSHOT_GLOB = "chargers_*.parquet"


def _latest_snapshot_synced_at(snapshot_dir: Path) -> str | None:
    """디렉터리의 가장 최근 스냅샷에 임베드된 synced_at 값. 스냅샷 없으면 None."""
    if not snapshot_dir.exists():
        return None
    files = sorted(snapshot_dir.glob(SNAPSHOT_GLOB))
    if not files:
        return None
    conn = duckdb.connect(":memory:")
    try:
        row = conn.execute(
            f"SELECT ANY_VALUE(synced_at) FROM read_parquet('{files[-1].resolve()}')"
        ).fetchone()
    finally:
        conn.close()
    return None if row is None or row[0] is None else str(row[0])


def write_snapshot(
    db_path: Path,
    snapshot_dir: Path,
    *,
    force: bool = False,
) -> Path | None:
    """현재 SQLite store 를 날짜별 Parquet 으로 export.

    Returns
    -------
    Path | None
        기록한 Parquet 경로. synced_at 이 직전 스냅샷과 동일해 스킵하면 None.
    """
    store = open_store(db_path)
    try:
        synced_at = store.last_synced_at()
        row_count = store.total_count()
    finally:
        store.close()

    if synced_at is None:
        raise RuntimeError(
            "store 가 한 번도 sync 되지 않았습니다 — 먼저 ev-mcp-sync 를 실행하세요"
        )
    synced_at_iso = synced_at.isoformat()

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    if not force and _latest_snapshot_synced_at(snapshot_dir) == synced_at_iso:
        return None

    kst_date = datetime.now(KST).date().isoformat()
    out_path = snapshot_dir / f"chargers_{kst_date}.parquet"

    conn = duckdb.connect(":memory:")
    try:
        conn.execute("INSTALL sqlite")
        conn.execute("LOAD sqlite")
        conn.execute(f"ATTACH '{db_path.resolve()}' AS sdb (TYPE sqlite, READ_ONLY)")
        conn.execute(
            f"""
            COPY (
                SELECT *,
                       DATE '{kst_date}' AS snapshot_date,
                       '{synced_at_iso}' AS synced_at,
                       {row_count} AS row_count
                FROM sdb.chargers
            ) TO '{out_path.resolve()}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    finally:
        conn.close()
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(prog="ev-mcp-snapshot", description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument(
        "--force",
        action="store_true",
        help="synced_at 이 직전 스냅샷과 같아도 강제 기록",
    )
    args = parser.parse_args()
    result = write_snapshot(args.db, args.snapshot_dir, force=args.force)
    if result is None:
        print("스냅샷 스킵 — 마지막 sync 이후 변경 없음 (--force 로 강제 가능)")
    else:
        print(f"스냅샷 기록: {result}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_snapshot.py -q`
Expected: PASS — 3 passed

- [ ] **Step 5: 커밋**

```bash
git add src/ev_mcp/snapshot.py tests/test_snapshot.py
git commit -m "feat(snapshot): SQLite store → 날짜별 Parquet export 모듈"
```

---

## Task 2: `settings.py` 에 `snapshot_dir` 추가

**Files:**
- Modify: `src/ev_mcp/settings.py:29-32`

- [ ] **Step 1: `snapshot_dir` 필드 추가**

`src/ev_mcp/settings.py` 의 `snapshot_path` 필드 **아래에** 추가 (`snapshot_path`는 R2 외 호환 위해 일단 남겨둠 — Task 3 에서 로컬 경로는 `snapshot_dir`로 대체됨):

```python
    snapshot_dir: Path = Field(
        default=Path("data/snapshots"),
        description="날짜별 Parquet 스냅샷 디렉터리 (snapshot_source='local' 일 때 glob 대상)",
    )
```

- [ ] **Step 2: import 확인**

`Path` 는 이미 import 됨 (`from pathlib import Path`). 추가 import 불필요.

- [ ] **Step 3: 타입체크**

Run: `python -m mypy src/ev_mcp/settings.py`
Expected: Success — no issues

- [ ] **Step 4: 커밋**

```bash
git add src/ev_mcp/settings.py
git commit -m "feat(settings): snapshot_dir 추가 — 다중 스냅샷 glob 진입점"
```

---

## Task 3: analytics 레이어 view 전환

이 Task 는 `analytics.py` 의 `{source}` placeholder 를 named view (`v_all`·`v_latest`) 로 교체한다. 기존 analytics 테스트·conftest 픽스처·기존 툴 2개가 모두 함께 바뀌므로 한 Task 에서 일괄 처리한다.

**Files:**
- Modify: `src/ev_mcp/analytics.py`
- Modify: `tests/conftest.py:30-108`
- Modify: `tests/test_analytics.py` (전체 재작성)
- Modify: `src/ev_mcp/tools/analytics_operator_health.py:48` (`FROM {source}` → `FROM v_latest`)
- Modify: `src/ev_mcp/tools/analytics_regional_density.py:42,57` (`FROM {source}` → `FROM v_latest`)

- [ ] **Step 1: conftest 픽스처를 디렉터리 픽스처로 재작성**

`tests/conftest.py` 의 `analytics_snapshot` 픽스처(30~100행)와 `analytics` 픽스처(103~108행)를 아래로 **교체**:

```python
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
```

`Any` 가 conftest 에 import 안 되어 있으면 상단에 `from typing import Any` 추가.

- [ ] **Step 2: `test_analytics.py` 재작성**

`tests/test_analytics.py` 전체를 아래로 **교체**:

```python
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
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python -m pytest tests/test_analytics.py -q`
Expected: FAIL — `analytics.query` 가 `{source}` placeholder 를 요구하거나 view 가 없어 실패

- [ ] **Step 4: `analytics.py` view 레이어 구현**

`src/ev_mcp/analytics.py` 에서 `_source_expr` 메서드(47~75행)를 **삭제**하고, `_ensure_connected`(81~88행)·`_configure_r2`·`query` 를 아래로 교체. 클래스의 다른 부분(`__init__`, `close`, `_collect_secrets`, `_redact`, `_suppress`, `build_analytics_client`)은 그대로 둔다.

`SNAPSHOT_GLOB` 상수를 모듈 상단 import 아래에 추가:

```python
from .snapshot import SNAPSHOT_GLOB
```

`_ensure_connected` 교체:

```python
    def _ensure_connected(self) -> Any:
        if self._conn is not None:
            return self._conn
        conn = duckdb.connect(":memory:")
        self._create_views(conn)
        self._conn = conn
        return conn

    def _create_views(self, conn: Any) -> None:
        """소스(local glob / R2 s3 glob)에 따라 v_all·v_latest view 생성.

        호출부 SQL 에 소스 문자열이 들어가지 않도록, read_parquet 호출은
        view 정의 단 한 곳에만 존재한다.
        """
        src = self._settings.snapshot_source.lower()
        if src == "local":
            snapshot_dir = self._settings.snapshot_dir
            files = (
                sorted(snapshot_dir.glob(SNAPSHOT_GLOB))
                if snapshot_dir.exists()
                else []
            )
            if not files:
                raise AnalyticsError(
                    f"스냅샷이 없습니다: {snapshot_dir}. "
                    "ev-mcp-sync 후 ev-mcp-snapshot 을 한 번 실행하세요."
                )
            glob_path = (snapshot_dir / SNAPSHOT_GLOB).resolve()
            source = f"read_parquet('{glob_path}')"
        elif src == "r2":
            bucket = self._settings.r2_bucket
            if not bucket:
                raise AnalyticsError(
                    "snapshot_source='r2' 인데 R2_BUCKET 이 설정되지 않았습니다. "
                    ".env 의 R2_* 필드를 채우거나 SNAPSHOT_SOURCE=local 로 두세요."
                )
            self._configure_r2(conn)
            source = f"read_parquet('s3://{bucket}/chargers_*.parquet')"
        else:
            raise AnalyticsError(
                f"알 수 없는 snapshot_source: '{src}'. 'local' 또는 'r2' 만 허용."
            )
        try:
            conn.execute(f"CREATE VIEW v_all AS SELECT * FROM {source}")
            conn.execute(
                "CREATE VIEW v_latest AS SELECT * FROM v_all "
                "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM v_all)"
            )
        except AnalyticsError:
            raise
        except Exception as e:
            raise AnalyticsError(self._redact(f"view 생성 실패: {e}")) from None
```

`query` 교체 (`{source}` 검증·치환 제거):

```python
    def query(
        self,
        sql: str,
        params: list[Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        """v_all / v_latest view 에 대한 SELECT 실행.

        호출부는 평범한 SQL 을 쓴다 — ``FROM v_latest`` (최신 스냅샷) 또는
        ``FROM v_all`` (전체 관측열). 소스 경로/자격증명은 view 정의에만 있다.
        """
        conn = self._ensure_connected()
        try:
            cursor = conn.execute(sql, params or [])
            return cast(list[tuple[Any, ...]], cursor.fetchall())
        except AnalyticsError:
            raise
        except Exception as e:
            raise AnalyticsError(
                self._redact(f"query failed: {type(e).__name__}: {e}")
            ) from None
```

`_configure_r2` 메서드는 기존 그대로 유지 (90~115행). 모듈 docstring 의 "ATTACH mode" 문단은 정확하므로 유지.

- [ ] **Step 5: 기존 툴 2개를 `v_latest` 로 전환**

`src/ev_mcp/tools/analytics_operator_health.py`: `_QUERY_TEMPLATE`(38~54행) 안의 `FROM {source}` 를 `FROM v_latest` 로 변경.

`src/ev_mcp/tools/analytics_regional_density.py`: `_QUERY_SIGUNGU`(34~47행)·`_QUERY_SIDO`(49~62행) 안의 `FROM {source}` 를 각각 `FROM v_latest` 로 변경. `regional_density` 함수의 `.format(..., source="{source}")` 호출(101~104행)에서 `source=` 인자를 제거 — 즉:

```python
    template = (_QUERY_SIGUNGU if group_by == "sigungu" else _QUERY_SIDO).format(
        dc_placeholders=dc_placeholders,
    )
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/test_analytics.py tests/test_analytics_operator_health.py tests/test_analytics_regional_density.py -q`
Expected: PASS — 기존 운영자/지역 툴 테스트 + 새 view 테스트 모두 green

(툴 테스트 파일명이 다르면 `python -m pytest tests/ -k "analytic" -q` 로 확인)

- [ ] **Step 7: 타입체크 + 린트**

Run: `python -m mypy src/ev_mcp/analytics.py && python -m ruff check src/ev_mcp/analytics.py src/ev_mcp/tools/`
Expected: 둘 다 통과

- [ ] **Step 8: 커밋**

```bash
git add src/ev_mcp/analytics.py tests/conftest.py tests/test_analytics.py \
        src/ev_mcp/tools/analytics_operator_health.py \
        src/ev_mcp/tools/analytics_regional_density.py
git commit -m "refactor(analytics): {source} placeholder → v_all/v_latest named view"
```

---

## Task 4: 도메인 모델 (`SnapshotDiff`, `InventoryTrendRow`)

**Files:**
- Modify: `src/ev_mcp/domain.py` (파일 끝에 추가)

- [ ] **Step 1: 모델 2개 추가**

`src/ev_mcp/domain.py` 파일 **맨 끝**에 추가:

```python
class SnapshotDiff(BaseModel):
    """snapshot_diff 의 결과 — 두 스냅샷 사이 변화 집계.

    스칼라 집계만 담는다 (508k 행 나열 금지 — 토큰 예산). from=이전 관측,
    to=이후 관측. synced_at 을 함께 노출해 "두 관측이 실은 동일 데이터" 인
    상황을 숨기지 않는다.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_date: str
    to_date: str
    from_synced_at: str
    to_synced_at: str
    appeared: int  # to 에만 있는 충전기 (신규)
    disappeared: int  # from 에만 있는 충전기 (제거)
    stat_changed: int  # 양쪽에 있으나 stat 코드가 바뀐 충전기
    net_change: int  # appeared - disappeared


class InventoryTrendRow(BaseModel):
    """inventory_trend 의 한 행 — 관측일별 인벤토리 스냅샷."""

    model_config = ConfigDict(populate_by_name=True)

    snapshot_date: str
    synced_at: str
    total_chargers: int
    dc_count: int  # 급속 (DC 차데모/콤보/NACS) 수
    available_count: int  # stat='2' 충전대기
    distinct_operators: int
    delta_total: int | None = None  # 직전 관측 대비 총 충전기 증감. 첫 행은 None
```

- [ ] **Step 2: 타입체크**

Run: `python -m mypy src/ev_mcp/domain.py`
Expected: Success

- [ ] **Step 3: 커밋**

```bash
git add src/ev_mcp/domain.py
git commit -m "feat(domain): SnapshotDiff·InventoryTrendRow 시계열 모델"
```

---

## Task 5: `snapshot_diff` 툴

**Files:**
- Create: `src/ev_mcp/tools/analytics_snapshot_diff.py`
- Test: `tests/test_analytics_snapshot_diff.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_analytics_snapshot_diff.py`:

```python
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
```

이 테스트는 `ctx_single_snapshot` 픽스처가 필요하다. `tests/conftest.py` 끝에 추가:

```python
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
                stat VARCHAR, chger_type VARCHAR, del_yn VARCHAR,
                snapshot_date DATE, synced_at VARCHAR, row_count INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO t VALUES "
            "('S1','C1','ME','2','04','N',DATE '2026-05-22','2026-05-22T03:00:00+00:00',1)"
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_analytics_snapshot_diff.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ev_mcp.tools.analytics_snapshot_diff'`

- [ ] **Step 3: `snapshot_diff` 툴 구현**

`src/ev_mcp/tools/analytics_snapshot_diff.py`:

```python
"""Tool: snapshot_diff — 두 스냅샷 날짜 사이 충전기 변화 집계.

Phase 11 (시계열 분석 기반). v_all 위에서 from/to 두 관측을 충전기 고유키
(stat_id + chger_id)로 full outer join 한다.
"""

from __future__ import annotations

from ..context import ToolContext
from ..domain import SnapshotDiff

_OBSERVATIONS_QUERY = """
    SELECT snapshot_date, ANY_VALUE(synced_at) AS synced_at
    FROM v_all
    GROUP BY snapshot_date
    ORDER BY snapshot_date
"""

_DIFF_QUERY = """
    WITH f AS (
        SELECT stat_id, chger_id, stat FROM v_all WHERE snapshot_date = ?
    ),
    t AS (
        SELECT stat_id, chger_id, stat FROM v_all WHERE snapshot_date = ?
    )
    SELECT
        COUNT(*) FILTER (WHERE f.chger_id IS NULL) AS appeared,
        COUNT(*) FILTER (WHERE t.chger_id IS NULL) AS disappeared,
        COUNT(*) FILTER (
            WHERE f.chger_id IS NOT NULL AND t.chger_id IS NOT NULL
              AND f.stat IS DISTINCT FROM t.stat
        ) AS stat_changed
    FROM f
    FULL OUTER JOIN t ON f.stat_id = t.stat_id AND f.chger_id = t.chger_id
"""


def snapshot_diff(
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    ctx: ToolContext,
) -> SnapshotDiff:
    """두 스냅샷 날짜 사이 충전기 변화 — 신규/제거/상태변경 집계.

    Phase 11 의 시계열 분석 툴. Parquet 스냅샷 관측열(v_all) 위에서 from/to
    두 날짜를 충전기 고유키로 비교한다.

    Parameters
    ----------
    from_date:
        비교 시작 날짜 ("YYYY-MM-DD"). None 이면 직전(끝에서 두 번째) 관측.
    to_date:
        비교 끝 날짜 ("YYYY-MM-DD"). None 이면 최신 관측.

    Returns
    -------
    SnapshotDiff
        appeared(신규)·disappeared(제거)·stat_changed(상태변경)·net_change.
        각 관측의 synced_at 도 포함 — 두 관측이 같은 synced_at 이면 "변화 0"
        은 데이터가 안 바뀐 것일 뿐임을 알 수 있다.

    예시
    ----
    "지난 스냅샷 대비 충전기가 얼마나 늘었어?"
        → 인자 없이 호출 (최근 2개 관측 자동 비교).

    "5월 20일과 22일 사이 변화"
        → from_date="2026-05-20", to_date="2026-05-22"
    """
    observations = ctx.analytics.query(_OBSERVATIONS_QUERY, [])
    if len(observations) < 2:
        raise ValueError(
            f"비교하려면 스냅샷이 2개 이상 필요합니다 (현재 {len(observations)}개). "
            "ev-mcp-snapshot 을 며칠에 걸쳐 실행해 관측을 쌓으세요."
        )
    synced_by_date = {str(r[0]): str(r[1]) for r in observations}
    dates = sorted(synced_by_date)

    resolved_from = from_date if from_date is not None else dates[-2]
    resolved_to = to_date if to_date is not None else dates[-1]
    for label, d in (("from_date", resolved_from), ("to_date", resolved_to)):
        if d not in synced_by_date:
            raise ValueError(
                f"{label}={d!r} 에 해당하는 스냅샷이 없습니다. "
                f"사용 가능한 날짜: {dates}"
            )

    row = ctx.analytics.query(_DIFF_QUERY, [resolved_from, resolved_to])[0]
    appeared, disappeared, stat_changed = int(row[0]), int(row[1]), int(row[2])
    return SnapshotDiff(
        from_date=resolved_from,
        to_date=resolved_to,
        from_synced_at=synced_by_date[resolved_from],
        to_synced_at=synced_by_date[resolved_to],
        appeared=appeared,
        disappeared=disappeared,
        stat_changed=stat_changed,
        net_change=appeared - disappeared,
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_analytics_snapshot_diff.py -q`
Expected: PASS — 3 passed

- [ ] **Step 5: 타입체크 + 린트**

Run: `python -m mypy src/ev_mcp/tools/analytics_snapshot_diff.py && python -m ruff check src/ev_mcp/tools/analytics_snapshot_diff.py`
Expected: 둘 다 통과

- [ ] **Step 6: 커밋**

```bash
git add src/ev_mcp/tools/analytics_snapshot_diff.py \
        tests/test_analytics_snapshot_diff.py tests/conftest.py
git commit -m "feat(tools): snapshot_diff — 두 스냅샷 사이 충전기 변화 집계"
```

---

## Task 6: `inventory_trend` 툴 + DC_CODES 공유 상수

**Files:**
- Create: `src/ev_mcp/tools/_analytics_shared.py`
- Modify: `src/ev_mcp/tools/analytics_regional_density.py:31` (`DC_CODES` import 로 대체)
- Create: `src/ev_mcp/tools/analytics_inventory_trend.py`
- Test: `tests/test_analytics_inventory_trend.py`

- [ ] **Step 1: 공유 상수 모듈 생성**

`src/ev_mcp/tools/_analytics_shared.py`:

```python
"""분석 툴 공유 상수 — 여러 툴이 동일하게 쓰는 코드 집합."""

from __future__ import annotations

# 급속 충전기로 분류하는 chger_type 코드 (DC 차데모/콤보 계열 + NACS).
# "02" AC완속·"07" AC3상 은 완속이라 제외. 상세는 regional_density docstring 참고.
DC_CODES: tuple[str, ...] = ("01", "03", "04", "05", "06", "08", "09", "10")
```

- [ ] **Step 2: `regional_density` 가 공유 상수를 쓰도록 변경**

`src/ev_mcp/tools/analytics_regional_density.py` 31행의 로컬 `DC_CODES = (...)` 정의를 삭제하고, import 블록(23~25행 근처)에 추가:

```python
from ._analytics_shared import DC_CODES
```

- [ ] **Step 3: `regional_density` 회귀 확인**

Run: `python -m pytest tests/test_analytics_regional_density.py -q`
Expected: PASS — 기존 테스트 그대로 green (테스트 파일명이 다르면 `-k regional` 사용)

- [ ] **Step 4: `inventory_trend` 테스트 작성**

`tests/test_analytics_inventory_trend.py`:

```python
"""Unit tests for the inventory_trend tool (Phase 11)."""

from __future__ import annotations

import pytest

from ev_mcp.analytics import AnalyticsError
from ev_mcp.tools.analytics_inventory_trend import inventory_trend


def test_trend_returns_row_per_observation(ctx) -> None:  # type: ignore[no-untyped-def]
    """관측일별 1행 — 픽스처는 2개 스냅샷.

    오름차순 정렬, 첫 행 delta_total=None, 둘째 행은 직전 대비 증감.
    older 총계 ME180+EV150+KM120+TINY50 +DEAD1 = 501,
    latest ME200+... = 521 → delta_total = 20.
    """
    rows = inventory_trend(ctx=ctx)
    assert len(rows) == 2
    assert rows[0].snapshot_date == "2026-05-20"
    assert rows[0].delta_total is None
    assert rows[1].snapshot_date == "2026-05-22"
    assert rows[1].delta_total == rows[1].total_chargers - rows[0].total_chargers
    assert rows[1].total_chargers - rows[0].total_chargers == 20


def test_trend_single_snapshot_has_null_delta(ctx_single_snapshot) -> None:  # type: ignore[no-untyped-def]
    """스냅샷 1개 → 1행, delta_total None."""
    rows = inventory_trend(ctx=ctx_single_snapshot)
    assert len(rows) == 1
    assert rows[0].delta_total is None


def test_trend_empty_dir_raises(ctx_empty_snapshot) -> None:  # type: ignore[no-untyped-def]
    """스냅샷 0개 → AnalyticsError (레이어에서)."""
    with pytest.raises(AnalyticsError, match="스냅샷"):
        inventory_trend(ctx=ctx_empty_snapshot)
```

`ctx_empty_snapshot` 픽스처를 `tests/conftest.py` 끝에 추가:

```python
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
```

- [ ] **Step 5: 테스트 실패 확인**

Run: `python -m pytest tests/test_analytics_inventory_trend.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ev_mcp.tools.analytics_inventory_trend'`

- [ ] **Step 6: `inventory_trend` 툴 구현**

`src/ev_mcp/tools/analytics_inventory_trend.py`:

```python
"""Tool: inventory_trend — 관측일별 충전기 인벤토리 곡선.

Phase 11 (시계열 분석 기반). v_all 위에서 snapshot_date 별로 집계.
delta_total(직전 관측 대비 증감)은 Python 에서 계산한다.
"""

from __future__ import annotations

from ..context import ToolContext
from ..domain import InventoryTrendRow
from ._analytics_shared import DC_CODES

DEFAULT_LIMIT = 30
MAX_LIMIT = 90
AVAILABLE_CODE = "2"

_QUERY_TEMPLATE = """
    SELECT
        CAST(snapshot_date AS VARCHAR) AS snapshot_date,
        ANY_VALUE(synced_at) AS synced_at,
        COUNT(*) AS total_chargers,
        SUM(CASE WHEN chger_type IN ({dc_placeholders}) THEN 1 ELSE 0 END) AS dc_count,
        SUM(CASE WHEN stat = ? THEN 1 ELSE 0 END) AS available_count,
        COUNT(DISTINCT busi_id) AS distinct_operators
    FROM v_all
    WHERE del_yn = 'N'
    GROUP BY snapshot_date
    ORDER BY snapshot_date DESC
    LIMIT ?
"""


def inventory_trend(
    *,
    limit: int = DEFAULT_LIMIT,
    ctx: ToolContext,
) -> list[InventoryTrendRow]:
    """관측일별 충전기 인벤토리 추세 — 총수/DC/가용/운영자 수 + 직전 대비 증감.

    Phase 11 의 시계열 분석 툴. Parquet 스냅샷 관측열(v_all) 위에서 집계.
    스냅샷은 불규칙 관측열이므로 날짜 간격이 일정하지 않을 수 있다. 각 행의
    synced_at 을 함께 보면 "추세"가 실제 데이터 변화인지 확인할 수 있다.

    Parameters
    ----------
    limit:
        반환할 최근 관측 수. 기본 30, 최대 90.

    Returns
    -------
    list[InventoryTrendRow]
        snapshot_date 오름차순. 첫 행 delta_total 은 None (직전 관측 없음).

    예시
    ----
    "충전기 수가 어떻게 늘고 있어?"
        → 인자 없이 호출.

    "최근 7개 관측만"
        → limit=7
    """
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit 은 1~{MAX_LIMIT} 사이여야 합니다 (받은 값: {limit})")

    dc_placeholders = ",".join(["?"] * len(DC_CODES))
    sql = _QUERY_TEMPLATE.format(dc_placeholders=dc_placeholders)
    rows = ctx.analytics.query(sql, [*DC_CODES, AVAILABLE_CODE, limit])

    # 쿼리는 DESC (최근 우선) 로 LIMIT 을 걸었으니, 오름차순으로 뒤집어 delta 계산.
    ordered = list(reversed(rows))
    result: list[InventoryTrendRow] = []
    prev_total: int | None = None
    for r in ordered:
        total = int(r[2])
        result.append(
            InventoryTrendRow(
                snapshot_date=str(r[0]),
                synced_at=str(r[1]),
                total_chargers=total,
                dc_count=int(r[3]),
                available_count=int(r[4]),
                distinct_operators=int(r[5]),
                delta_total=None if prev_total is None else total - prev_total,
            )
        )
        prev_total = total
    return result
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `python -m pytest tests/test_analytics_inventory_trend.py -q`
Expected: PASS — 3 passed

- [ ] **Step 8: 타입체크 + 린트**

Run: `python -m mypy src/ev_mcp/tools/ && python -m ruff check src/ev_mcp/tools/`
Expected: 둘 다 통과

- [ ] **Step 9: 커밋**

```bash
git add src/ev_mcp/tools/_analytics_shared.py \
        src/ev_mcp/tools/analytics_regional_density.py \
        src/ev_mcp/tools/analytics_inventory_trend.py \
        tests/test_analytics_inventory_trend.py tests/conftest.py
git commit -m "feat(tools): inventory_trend — 관측일별 인벤토리 추세 + DC_CODES 공유"
```

---

## Task 7: 서버에 툴 2개 등록

**Files:**
- Modify: `src/ev_mcp/server.py` (import 블록 + `_register_tools`)

배경: `server.py` 는 `_register_tools(mcp, ctx)` 안에서 각 툴을 `@mcp.tool(annotations=READ_ONLY)` 클로저로 감싼다. 기존 패턴(`analyze_operator_health`, `regional_density`, 343행 근처)을 따른다.

- [ ] **Step 1: import 추가**

`src/ev_mcp/server.py` 의 import 블록(55~56행, `analytics_operator_health`/`analytics_regional_density` import 옆)에 추가:

```python
from .tools.analytics_inventory_trend import inventory_trend as _inventory_trend
from .tools.analytics_snapshot_diff import snapshot_diff as _snapshot_diff
```

도메인 모델 import (`OperatorHealthRow`, `RegionalDensityRow` 가 import 되는 줄 근처)에 추가:

```python
from .domain import InventoryTrendRow, SnapshotDiff
```

(이미 `from .domain import ...` 줄이 있으면 거기에 두 이름을 합친다.)

- [ ] **Step 2: 툴 등록 추가**

`_register_tools` 안, `regional_density` 툴 정의(343행 `return _regional_density(...)`) **바로 다음**에 추가:

```python
    @mcp.tool(annotations=READ_ONLY)
    def snapshot_diff(
        *,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> SnapshotDiff:
        """두 스냅샷 날짜 사이 충전기 변화 — 신규/제거/상태변경 집계.

        Parquet 스냅샷 관측열 위에서 비교. 인자 없이 호출하면 최근 2개 관측을
        자동 비교한다. from_date/to_date 는 "YYYY-MM-DD". 결과의 synced_at 으로
        두 관측이 실제로 다른 데이터인지 확인 가능.

        "지난번 대비 충전기 얼마나 늘었어?" 같은 질문에 사용.
        """
        return _snapshot_diff(from_date=from_date, to_date=to_date, ctx=ctx)

    @mcp.tool(annotations=READ_ONLY)
    def inventory_trend(
        *,
        limit: int = 30,
    ) -> list[InventoryTrendRow]:
        """관측일별 충전기 인벤토리 추세 — 총수/DC/가용/운영자 수 + 증감.

        Parquet 스냅샷 관측열 위에서 snapshot_date 별 집계. 스냅샷은 불규칙
        관측열이라 날짜 간격이 일정하지 않을 수 있다. limit 기본 30, 최대 90.

        "충전기 수가 어떻게 늘고 있어?" 같은 질문에 사용.
        """
        return _inventory_trend(limit=limit, ctx=ctx)
```

- [ ] **Step 3: 서버 빌드 스모크 + 타입체크**

Run: `python -c "from ev_mcp.server import build_server; build_server() and print('ok')" && python -m mypy src/ev_mcp/server.py`
Expected: `ok` 출력 + mypy 통과

(`build_server()` 가 SERVICE_KEY 를 요구하면 `SERVICE_KEY=TEST python -c "..."` 로 실행)

- [ ] **Step 4: 커밋**

```bash
git add src/ev_mcp/server.py
git commit -m "feat(server): snapshot_diff·inventory_trend MCP 툴 등록"
```

---

## Task 8: `sync.py` 에 `--snapshot` 플래그

**Files:**
- Modify: `src/ev_mcp/sync.py` (`sync()` 함수 끝 + `main()` argparse)

배경: `sync()` 는 async, 마지막에 `store.set_state("last_synced_at", ...)` → `store.close()` 후 끝난다. 스냅샷은 sync 전체 패스 성공 완료 후에만 찍어야 한다(부분 동기화 상태 금지). `store.close()` 다음에 `write_snapshot` 을 호출한다 — `write_snapshot` 은 자체적으로 store 를 다시 연다.

- [ ] **Step 1: import 추가**

`src/ev_mcp/sync.py` import 블록에 추가:

```python
from .snapshot import DEFAULT_SNAPSHOT_DIR, write_snapshot
```

- [ ] **Step 2: `sync()` 시그니처 + 본문 수정**

`sync()` 함수 시그니처에 `snapshot: bool = True` 추가:

```python
async def sync(
    db_path: Path,
    page_size: int = DEFAULT_PAGE_SIZE,
    full: bool = False,
    snapshot: bool = True,
) -> None:
```

`sync()` 본문 맨 끝, `store.close()` **다음 줄**에 추가 (현재 `logger.info("sync_complete", ...)` 다음, `store.close()` 가 마지막 줄):

```python
    store.close()
    if snapshot:
        result = write_snapshot(db_path, DEFAULT_SNAPSHOT_DIR, force=False)
        if result is None:
            logger.info("snapshot_skipped", reason="synced_at_unchanged")
        else:
            logger.info("snapshot_written", path=str(result))
```

(기존 `store.close()` 줄이 이미 있으면 중복 추가하지 말고 그 뒤에 if 블록만 넣는다.)

- [ ] **Step 3: `main()` argparse 에 플래그 추가**

`main()` 의 argparse 블록, `--full` 인자 정의 다음에 추가:

```python
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="sync 완료 후 날짜별 Parquet 스냅샷을 찍지 않음 (기본은 찍음)",
    )
```

`asyncio.run(...)` 호출을 수정:

```python
    asyncio.run(
        sync(
            args.db,
            page_size=args.page_size,
            full=args.full,
            snapshot=not args.no_snapshot,
        )
    )
```

- [ ] **Step 4: 타입체크 + 린트**

Run: `python -m mypy src/ev_mcp/sync.py && python -m ruff check src/ev_mcp/sync.py`
Expected: 둘 다 통과

- [ ] **Step 5: 커밋**

```bash
git add src/ev_mcp/sync.py
git commit -m "feat(sync): --snapshot — sync 완료 후 날짜별 스냅샷 자동 기록"
```

---

## Task 9: 콘솔 엔트리 · gitignore · 전체 verify

**Files:**
- Modify: `pyproject.toml` (`[project.scripts]`)
- Modify: `.gitignore`

- [ ] **Step 1: `ev-mcp-snapshot` 콘솔 엔트리 추가**

`pyproject.toml` 의 `[project.scripts]` 블록에 추가 (의존성 추가 아님 — 스크립트 엔트리만):

```toml
[project.scripts]
ev-mcp = "ev_mcp.server:main"
ev-mcp-sync = "ev_mcp.sync:main"
ev-mcp-snapshot = "ev_mcp.snapshot:main"
```

- [ ] **Step 2: `.gitignore` 에 스냅샷 디렉터리 추가**

`.gitignore` 에 `data/` 관련 줄 근처에 추가:

```
data/snapshots/
```

(`data/` 가 통째로 ignore 되어 있으면 이 줄은 생략 가능 — `.gitignore` 를 먼저 확인하고, `data/` 가 없으면 추가.)

- [ ] **Step 3: 패키지 재설치 (콘솔 엔트리 반영)**

Run: `uv pip install -e ".[dev]"`
Expected: 설치 성공, `ev-mcp-snapshot` 명령 사용 가능

- [ ] **Step 4: 전체 verify**

Run: `python -m pytest -q && python -m ruff check . && python -m mypy src/`
Expected: 전부 green. 테스트 ~140건 (기존 123 + 신규: snapshot 3, snapshot_diff 3, inventory_trend 3, analytics view 7 재작성 ≈ +9 순증).

- [ ] **Step 5: `ev-mcp-snapshot` 스모크 (선택 — `data/chargers.db` 가 있을 때만)**

Run: `ev-mcp-snapshot --help`
Expected: argparse 도움말 출력 (`--db`, `--snapshot-dir`, `--force`)

- [ ] **Step 6: 커밋**

```bash
git add pyproject.toml .gitignore
git commit -m "chore: ev-mcp-snapshot 콘솔 엔트리 + data/snapshots gitignore"
```

---

## Task 10: Phase 11 보고서

**Files:**
- Create: `docs/PHASE11.md`

- [ ] **Step 1: `/phase-review 11` 실행 (code-reviewer 에이전트)**

CRITICAL/HIGH 이슈가 나오면 fix 후 `python -m pytest -q` 재확인.

- [ ] **Step 2: `docs/PHASE11.md` 작성**

`docs/PHASE10.md` 형식을 따라 작성. 포함 내용:
- 무엇을 만들었나 — 스냅샷 export, view 레이어, 툴 2개.
- 핵심 결정 4가지 (spec 의 결정 1~4 요약).
- 파일 목록 + 테스트 수 변화.
- 한계 / 다음 단계 — Stage 10.1(R2 export, forward dependency: R2 Parquet 도 `snapshot_date`·`synced_at`·`row_count` 컬럼 임베드 필수), Phase 12(운영자/지역 추세 툴), 롤업 테이블(스냅샷 ~60일 후).

- [ ] **Step 3: CLAUDE.md 진행 상황 갱신**

`CLAUDE.md` 의 "진행 상황" 섹션에 Phase 11 한 줄 추가:

```
- **Phase 11 (완료):** 시계열 분석 기반 — 날짜별 스냅샷 export(`ev-mcp-snapshot`) + analytics view 레이어(`v_all`/`v_latest`) + 시계열 툴 2개(`snapshot_diff`, `inventory_trend`). → `docs/PHASE11.md`
```

- [ ] **Step 4: 커밋**

```bash
git add docs/PHASE11.md CLAUDE.md
git commit -m "docs: Phase 11 보고서 — 시계열 분석 기반"
```

---

## Self-Review 결과

**Spec coverage:** spec 의 컴포넌트·결정 전부 Task 로 매핑됨 —
- 결정 1(sync 관측 + synced_at 중복 스킵) → Task 1
- 결정 2(데이터 정직성, synced_at 노출) → Task 4·5·6 모델/툴
- 결정 3(snapshot↔sync 분리, `ev-mcp-snapshot` 주 메커니즘) → Task 1·8
- 결정 4(named view) → Task 3
- 첫 툴 2개 → Task 5·6
- forward dependency(R2 컬럼 규약) → Task 10 PHASE11.md
- 비목표(롤업·R2 export·요일 분석) → Task 미생성 (의도적)

**Type consistency:** `write_snapshot(db_path, snapshot_dir, *, force)` 시그니처가 Task 1·8 에서 일치. `SnapshotDiff`/`InventoryTrendRow` 필드가 Task 4 정의 ↔ Task 5·6 생성자 ↔ Task 7 반환 타입에서 일치. `DC_CODES` 가 Task 6 에서 정의 후 `regional_density`·`inventory_trend` 양쪽에서 동일 import. `SNAPSHOT_GLOB` 가 Task 1 정의 후 Task 3 에서 import.

**Placeholder scan:** "TBD"/"적절히 처리" 류 없음. 모든 코드 스텝에 완전한 코드 포함.

**알려진 위험 1 — conftest 픽스처 교체의 파급:** Task 3 Step 1 이 `analytics_snapshot`→`analytics_snapshot_dir` 로 픽스처를 바꾼다. 기존 `analyze_operator_health`/`regional_density` 툴 테스트가 `analytics`/`ctx` 픽스처를 통해 이 데이터를 쓰므로, latest 스냅샷(2026-05-22)이 기존 기대값(ME=200/EV=150/KM=120/TINY=50 + DEAD del_yn='Y')을 그대로 유지하도록 픽스처를 설계했다. Task 3 Step 6 에서 기존 툴 테스트 green 을 명시적으로 확인한다.

**알려진 위험 2 — 기존 툴 테스트가 `{source}` 를 직접 쓰는 경우:** `test_analytics_operator_health.py`/`test_analytics_regional_density.py` 가 `analytics.query("... {source} ...")` 를 직접 호출하면 Task 3 후 깨진다. Step 6 에서 발견되면, 해당 테스트의 `{source}` 를 `v_latest` 로 바꾸는 것으로 fix (동작 동일).

---

## Execution Handoff

(plan 저장 후 실행 방식 선택 — 아래 메시지 참조)
