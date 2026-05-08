# Phase 9 — TypeScript Cloudflare Workers 포팅

**시작:** 2026-05-07
**상태:** Stage 4 완료, Stage 5 코드 준비 완료 — 사용자 Cloudflare 계정에서 `wrangler deploy` 실행 + Claude.ai Custom Connector 등록 단계 대기 중. 배포 runbook: [`workers/DEPLOY.md`](../workers/DEPLOY.md).
**범위:** Python (FastMCP) → TypeScript (Workers + Durable Objects + agents-mcp). 무료 / 영원히 떠 있음 / 자동 sync (Cron Trigger).

## Context — 왜 포팅?

Phase 1~8 의 Python 구현은 견고하지만:
- Render 배포에 신용카드 등록 필요 (사용자 계정 제약)
- Koyeb 등 대안도 free tier 디스크 비영속 → 매번 sync 필요
- MCPB 모드 (Phase 7) 는 사용자 PC 의존

Cloudflare Workers + Durable Objects 의 SQLite 기능 (2025년 GA) 으로 **진짜 무료 + 영구 + 글로벌 엣지** 배포 가능. 단 Python 미지원 → TypeScript 재작성.

## 결정 사항

| 항목 | 선택 |
|---|---|
| 레포 | 같은 레포, `workers/` 하위 (Python + TS 공존) |
| MVP 범위 | 3 도구 (`lookup_codes` + `list_chargers_by_operator` + `find_chargers_nearby`) |
| 스토리지 | Durable Objects + SQLite (단일 DO 인스턴스 `ChargerInventory`) |
| MCP SDK | Cloudflare 공식 `agents-mcp` (boilerplate 최소) |
| 배포 도구 | wrangler |
| 테스트 | vitest + msw (httpx mock 대응) |

## Architecture

```
                  Claude.ai / Claude Desktop
                          │  (HTTPS)
                          ▼
       ┌───────────────────────────────────┐
       │  Cloudflare Worker (전 세계 엣지) │
       │   ├─ MCP fetch handler             │
       │   ├─ agents-mcp 라우팅              │
       │   └─ DO stub.fetch() 으로 위임      │
       └────────────┬──────────────────────┘
                    │
                    ▼
       ┌───────────────────────────────────┐
       │  Durable Object: ChargerInventory │
       │   ├─ SQLite (자체 영속 디스크)     │
       │   ├─ 506k 행 + 4 인덱스             │
       │   └─ 7 tools 의 데이터 응답         │
       └───────────────────────────────────┘
                    ▲
                    │ Cron Trigger (매일 KST 03시)
                    │
       ┌────────────┴──────────────────────┐
       │  Sync Worker (별도 worker, Cron)  │
       │   ├─ data.go.kr getChargerInfo     │
       │   ├─ 페이지 단위 fetch              │
       │   └─ DO stub 으로 UPSERT            │
       └───────────────────────────────────┘
                    │
                    ▼
            data.go.kr OpenAPI
```

## Stages

### Stage 1 — Foundation + lookup_codes (오늘)
- `workers/` scaffold (package.json, tsconfig, wrangler.toml, vitest)
- 코드 테이블 7종 TS const 로 이전
- `agents-mcp` 통합 + Worker fetch handler
- `ChargerInventory` Durable Object 스키마 (테이블 + 인덱스, 메서드 stub)
- `lookup_codes` 도구 (정적 데이터, DO 미사용)
- `wrangler dev` 로 로컬 검증 + MCP Inspector 연결

### Stage 2 — list_chargers_by_operator + find_chargers_nearby (별도 세션)
- ChargerInfo 타입 + zod 스키마
- DO SQLite 쿼리 (by_busi_id, by_busi_id_and_zcode, near_lat_lng)
- 두 도구 구현 + 단위 테스트
- 코드 테이블 룩업 (resolve_busi_id, resolve_sido)
- haversine + bbox 헬퍼

### Stage 3 — 나머지 4 도구 (별도 세션)
- `get_charger_status` (live fetch)
- `recent_status_changes` (live + 60s 인메모리 캐시)
- `search_chargers_by_region` (DO 쿼리)
- `get_station_details` (DO 쿼리 + 라이브 fallback)

### Stage 4 — Sync Worker (별도 세션)
- Cron Trigger 별도 worker
- data.go.kr 클라이언트 + redact + retry
- DO stub.fetch("internal://upsert") 로 UPSERT
- 매일 1회 자동 실행
- last_completed_page 영속 (DO sync_state 테이블)

### Stage 5 — 배포 + 검증
- `wrangler secret put SERVICE_KEY`
- `wrangler deploy`
- production URL 확보 후 Claude.ai Custom Connector 등록
- Phase 5 의 사용 예시 3 가지 자연어 검증
- Phase 9 보고서 마무리

## ChargerInventory DO API

Python `ChargerStore` 의 메서드를 1:1 매핑 (이름 동일):

```typescript
class ChargerInventory extends DurableObject {
  // writes
  upsertMany(rows: ChargerInfo[]): Promise<number>
  setState(key: string, value: string): Promise<void>

  // reads
  byStatId(statId: string): Promise<ChargerInfo[]>
  byBusiId(busiId: string, limit: number): Promise<ChargerInfo[]>
  byZcode(zcode: string, limit: number): Promise<ChargerInfo[]>
  byZscode(zscode: string, limit: number): Promise<ChargerInfo[]>
  nearLatLng(lat: number, lng: number, radiusKm: number, limit: number): Promise<ChargerInfo[]>
  byBusiIdAndZcode(busiId: string, zcode: string, limit: number): Promise<ChargerInfo[]>

  // meta
  totalCount(): Promise<number>
  lastSyncedAt(): Promise<Date | null>
}
```

