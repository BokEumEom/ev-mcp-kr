# Phase 9 보고 — TypeScript Cloudflare Workers 포팅

**기간:** 2026-05-07 ~ 2026-05-08
**범위:** Python/FastMCP 7-tool MCP 서버 → TypeScript/Workers + Durable Objects 포팅. 무료 / 영구 / 글로벌 엣지.
**검증:** `tsc --noEmit` 클린, `wrangler deploy --dry-run` 통과 (번들 1.65 MiB raw / **301.60 KiB gzipped**, 무료 플랜 1MB 한도 안). 7개 MCP 툴 라이브 호출 검증, 실 production 배포 후 `/health` 200 + cron sync 동작 확인.

## 요약 (3줄)

Render 호스팅의 신용카드 장벽 + Koyeb 등 free tier 디스크 비영속 + MCPB 모드 (Phase 7) 의 PC 의존성을 모두 우회하기 위해 **Cloudflare Workers + Durable Objects (SQLite GA 2025)** 로 전체 스택을 TypeScript 재작성. 핵심 깨달음은 `agents-mcp.serve()` 가 MCP 세션마다 별도 DO 로 라우팅한다는 점 — 그래서 **두-DO 아키텍처 (per-session McpAgent + 단일 글로벌 InventoryStore)** 로 분리하고 DO RPC 로 위임. 7개 툴 모두 1:1 포팅 + 페이지·재개 가능한 cron sync + 토큰 게이트된 admin 엔드포인트 + 배포 runbook (`workers/DEPLOY.md`) 까지 한 사이클로 완성.

## 핵심 결정

- **두-DO 분리.** 처음엔 `ChargerInventory` 한 클래스에 McpAgent + SQLite 다 합쳤지만, `serve()` 가 `streamable-http:<sessionId>` 로 DO 를 키잉해서 세션마다 별도 인스턴스 + 별도 SQLite 라는 걸 Stage 2 검증 중 발견. 옵션 A (모든 세션을 단일 DO ID 로 강제 라우팅) 는 transport state 가 충돌, 옵션 B (별도 InventoryStore plain DO + RPC) 가 프레임워크 결과 일치. **B 채택.**
- **같은 워커 = MCP + sync.** Stage 4 sync 를 별도 worker 로 분리할지 같은 worker 의 `scheduled` 핸들러로 둘지 갈렸음. 후자 선택 — STORE 바인딩 공유, cross-worker 인증 불필요, 운영 단순. 같은 코드베이스가 fetch (MCP) + scheduled (cron) 둘 다 export.
- **Cron 매분 ❌ / 매 5분 ✓.** `*/5 * * * *` × `pagesPerTick=1` × `pageSize=2000` = 253 페이지 ≈ 21시간 풀사이클 ≈ "거의 일 1회". 무료 플랜 scheduled handler 의 30s wall-clock 한도 안에 한 페이지 fetch + upsert 가 들어옴. 유료 플랜은 `crons = ["0 18 * * *"]` 단일 실행으로 전환 가능.
- **pageSize lock per cycle.** 운영 직후 발견한 버그 — cron(2000) + 수동 트리거(500) 혼용 시 `total_pages` 와 `last_completed_page` 가 디싱크. cycle 첫 tick 의 pageSize 를 `sync_state.page_size` 에 저장 + 이후 tick 강제 일치. cycle 종료 시 자동 해제.
- **`/internal/*` 안전 기본값.** `DEV_SEED_TOKEN` 미설정 시 503 (production 가드). 토큰 일치 시 200, 불일치 시 403. seed/sync/sync-status/sync-reset 4개 admin 엔드포인트 모두 동일 게이트.
- **Python 코드 그대로 보존.** `src/ev_mcp/` 는 MCPB (Phase 7) 사용자용으로 유지. 코드 테이블 (`codes/*.json`) 은 양쪽이 빌드 시 import 해서 공유.

## 추가/변경된 모듈

