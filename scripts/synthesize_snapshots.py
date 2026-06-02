"""web 시계열 페이지용 **합성(데모) 스냅샷** 생성.

⚠️ 이 스크립트가 만드는 데이터는 실제가 아니다. 시계열 페이지의 UI/차트를
보여주기 위한 데모용이다. 실제 추세로 해석하면 안 된다. 실제 스냅샷이 며칠
쌓이면(ev-mcp-sync 반복) 이 스크립트 없이 같은 페이지가 진짜 데이터로 동작한다.

방식
----
가장 최근 실제 스냅샷(data/snapshots/) 1장을 베이스로, 과거 N-1일을 역산해
만든다. 운영 데이터(data/snapshots/)는 건드리지 않고 scratch/web_snapshots/ 에만
쓴다 (MCP 툴의 v_all 오염 방지).

- 총량 점증: 과거일수록 신규 충전기를 덜어냄 (하루 ~DAILY_NEW 대 신규 설치 스토리)
- 가동률 추세: 과거일수록 일부 가용(stat='2')을 비가동(stat='4')으로 전환
  → 비가동률이 과거→현재로 개선되는 추세를 연출

실행
----
    source .venv/bin/activate
    python scripts/synthesize_snapshots.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT_DIR = ROOT / "data" / "snapshots"
DEFAULT_OUT_DIR = ROOT / "scratch" / "web_snapshots"
SNAPSHOT_GLOB = "chargers_*.parquet"

DAYS = 9  # 총 관측 수 (베이스 1 + 합성 DAYS-1)
DAILY_NEW = 600  # 하루 신규 충전기 (역산 시 과거에서 덜어낼 양)


def _latest_snapshot(snapshot_dir: Path) -> tuple[Path, date, int]:
    """가장 최근 0행 아닌 스냅샷과 그 날짜·행수."""
    files = sorted(snapshot_dir.glob(SNAPSHOT_GLOB), reverse=True)
    conn = duckdb.connect(":memory:")
    try:
        for f in files:
            row = conn.execute(
                f"SELECT COUNT(*), ANY_VALUE(snapshot_date) "
                f"FROM read_parquet('{f.resolve()}')"
            ).fetchone()
            if row and row[0] > 0:
                return f, row[1], int(row[0])
    finally:
        conn.close()
    raise FileNotFoundError(
        f"{snapshot_dir} 에 정상 스냅샷이 없습니다. ev-mcp-sync 를 먼저 실행하세요."
    )


def synthesize(snapshot_dir: Path, out_dir: Path) -> list[str]:
    base, base_date, total = _latest_snapshot(snapshot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(":memory:")
    dates: list[str] = []
    try:
        for offset in range(DAYS - 1, -1, -1):  # 과거(큰 offset) → 현재(0)
            d = base_date - timedelta(days=offset)
            d_iso = d.isoformat()
            keep = total - offset * DAILY_NEW
            # 과거일수록 가용→비가동 전환을 촘촘히 (mod 작게). offset=0 은 무전환.
            stat_replace = ""
            if offset > 0:
                mod = max(10, 50 - offset * 5)
                stat_replace = (
                    f", CASE WHEN stat = '2' AND rn % {mod} = 0 "
                    f"THEN '4' ELSE stat END AS stat"
                )
            out = out_dir / f"chargers_{d_iso}.parquet"
            conn.execute(
                f"""
                COPY (
                    WITH ranked AS (
                        SELECT *, ROW_NUMBER() OVER (ORDER BY stat_id, chger_id) AS rn
                        FROM read_parquet('{base.resolve()}')
                    )
                    SELECT * EXCLUDE (rn) REPLACE (
                        DATE '{d_iso}' AS snapshot_date,
                        '{d_iso}T03:00:00+00:00' AS synced_at,
                        {keep} AS row_count
                        {stat_replace}
                    )
                    FROM ranked
                    WHERE rn <= {keep}
                ) TO '{out.resolve()}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
            dates.append(d_iso)
    finally:
        conn.close()

    manifest = {
        "synthetic": True,
        "base_date": base_date.isoformat(),
        "dates": dates,
        "note": (
            f"{base_date.isoformat()} 실제 스냅샷 1관측 + 과거 {DAYS - 1}일 합성. "
            "데모용 — 실제 추세 아님."
        ),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return dates


def main() -> int:
    parser = argparse.ArgumentParser(prog="synthesize-snapshots", description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    try:
        dates = synthesize(args.snapshot_dir, args.out_dir)
    except FileNotFoundError as e:
        sys.stderr.write(f"{e}\n")
        return 1
    sys.stdout.write(
        f"합성 스냅샷 {len(dates)}개 생성: {dates[0]} ~ {dates[-1]} → {args.out_dir}\n"
        "⚠️ 데모용 합성 데이터 (실제 추세 아님)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