스키마는 Phase 6 의 `ChargerStore` 와 정확히 동일 (PRIMARY KEY (stat_id, chger_id), 4 인덱스).

## 호환성 / 공존

- Python 코드 (`src/ev_mcp/`) 그대로 유지 — MCPB 사용자는 그대로 사용
- TS 코드는 `workers/` 안에서 독립 (자체 package.json, tsconfig, vitest)
- 코드 테이블 (`codes/*.json`) 은 양쪽이 공유 — Python 은 import, TS 는 빌드 시 import
- 같은 docx 스펙을 진실의 원천으로 유지

## 지표 / 검증 기준

| 단계 | 검증 |
|---|---|
| Stage 1 | `wrangler dev` 부팅, MCP Inspector 7 도구 표시, lookup_codes 7 카테고리 정상 응답 |
| Stage 2 | `list_chargers_by_operator(operator="채비")` → 0건 아님 (DO 에 seed 후) |
| Stage 3 | 7 도구 모두 wrangler dev 에서 응답. vitest 로 회귀 테스트 |
| Stage 4 | Cron Trigger 1회 실행 → DO 에 ~수천 행 (부분 sync). 영속 확인 |
| Stage 5 | production URL `https://ev-mcp.<account>.workers.dev/mcp` 에서 Claude 자연어 호출 정상 |

## 변경 이력
- 2026-05-07 Phase 9 시작, plan 작성
- 2026-05-07 Stage 2 완료 — DDL 분리 실행 (DO SQLite 한 statement 제약 해결), `ChargerInfo` TS 타입 + zod 스키마, `list_chargers_by_operator` + `find_chargers_nearby` 툴, wrangler dev 검증.
- 2026-05-07 아키텍처 분리 (옵션 2 채택) — `InventoryStore` 를 별도 plain DO 로 추출, `ChargerInventory` (McpAgent) 는 `idFromName("global")` stub 으로 RPC 위임. `wrangler.toml` 에 STORE 바인딩 + v2 마이그레이션 추가. 2-row seed → 새 MCP 세션에서 read 성공으로 cross-session 영속 확인.
- 2026-05-08 Stage 3a — `search_chargers_by_region` (region+district), `get_station_details` (stat_id) 추가. `byStatId/byZcode/byZscode` DO 메서드 + 5-tool 검증.
- 2026-05-08 Stage 3b — `EvChargerClient` (workers/src/client.ts) data.go.kr 라이브 클라이언트 (retry + redact + AbortController), `get_charger_status` + `recent_status_changes` (60s 인메모리 캐시) 추가. `fetch.bind(globalThis)` 로 Workers Illegal-invocation 회피. 실 API 호출 검증 (cache hit 11ms, 키 누출 없음). 7개 툴 모두 라이브.
- 2026-05-08 Stage 4 — `getChargerInfo` + `apiToChargerInfo` 매퍼 추가, 페이지·재개 가능한 sync 상태 머신 (`workers/src/sync.ts`) 구현. `scheduled` 핸들러를 같은 worker 에 추가 (별도 worker 대신 운영 단순화). 매분이 아닌 5분 cron (`*/5 * * * *`) — `pageSize=2000` 기준 253 페이지 ≈ 21시간 풀사이클. `/internal/sync` (수동 트리거) + `/internal/sync-status` (진단) 추가. 검증: tick#1 → page 1 (500 rows), tick#2 → page 2 (resume, +500 rows), MCP 툴이 실 sync 데이터(`ME174013` 낙성대동주민센터) 즉시 반환.
- 2026-05-08 Stage 5 (코드 준비) — `/internal/*` 토큰 게이트 강화: `DEV_SEED_TOKEN` 미설정 시 503 (안전 기본값). `/internal/sync-status` 도 게이트에 포함. `wrangler deploy --dry-run` 통과 (번들 1.65 MiB raw / **301.60 KiB gzipped**, free-tier 1MB 한도 안). `workers/DEPLOY.md` 작성 — 사용자 Cloudflare 계정 액션 단계별 정리.

## 최종 상태 (Phase 9 마무리)

### 코드 ✓
- 7 MCP 툴 모두 Workers 에 포팅, 라이브 검증 완료
- 두-DO 아키텍처 (per-session McpAgent + global InventoryStore)
- data.go.kr 라이브 클라이언트 (retry/redact/timeout)
- Cron-driven 재개 가능한 sync 상태 머신
- 토큰 게이트된 admin 엔드포인트 3개

### 사용자 액션 대기
- `wrangler login` (인터랙티브 OAuth)
- `wrangler secret put SERVICE_KEY` + `wrangler secret put DEV_SEED_TOKEN`
- `wrangler deploy`
- Claude.ai Settings → Connectors → Add custom connector → `https://ev-mcp.<account>.workers.dev/mcp`
- 자연어 스모크 테스트 3종 (DEPLOY.md §6)

### 알려진 한계 / 후속 검토
- `find_chargers_nearby` 가 lat/lng-only — Phase 5 의 address 기반 질의는 동작하지 않음. VWorld 지오코더 통합은 Phase 10+ 결정.
- `recent_status_changes` 첫 호출 5–30s — upstream 지연. 캐시는 ~10–50ms.
- Free plan scheduled CPU 30s 제약 → `pagesPerTick=1`. paid plan 은 `crons = ["0 18 * * *"]` 단일 실행 가능.
- `/internal/*` 는 토큰만으로 보호. 실제 운영에선 Cloudflare Access 또는 IP allow-list 추가 권장.
