"""web dashboard 가 fetch 하는 Parquet 을 최신 스냅샷으로 갱신.

web/ 의 DuckDB-WASM 페이지들은 ``/scratch/chargers_snapshot.parquet`` 한 파일을
fetch 한다. 이 파일은 sync 파이프라인과 분리돼 있어, ``ev-mcp-sync`` 를 돌려도
자동으로 갱신되지 않는다 (그래서 web 이 옛 데이터를 보는 사고가 났다).

이 스크립트는 그 단절을 잇는다: ``data/snapshots/`` 의 **가장 최근 정상(0행 아님)**
날짜별 스냅샷을 골라 web 이 보는 경로로 복사한다. ``ev-mcp-sync`` (또는
``ev-mcp-snapshot``) 후 한 번 실행하면 web 데이터가 최신화된다.

실행
----
    source .venv/bin/activate
    python scripts/publish_web_snapshot.py
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT_DIR = ROOT / "data" / "snapshots"
DEFAULT_DEST = ROOT / "scratch" / "chargers_snapshot.parquet"
SNAPSHOT_GLOB = "chargers_*.parquet"


def _row_count(parquet: Path) -> int:
    conn = duckdb.connect(":memory:")
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM read_parquet('{parquet.resolve()}')"
        ).fetchone()
    finally:
        conn.close()
    return 0 if row is None else int(row[0])


def latest_valid_snapshot(snapshot_dir: Path) -> Path | None:
    """파일명 날짜 내림차순으로 첫 번째 0행 아닌 스냅샷. 없으면 None."""
    files = sorted(snapshot_dir.glob(SNAPSHOT_GLOB), reverse=True)
    for f in files:
        if _row_count(f) > 0:
            return f
    return None


def publish(snapshot_dir: Path, dest: Path) -> Path:
    if not snapshot_dir.exists():
        raise FileNotFoundError(
            f"스냅샷 디렉터리가 없습니다: {snapshot_dir}. "
            "ev-mcp-sync (또는 ev-mcp-snapshot) 를 먼저 실행하세요."
        )
    latest = latest_valid_snapshot(snapshot_dir)
    if latest is None:
        raise FileNotFoundError(
            f"{snapshot_dir} 에 정상(0행 아님) 스냅샷이 없습니다. "
            "ev-mcp-sync 를 완료한 뒤 다시 실행하세요."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(latest, dest)
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(prog="publish-web-snapshot", description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args()
    try:
        src = publish(args.snapshot_dir, args.dest)
    except FileNotFoundError as e:
        sys.stderr.write(f"{e}\n")
        return 1
    rows = _row_count(args.dest)
    sys.stdout.write(f"web 스냅샷 갱신: {src.name} → {args.dest} ({rows:,} 행)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
