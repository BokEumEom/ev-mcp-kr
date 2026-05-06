# Phase 6 보고 — SQLite 영속 캐시

**기간:** 2026-05-06
**범위:** 계획서 Phase 6 (영속화 + sync 분리)
**검증:** pytest **102건** 통과 (Phase 5 의 89건 + 13건 신규: store 18건, sync 2건, 기타 정리), ruff 클린, mypy `--strict` 클린.

## 요약 (3줄)

PLAN.md 의 in-memory 24h 캐시 가정이 실제 데이터 (totalCount **506k**) 와 data.go.kr 의 운영 특성 (페이지당 49~60s, 9999행 호출 시 504 게이트웨이 timeout) 앞에서 무너졌습니다. **SQLite 영속 store** + **sync 와 read 분리** 로 재설계: 충전기 인벤토리는 `data/chargers.db` 에 영속화되고, 별도 `scripts/sync_chargers.py` 가 점진적으로 채웁니다. MCP 서버는 read-only 로만 사용하므로 사용자 쿼리는 더 이상 data.go.kr 응답 시간에 묶이지 않습니다 (49s → 마이크로초~ms).

## 추가/변경된 모듈

### 신규
| 파일 | 역할 |
|---|---|
| `src/ev_mcp/store.py` | `ChargerStore` SQLite 클래스 — 스키마 + UPSERT + 인덱스 룩업 (by_busi_id/by_zcode/by_zscode/by_stat_id/near_lat_lng/by_busi_id_and_zcode) |
| `scripts/sync_chargers.py` | 독립 sync 스크립트. resume 지원, 504 무한 retry, page_size 가변 |
| `tests/test_store.py` | store 단위 테스트 18건 (UPSERT idempotent, 인덱스 정확성, bbox, sync_state, is_fresh) |
| `tests/test_sync.py` | sync 스크립트 통합 테스트 2건 (2-page 영속화, last_completed_page 재개) |
| `data/.gitkeep` | DB 디렉터리 (DB 파일 자체는 .gitignore) |
| `docs/PHASE6.md` | (이 문서) |

### 변경
| 파일 | 변경 |
|---|---|
| `src/ev_mcp/cache.py` | `StationInfoCache` 제거 — `StatusCache` (60s TTL, getChargerStatus 용) 만 유지 |
| `src/ev_mcp/context.py` | `ToolContext` 에 `store: ChargerStore` 추가 |
| `src/ev_mcp/settings.py` | `db_path: Path` 필드 추가 (기본 `data/chargers.db`, `DB_PATH` env override) |
| `src/ev_mcp/server.py` | 워밍 백그라운드 task 제거. `build_server` 가 `open_store` 호출. `/health` 가 store 통계 (`total_count`, `last_synced_at`, `last_completed_page`) |
| `src/ev_mcp/tools/operator.py` | `ctx.store.by_busi_id` 룩업으로 단순화 (콜드패스 다중 페이지 분기 제거) |
| `src/ev_mcp/tools/region.py` | `ctx.store.by_zcode/by_zscode` 룩업 (콜드패스 분기 제거) |
| `src/ev_mcp/tools/station.py` | `ctx.store.by_stat_id` PRIMARY KEY 룩업. 빈 결과 시 라이브 fallback 유지 |
| `src/ev_mcp/tools/nearby.py` | `ctx.store.near_lat_lng` 으로 bbox prefilter, 결과에 haversine. KR-only 좌표 가드 직접 |
| `src/ev_mcp/tools/{status,codes}.py` | 변경 없음 (status 는 라이브, codes 는 정적 JSON) |
| `tests/conftest.py` | `ctx` 픽스처가 `:memory:` SQLite store 주입. settings 가 `DB_PATH=:memory:` env 강제 |
| `tests/test_cache.py` | `StationInfoCache` 테스트 제거 (store 로 이전). StatusCache 테스트만 남김 |
| `tests/test_tools_*.py` | `seed_for_testing` 호출이 `ctx.store.seed_for_testing` 으로 변경. cold-path fallback 테스트 정리 |
| `tests/test_server.py` | 워밍 task 관련 테스트 4건 제거. `/health` 어설션이 새 `store` 필드 검증 |
| `.gitignore` | `data/*.db`, `data/*.db-shm`, `data/*.db-wal` 추가 |
| `README.md` | sync 스크립트 사용법 + 첫 실행 가이드 추가 |

