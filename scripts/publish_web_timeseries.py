"""실제 일별 스냅샷(data/snapshots/)을 시계열 페이지가 보는 곳으로 publish.

trends.html 은 ``scratch/web_snapshots/`` 의 날짜별 parquet + manifest +
trends_summary 를 읽는다. 이 스크립트는 ``data/snapshots/`` 의 **0행 아닌 실제
관측들**을 그쪽으로 복사하고, 합성이 아님(``synthetic=false``)을 명시한 manifest
와 요약을 생성한다. 데모 배너는 자동으로 사라진다.

관측이 1개뿐이던 시절엔 ``synthesize_snapshots.py`` 로 데모를 만들었지만, 실제
관측이 2개 이상 쌓이면 이 스크립트로 대체한다 (진짜 추세).

실행
----
    source .venv/bin/activate
    python scripts/publish_web_timeseries.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT_DIR = ROOT / "data" / "snapshots"
DEFAULT_OUT_DIR = ROOT / "scratch" / "web_snapshots"
SNAPSHOT_GLOB = "chargers_*.parquet"


def _valid_snapshots(snapshot_dir: Path) -> list[tuple[str, Path]]:
    """0행 아닌 스냅샷 → [(snapshot_date_iso, path)] (날짜 오름차순, 날짜 중복은 최신 파일)."""
    conn = duckdb.connect(":memory:")
    by_date: dict[str, Path] = {}
    try:
        for f in sorted(snapshot_dir.glob(SNAPSHOT_GLOB)):
            row = conn.execute(
                f"SELECT CAST(ANY_VALUE(snapshot_date) AS VARCHAR), COUNT(*) "
                f"FROM read_parquet('{f.resolve()}')"
            ).fetchone()
            if row and row[1] > 0 and row[0]:
                by_date[row[0]] = f  # 같은 날짜는 마지막(파일명순 뒤) 우선
    finally:
        conn.close()
    return sorted(by_date.items())


def publish(snapshot_dir: Path, out_dir: Path) -> list[str]:
    if not snapshot_dir.exists():
        raise FileNotFoundError(
            f"스냅샷 디렉터리가 없습니다: {snapshot_dir}. ev-mcp-sync 를 먼저 실행하세요."
        )
    snaps = _valid_snapshots(snapshot_dir)
    if len(snaps) < 2:
        raise ValueError(
            f"실제 스냅샷이 {len(snaps)}개뿐입니다. 시계열엔 2개 이상 필요합니다. "
            "며칠 더 sync 하거나, 데모가 필요하면 synthesize_snapshots.py 를 쓰세요."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    # 기존 chargers_*.parquet 제거 (합성 잔재 등) — manifest 와 정합 유지
    for old in out_dir.glob(SNAPSHOT_GLOB):
        old.unlink()

    dates: list[str] = []
    for d, f in snaps:
        shutil.copy2(f, out_dir / f"chargers_{d}.parquet")
        dates.append(d)

    manifest = {
        "synthetic": False,
        "dates": dates,
        "note": f"실제 sync 관측 {len(dates)}개 ({dates[0]} ~ {dates[-1]}).",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # per-date 요약 생성 (트렌드 즉시 로드용)
    from build_trends_summary import build as build_summary

    build_summary(out_dir)
    return dates


def main() -> int:
    parser = argparse.ArgumentParser(prog="publish-web-timeseries", description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    try:
        dates = publish(args.snapshot_dir, args.out_dir)
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"{e}\n")
        return 1
    sys.stdout.write(
        f"시계열 web 스냅샷 publish: {len(dates)}개 관측 ({dates[0]} ~ {dates[-1]}) → {args.out_dir}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