### 신규 (`workers/`)
| 파일 | 역할 | 라인 |
|---|---|---|
| `src/inventory_store.ts` | 단일 글로벌 plain DO. SQLite 스키마 (chargers + sync_state), 6개 read 메서드 + upsertMany + seedForTesting | 289 |
| `src/agent.ts` | per-session `McpAgent`. 7개 툴 등록, `env.STORE.get(idFromName("global"))` stub 으로 InventoryStore 위임 | 202 |
| `src/client.ts` | data.go.kr 라이브 클라이언트. `getChargerInfo` + `getChargerStatus` + retry + redact + AbortController + envelope unwrap | 442 |
| `src/sync.ts` | cron 상태 머신. `runSyncTick` (페이지 단위 fetch + upsert + state 영속) + `getSyncStatus` + `resetSyncCycle` | 246 |
| `src/types.ts` | `ChargerInfo` / `ChargerStatusRow` / `ResultHeader` 인터페이스, zod 스키마 (sync 워커 검증용), `coerceStat` / `parseYyyymmddhhmmss` / `rowToChargerInfo` | 257 |
| `src/index.ts` | Worker entry. `fetch` (MCP + admin) + `scheduled` 핸들러. 토큰 게이트 헬퍼 | 165 |
| `src/codes/index.ts` | 정적 코드 테이블 import + `resolveSido/Sigungu/BusiId` | 98 |
| `src/tools/inventory.ts` | DO 의존 툴 4종 (`list_chargers_by_operator`, `find_chargers_nearby`, `search_chargers_by_region`, `get_station_details`) | 337 |
| `src/tools/status.ts` | 라이브 의존 툴 2종 (`get_charger_status`, `recent_status_changes` + 60s `RecentChangesCache`) | 175 |
| `src/tools/codes.ts` | `lookup_codes` (정적) | 24 |
| `wrangler.toml` | INVENTORY + STORE DO 바인딩, v1+v2 마이그레이션, `*/5 * * * *` cron | — |
| `DEPLOY.md` | 사용자 액션 단계별 runbook (login → secret put → deploy → Claude.ai connector → 자연어 스모크) | — |

### 변경
| 파일 | 변경 |
|---|---|
| `docs/PHASE9.md` | 이 보고서 (재구성) |

### 보존 (Phase 1~8 영향 없음)
- `src/ev_mcp/*` — MCPB 사용자용 그대로 운영
- `src/ev_mcp/codes/*.json` ↔ `workers/src/codes/*.json` — 동일 데이터 양쪽 import

## 아키텍처

```
                  Claude.ai / Claude Desktop
                          │  (HTTPS, /mcp Streamable)
                          ▼
       ┌─────────────────────────────────────────────┐
       │  Cloudflare Worker (전 세계 엣지)             │
       │   ├─ fetch handler                           │
       │   │   ├─ /mcp           → ChargerInventory    │
       │   │   ├─ /health        → 200                 │
       │   │   └─ /internal/*    → token gate          │
       │   └─ scheduled handler (cron */5)            │
       │       └─ runSyncTick → DO RPC                 │
       └────────────┬────────────────────────────────┘
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
 ┌──────────────┐        ┌──────────────────┐
 │ ChargerInven │        │ InventoryStore   │
 │  (McpAgent,  │ RPC →  │  (plain DO,      │
 │   세션별 DO) │        │   "global" ID)   │
 │              │        │   ├─ SQLite      │
 │  툴 라우팅   │        │   │  (chargers + │
 │  + 라이브    │        │   │   sync_state)│
 │    HTTP      │        │   └─ 506k rows   │
 └──────────────┘        └────────┬─────────┘
        │                         ▲
        │ (live status only)      │ (upsert)
        ▼                         │
   data.go.kr ───────────────────┘
   getChargerStatus (라이브)
   getChargerInfo (sync)
```

## 단계별 결과

| Stage | 산출 | 검증 |
|---|---|---|
| 1 (05-07) | scaffold + `lookup_codes` | wrangler dev 부팅, 1 툴 응답 |
| 2 (05-07) | `list_chargers_by_operator` + `find_chargers_nearby` + DDL fix (`SCHEMA_STATEMENTS` 6 분리 → DO SQLite 한 statement 제약 우회) + 두-DO 분리 | 2-row seed → 새 MCP 세션에서 read 성공 (cross-session 영속) |
| 3a (05-08) | `search_chargers_by_region` + `get_station_details` | 5 툴 라이브, 강남구 4 rows 반환 |
| 3b (05-08) | `EvChargerClient` + `get_charger_status` + `recent_status_changes` (60s 캐시) | 7 툴 라이브, 캐시 hit 11ms, `fetch.bind(globalThis)` 로 Workers Illegal-invocation 회피 |
| 4 (05-08) | `getChargerInfo` + 페이지 재개 가능한 sync 상태 머신 + `scheduled` 핸들러 + `/internal/sync` + `/internal/sync-status` | tick #1 page 1, tick #2 page 2 (resume), MCP 가 실 sync 데이터(`ME174013` 낙성대동주민센터) 즉시 반환 |
| 5 (05-08) | `/internal/*` 토큰 게이트 강화 + `workers/DEPLOY.md` + `wrangler deploy --dry-run` 통과 + 사용자 production 배포 + pageSize lock 핫픽스 + `/internal/sync-reset` | production `/health` 200, cron sync 페이지 누적 진행 중 |