## 핵심 결정

- **분리된 sync 와 read.** server 가 data.go.kr 호출을 직접 안 함. sync 는 끈기 있는 별도 프로세스 (timeout 180s, retry 5회, 무한 backoff). read 는 SQLite 인덱스 쿼리.
- **부분 업데이트 OK.** sync 가 중간에 죽어도 받은 페이지는 모두 commit 됨. 다음 실행이 `last_completed_page+1` 부터 이어받음.
- **WAL 모드.** sync 가 쓰는 동안 server 가 read 가능. SQLite 의 다중 reader + 단일 writer 모델.
- **`:memory:` 테스트 픽스처.** 모든 테스트가 메모리 DB 사용 → 파일 IO 없음, 격리 완벽, ~10ms 안에 102건 실행.
- **status 캐시는 in-memory 유지.** 60s TTL 짧고 라이브 데이터라 영속화 가치 없음.

## 테스트 분포 (102건)

| 영역 | 개수 |
|---|---:|
| store (`tests/test_store.py`) | 18 |
| sync (`tests/test_sync.py`) | 2 |
| client (`tests/test_client.py`) | 15 |
| cache/StatusCache (`tests/test_cache.py`) | 7 |
| geocode (`tests/test_geocode.py`) | 5 |
| logging (`tests/test_logging.py`) | 2 |
| models (`tests/test_models.py`) | 5 |
| redact (`tests/test_redact.py`) | 4 |
| server (`tests/test_server.py`) | 9 |
| tools/codes | 3 |
| tools/nearby | 7 |
| tools/operator | 6 |
| tools/region | 5 |
| tools/station | 4 |
| tools/status | 10 |

기존 테스트 (Phase 1~5) 89건 → 100건+ 으로 증가, **회귀 0건**.

## Phase 5 의 운영기관(CV/EV) 0건 버그 — 최종 해결

| 시점 | 동작 | CV 호출 결과 |
|---|---|---|
| Phase 1~4 (in-memory cold path 1 페이지) | 페이지 1 의 ME 만 결과 | ✗ 0건 |
| Phase 5 fix(operator) (다중 페이지 cold path) | 페이지 30 까지 순회 | ✗ MCP 클라이언트 timeout (페이지당 60s × 5~10 = 5~10분) |
| **Phase 6 store-backed** | 인덱스 즉답 | ✅ 마이크로초 |

조건은 sync 가 한 번이라도 돌았으면 (CV 가 박힌 페이지까지 받았으면) CV 호출이 작동. 부분 sync 라도 사용 가능.

## 마이그레이션 / 첫 실행

기존 사용자 (Phase 1~5 운영 중) 가 Phase 6 으로 올릴 때:

1. `git pull && uv pip install -e ".[dev]"` (의존성은 stdlib 만 추가됐으므로 변화 없음)
2. `python scripts/sync_chargers.py` — 백그라운드로 실행 (`nohup ... &` 권장)
3. sync 진행 중에도 `/health` 체크: `rows` 가 점진적으로 증가
4. 일정 정도 (~10k+) 채워지면 운영기관 검색이 작동
5. 풀 sync 완료 시 `total_count_observed = totalCount` 일치
6. cron / systemd timer 로 일 1회 자동 sync 권장

## 검증

```bash
$ python -m pytest -q
......................................................................... [ 70%]
.................................                                         [100%]
102 passed in 0.84s

$ python -m ruff check .
All checks passed!

$ python -m mypy src/
Success: no issues found in 18 source files
```

서버 부팅 (sync 한 번이라도 돈 후):
```bash
$ ev-mcp &
$ curl -s localhost:8000/health | python -m json.tool
{
  "ok": true,
  "version": "0.1.0",
  "store": {
    "rows": 506421,
    "last_synced_at": "2026-05-06T17:30:42+00:00",
    "last_completed_page": 0
  }
}
```

## 다음 단계 (Phase 7 — Render 배포 + 운영)

1. Render 배포 영속 디스크 vs S3 download vs build-time DB
2. cron 스케줄 (일 1회 sync, 새벽 시간대)
3. WAL 체크포인트 (정기 PRAGMA wal_checkpoint)
4. statUpdDt 기준 incremental sync (full sync 대안)
5. 멀티 인스턴스 고려시 SQLite → Postgres/Litestream 마이그레이션 옵션
