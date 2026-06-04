#!/usr/bin/env bash
# web 대시보드 데이터 새로고침 — sync → publish 를 한 번에.
#
# ev-mcp-sync 는 data/snapshots/ 에만 쓰고, web 메인·고속도로 페이지는
# scratch/chargers_snapshot.parquet 를 읽는다 (sync 중 깨진 데이터 노출을 막는
# 의도적 분리). 이 스크립트가 둘을 잇는다: 최신 데이터를 받아 web 이 보는
# 파일로 publish 한다.
#
# 사용법:
#   scripts/refresh_web.sh                # sync + publish
#   scripts/refresh_web.sh --publish-only # 이미 sync 했으면 publish 만
#
# 참고: 시계열(trends) 페이지는 별도 흐름(scratch/web_snapshots/ + summary)이라
# 여기서 다루지 않는다. 라이브 사이트는 publish 후 scratch/ 를 배포해야 반영된다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# venv 자동 활성화 (있고, 아직 안 켜졌으면)
if [ -z "${VIRTUAL_ENV:-}" ] && [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

PUBLISH_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --publish-only) PUBLISH_ONLY=1 ;;
    -h | --help)
      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "알 수 없는 옵션: $arg (사용법: --help)" >&2
      exit 2
      ;;
  esac
done

if [ "$PUBLISH_ONLY" -eq 0 ]; then
  echo "▶ [1/2] ev-mcp-sync — data.go.kr → data/snapshots/"
  if command -v ev-mcp-sync >/dev/null 2>&1; then
    ev-mcp-sync
  else
    python -m ev_mcp.sync
  fi
else
  echo "▶ [1/2] sync 건너뜀 (--publish-only)"
fi

echo "▶ [2/3] publish 메인 — data/snapshots/ → scratch/ (메인·고속도로가 읽는 파일)"
python scripts/publish_web_snapshot.py

echo "▶ [3/3] publish 시계열 — 실제 관측 2개 이상이면 trends 도 갱신"
python scripts/publish_web_timeseries.py || echo "  (시계열 스킵: 실제 관측 2개 미만 — 더 쌓이면 자동 반영)"

echo "✔ 완료. 로컬은 새로고침하면 반영됩니다."
echo "  라이브 사이트는 scratch/chargers_snapshot.parquet 를 배포(push/업로드)해야 보입니다."