## InventoryStore DO API

`InventoryStore` (plain DO, `idFromName("global")`) — Python `ChargerStore` 의 메서드 동명 매핑:

```typescript
class InventoryStore extends DurableObject {
  // writes
  upsertMany(rows: readonly ChargerInfo[]): number
  setSyncState(key: string, value: string): void
  seedForTesting(rows: readonly ChargerInfo[]): number

  // reads
  byStatId(statId: string): ChargerInfo[]
  byBusiId(busiId: string, limit?: number): ChargerInfo[]
  byBusiIdAndZcode(busiId: string, zcode: string, limit?: number): ChargerInfo[]
  byZcode(zcode: string, limit?: number): ChargerInfo[]
  byZscode(zscode: string, limit?: number): ChargerInfo[]
  nearLatLng(lat: number, lng: number, radiusKm: number, limit?: number): ChargerInfo[]

  // meta
  totalCount(): number
  getSyncState(key: string): string | null
}
```

스키마는 Phase 6 의 `_SCHEMA_SQL` 과 비트 단위 동일 — `chargers` 1 테이블 + 4 인덱스 (busi_id / zcode / zscode / lat,lng) + `sync_state` 1 테이블, PRIMARY KEY (stat_id, chger_id).

## 보안 / 시크릿 위생

- **`SERVICE_KEY`**: `wrangler secret put` 으로 등록. 코드 어디에도 평문 없음 (`.dev.vars` 는 `.gitignore`).
- **`EvChargerClient.redact()`**: 외부에 surface 되는 모든 텍스트 (로그, 에러 메시지) 에서 raw + URL-encoded + plus-encoded 키 변형 모두 `***` 치환. wrangler tail grep 으로 누출 0건 확인.
- **`/internal/*` 게이트**: `DEV_SEED_TOKEN` 미설정 시 503 (production safe-default). 토큰 일치 시만 통과. 4개 admin 엔드포인트 (seed/sync/sync-status/sync-reset) 모두 동일.
- **Durable Object 격리**: McpAgent 의 per-session DO 가 transport state 만 가지고 데이터 무지 → InventoryStore 와 RPC 경계가 그 자체로 격리 보호막.

## 검증

```bash
$ npx tsc --noEmit                                                    # 클린
$ npx wrangler deploy --dry-run --outdir=/tmp/wrangler-dist
Total Upload: 1646.46 KiB / gzip: 301.60 KiB                          # 무료 플랜 1MB 안

$ curl -s https://ev-mcp.<account>.workers.dev/health
{"ok":true,"version":"0.1.0","platform":"cloudflare-workers"}         # production 살아있음

$ # tools/list (initialize → notifications/initialized → list)
"name":"find_chargers_nearby"
"name":"get_charger_status"
"name":"get_station_details"
"name":"list_chargers_by_operator"
"name":"lookup_codes"
"name":"recent_status_changes"
"name":"search_chargers_by_region"                                    # 7 툴

$ # 라이브 호출 (실 SERVICE_KEY)
recent_status_changes(period=1, limit=3) → 첫 호출 6.5s, total_count:81, count:3
recent_status_changes(period=1, limit=3) → 두번째 호출 11ms (cache hit)
get_charger_status(ER000563, 03)        → stat_label="충전대기", stat_upd_dt=ISO

$ # cron sync (production)
/internal/sync        → {processedRows:500, lastCompletedPage:N+1, ...}
/internal/sync-status → total_rows_in_store 점진 증가, page_size lock 가시

$ # 키 누출 검증
wrangler tail | grep -c "<SERVICE_KEY 처음 14자>"
0
```

## Render(P4–5) / MCPB(P7) / Workers(P9) 비교

| 항목 | Render | MCPB | Workers |
|---|---|---|---|
| 호스팅 비용 | $7~25/월 (CC 필수) | 0 | 0 (free plan) |
| Claude 클라이언트 | claude.ai + Desktop | Desktop | claude.ai + Desktop |
| `SERVICE_KEY` | 운영자 1 | 사용자 본인 | 운영자 1 (`wrangler secret`) |
| DB | 영속 디스크 운영 | 사용자 PC | DO SQLite (글로벌 엣지) |
| 첫 sync | 운영자 cron | 사용자 1회 | 자동 cron `*/5` |
| 영구 가동 | sleep 가능 | PC 켜져야 | 영원 (DO 인풋게이트로 자동 깨움) |
| 약관 리스크 | data.go.kr 키 공유 회색지대 | 정합 | 회색지대 동일 |
| 다중 동시 사용자 | 단일 인스턴스 | 사용자 별 | 세션별 DO + 글로벌 InventoryStore |
| 코드 베이스 | Python 단일 | Python 단일 | TypeScript 분리 (`workers/`) |

