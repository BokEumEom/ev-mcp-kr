"""web 시계열 페이지용 per-date 집계 요약(trends_summary.json) 생성.

trends.html 이 9개 전국 스냅샷(~135MB)을 브라우저로 전부 받아 집계하던 것을
이 작은 JSON 으로 대체해 **즉시** 로드되게 한다. 기간 변화(diff)만 선택된 2개
스냅샷을 그때그때 지연 로드한다.

per-date 집계는 trends.js 의 Q_TREND / Q_HEALTH 와 동일한 정의를 쓴다
(stat 코드 분류·DC 코드·del_yn 필터 일치). 새 스냅샷이 쌓이면 synthesize 또는
실제 publish 파이프라인이 이 스크립트를 다시 호출해 요약을 갱신한다.

실행
----
    source .venv/bin/activate
    python scripts/build_trends_summary.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "scratch" / "web_snapshots"

# trends.js 와 동일하게 유지할 것 (스펙: stat='9' 미연동 분리)
DOWNTIME_CODES = ("1", "4", "5")
UNMONITORED_CODE = "9"
AVAILABLE_CODE = "2"
DC_CODES = ("01", "03", "04", "05", "06", "08", "09", "10")


def _inlist(codes: tuple[str, ...]) -> str:
    return ",".join(f"'{c}'" for c in codes)


def build(web_dir: Path) -> Path:
    manifest_path = web_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"manifest.json 이 없습니다: {web_dir}. "
            "synthesize_snapshots.py 또는 publish 파이프라인을 먼저 실행하세요."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dates = manifest.get("dates", [])
    if not dates:
        raise ValueError("manifest 에 dates 가 비어 있습니다.")

    files = [web_dir / f"chargers_{d}.parquet" for d in dates]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"스냅샷 파일 누락: {missing}")

    filelist = ", ".join(f"'{f.resolve()}'" for f in files)
    conn = duckdb.connect(":memory:")
    try:
        rows = conn.execute(
            f"""
            SELECT
              CAST(snapshot_date AS VARCHAR)                                   AS d,
              COUNT(*)                                                         AS total,
              COUNT(*) FILTER (WHERE chger_type IN ({_inlist(DC_CODES)}))      AS dc,
              COUNT(*) FILTER (WHERE stat = '{AVAILABLE_CODE}')                AS available,
              COUNT(DISTINCT busi_id)                                          AS operators,
              AVG(CASE WHEN stat IN ({_inlist(DOWNTIME_CODES)}) THEN 1.0 ELSE 0.0 END) AS downtime,
              AVG(CASE WHEN stat = '{UNMONITORED_CODE}' THEN 1.0 ELSE 0.0 END) AS unmonitored
            FROM read_parquet([{filelist}])
            WHERE del_yn = 'N'
            GROUP BY snapshot_date
            ORDER BY snapshot_date
            """
        ).fetchall()
    finally:
        conn.close()

    trend = [
        {"d": r[0], "total": int(r[1]), "dc": int(r[2]), "available": int(r[3]), "operators": int(r[4])}
        for r in rows
    ]
    health = [{"d": r[0], "downtime": float(r[5]), "unmonitored": float(r[6])} for r in rows]
    summary = {
        "synthetic": manifest.get("synthetic", False),
        "note": manifest.get("note", ""),
        "dates": [r[0] for r in rows],
        "trend": trend,
        "health": health,
    }
    out = web_dir / "trends_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="build-trends-summary", description=__doc__)
    parser.add_argument("--web-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    try:
        out = build(args.web_dir)
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"{e}\n")
        return 1
    sys.stdout.write(f"시계열 요약 생성: {out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
