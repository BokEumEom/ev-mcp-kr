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