세 모드 다 같은 docx 스펙 + 같은 코드 테이블 (`codes/*.json`) 공유.

## 알려진 한계 / 후속

1. **`find_chargers_nearby` lat/lng-only.** Python 은 `address` 도 받지만 (VWorld 지오코더), Workers 포팅에선 미구현. 사용자 자연어 "강남역 근처" → Claude 가 lat/lng 직접 추론하지 못하면 실패. **Phase 10 후보 #1.**
2. **vitest + msw 미구현.** 회귀 방어망 없음 — `wrangler dev` 수동 검증만 있어 다음 변경 때 위험. **Phase 10 후보 #2.**
3. **무료 플랜 scheduled CPU 30s.** `pagesPerTick=1` 강제 → 풀사이클 21시간. 유료 플랜 ($5/월) 으로 전환 시 단일 일 1회 cron + 수십 페이지 한 번에 가능.
4. **`/internal/*` 토큰 단일 보호.** 추가 가드 (Cloudflare Access, IP allow-list, mTLS) 는 운영 정책 결정 후 추가.
5. **Python ↔ Workers 코드 중복.** `coerceStat`, `parseYyyymmddhhmmss`, 30+ 필드 매핑 등 두 곳에 있음 — 향후 docx 스펙 변경 시 양쪽 같이 갱신해야 함. `/spec-check` 슬래시 명령이 양쪽 다 검사하도록 확장 검토.
6. **Per-session McpAgent DO 비용.** 세션마다 별도 DO + 별도 SQLite (agents-mcp 가 자체 테이블 만듦). 무료 플랜 한도 (DO 인스턴스 1M/월) 안에서 동작하지만, 트래픽 증가 시 단일 DO 로 강제 라우팅 옵션 재검토 가능.

## 변경 이력
- 2026-05-07 Phase 9 시작, plan 작성, Stage 1 scaffold + lookup_codes
- 2026-05-07 Stage 2 — DDL 분리 실행, ChargerInfo TS 타입 + zod 스키마, list_chargers_by_operator + find_chargers_nearby
- 2026-05-07 두-DO 분리 (옵션 B) — InventoryStore plain DO 추출, ChargerInventory McpAgent → RPC 위임. STORE 바인딩 + v2 마이그레이션. cross-session 영속 검증
- 2026-05-08 Stage 3a — search_chargers_by_region + get_station_details, byStatId/byZcode/byZscode 메서드
- 2026-05-08 Stage 3b — EvChargerClient (retry + redact + AbortController), get_charger_status + recent_status_changes (60s 캐시), fetch.bind(globalThis) 로 Illegal-invocation 회피, 7 툴 라이브
- 2026-05-08 Stage 4 — getChargerInfo + apiToChargerInfo, 페이지 재개 가능한 sync 상태 머신, scheduled 핸들러 (`*/5 * * * *`), /internal/sync + /internal/sync-status. 실 데이터 sync 검증
- 2026-05-08 Stage 5 — /internal/* 토큰 게이트 강화 (`DEV_SEED_TOKEN` 미설정→503), workers/DEPLOY.md, wrangler deploy --dry-run 통과, production 배포 (사용자), pageSize lock 핫픽스 + /internal/sync-reset
- 2026-05-08 Phase 9 보고서 정리 (이 문서)

## 다음 단계 (Phase 10 후보)

1. **VWorld 지오코더 통합** — `find_chargers_nearby` 가 address 입력도 받게. Python `geocode.py` 1:1 포팅 + `VWORLD_KEY` 시크릿.
2. **vitest + msw 테스트 셋업** — `EvChargerClient` (msw 로 데이터고고개알 모킹) + `runSyncTick` (InventoryStore mock) + 툴 단위 회귀 테스트. 80%+ 커버리지.
3. **단일 일 1회 cron 전환** (유료 플랜 시) — `crons = ["0 18 * * *"]` + `pagesPerTick=20` 으로 한 번에 풀 sync.
4. **`/spec-check` 확장** — docx ↔ Python 모델 + Workers 모델 3-way 일치성 감사.
5. **OAuth (Claude Custom Connector)** — 운영 정책 결정 후. 현재는 무인증.
