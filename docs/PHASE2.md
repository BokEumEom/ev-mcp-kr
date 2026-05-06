# Phase 2 보고 — 캐시, 지오코더, 7개 MCP 툴

**기간:** 2026-04-30
**범위:** 계획서 Phase 2 (Cache & tools)
**검증:** pytest 68건 통과, ruff 클린, mypy `--strict` 클린.

## 요약 (3줄)

Phase 1 의 raw 클라이언트 위에 **캐시 계층**(24h station_info + 60s status), **지오코더**(VWorld), **7개 MCP 툴**을 얹었습니다. 사용자 노출용 도메인 모델(ChargerSummary, ChargerNearby, StationDetails, StatusChange)로 코드를 한국어 라벨까지 입혀서 반환합니다. Phase 3(FastMCP 서버 와이어링)가 바로 위에 얹히도록 인터페이스를 정리했습니다.

## 추가된 모듈

| 파일 | 역할 |
|---|---|
| `src/ev_mcp/cache.py` | StationInfoCache(24h, 4종 인덱스) + StatusCache(60s, GC) + Caches 컨테이너 |
| `src/ev_mcp/geocode.py` | VWorld 지오코더 (도로명→지번 fallback, key redaction) |
| `src/ev_mcp/codes_lookup.py` | 정적 코드 테이블 lazy 로더 + resolve_sido/sigungu/busi_id helper |
| `src/ev_mcp/domain.py` | 사용자 노출용 Pydantic 모델 4종 (코드 → 한국어 라벨 join) |
| `src/ev_mcp/tools/codes.py` | `lookup_codes` |
| `src/ev_mcp/tools/station.py` | `get_station_details` |
| `src/ev_mcp/tools/region.py` | `search_chargers_by_region` |
| `src/ev_mcp/tools/operator.py` | `list_chargers_by_operator` |
| `src/ev_mcp/tools/status.py` | `get_charger_status`, `recent_status_changes` |
| `src/ev_mcp/tools/nearby.py` | `find_chargers_nearby` (haversine + bounding box) |

## 핵심 설계 결정

- **2계층 캐시.** station_info 는 응답 한도 크고(12k~20k행) 변경 잦지 않아 24h 통째 prefetch + 4종 인덱스(stat_id/zcode/zscode/busi_id). status 는 60초로 짧아 키별 TTL 캐시. 둘 다 `asyncio.Lock` 으로 stampede dedup.
- **사용자 노출 모델 분리.** `models.py` 는 docx 1:1, `domain.py` 는 사용자 친화. 코드 → 한국어 라벨은 도메인 레이어에서만 join. 이렇게 하면 docx 변경(예: 코드 추가)이 raw 모델에만 영향.
- **지오코더는 옵션.** `VWORLD_KEY` 미설정 시 `find_chargers_nearby(address=...)` 만 막힘. lat/lng 직접 호출은 항상 가능.
- **bounding box pre-filter.** haversine 은 충전기 12k 모두 계산하면 비싸서, 위경도 사각형으로 1차 필터 후 정확 거리 계산.
- **시도 zcode 매칭.** cold cache + lat/lng → 전국 12k 다운받지 않도록 17개 시도의 bounding box 로 zcode 추정 후 그 시도만 fetch. 한국 영역 밖 좌표는 ValueError.

## 보안·견고성 (리뷰 반영)

code-reviewer 에이전트의 Phase 2 리뷰에서 잡힌 항목 처리:

| 발견 | 심각도 | 처리 |
|---|---|---|
| VWorld parcel-retry 5xx 시나리오 회귀 테스트 부재 | CRITICAL | 회귀 테스트 추가 (`test_geocode_parcel_retry_5xx_redacts_key`) |
| station_info refresh 중 예외 시 partial state 가능성 | HIGH | try/except 가드 + 기존 인덱스 보존 + 회귀 테스트 |
| StatusCache `_locks` 무한 누적 | HIGH | `_gc()` 추가 (10x TTL 초과 entry+lock 정리) + `invalidate()` 도 lock 비움 |
| 한국 영역 밖 좌표 + cold cache → 전국 9999행 fetch | HIGH | `_nearest_zcode is None` → ValueError + 회귀 테스트 |
| stat_id/chger_id 정규식 검증 부족 | HIGH | `^[A-Za-z0-9]{1,8}$` / `^[A-Za-z0-9]{2}$` 정규식, `../foo` 같은 입력 차단 |
| 토큰 폭발 — limit 200 + cold cache → 100KB+ 응답 | HIGH | MAX_LIMIT 100 으로 cap, cold-cache `num_of_rows` 도 1000~2000 으로 제한 |
| 테스트가 private `_rebuild_indexes` 호출 | MEDIUM | `seed_for_testing(rows)` public helper 추가 + 5개 테스트 마이그레이션 |

## 회귀 테스트 추가 (총 68건, +35건)

- 캐시: refresh 부분상태 보호, _locks 정리, GC 동작
- 지오코더: parcel-retry 5xx 키 마스킹, 도로명 NOT_FOUND → parcel fallback, non-JSON body 마스킹, unconfigured 동작
- 툴: 시도/시군구/충전기타입/available_only 필터, cold→hot 캐시 fallback, ValueError 검증, 한국 영역 밖 좌표 차단, path-traversal 입력 차단

## 변경 이력

- 2026-04-30 16:30 Phase 2-1~2-5 구현
- 2026-04-30 16:55 code-reviewer 종합 리뷰
- 2026-04-30 17:05 리뷰 반영 (CRITICAL 1 + HIGH 5 + MEDIUM 1)

## 다음 단계 (Phase 3 — FastMCP wiring)

1. `src/ev_mcp/server.py` — FastMCP 앱, 7개 툴 등록 (`readOnlyHint=True`).
2. 코드 테이블을 MCP **resources** (`mcp://codes/sido` 등) 로도 노출.
3. CORS 미들웨어 — `https://claude.ai`, `https://claude.com`, `http://localhost:6274`.
4. `/health` 엔드포인트 — 캐시 age 포함.
5. `structlog` JSON 라인 로깅 (`logs/ecs-mcp-server.log`).
6. `ev-mcp` console_script entry point — `python -m uvicorn` 으로 시작.
7. 로컬 MCP Inspector 스모크 테스트.

설계 검토 사항 (다음 Phase 진입 전 사용자 컨펌 필요):
- `ToolContext` dataclass 도입 여부 (client/caches/settings 트리플 → 단일 dependency)
- 백그라운드 캐시 워밍 작업 (Phase 3 시작 시 한 번 prefetch)
