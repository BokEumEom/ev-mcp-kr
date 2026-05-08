# Workers 배포 가이드 (Phase 9 Stage 5)

ev-mcp 의 Cloudflare Workers + Durable Objects 배포는 사용자 Cloudflare 계정에서 직접 실행해야 하는 단계가 절반입니다. 이 문서는 그 절차를 정리한 runbook 입니다.

## 0. 사전 준비

- Cloudflare 계정 (무료)
- `data.go.kr` 발급 `SERVICE_KEY` (URL-encoded 형태 그대로)
- `workers/` 에서 `npm install` 완료

```bash
cd workers
npx wrangler --version   # 4.x 확인
```

## 1. 로그인

```bash
cd workers
npx wrangler login
```

브라우저로 OAuth 동의창이 뜸. 셸 환경이라면 `! npx wrangler login` 으로 사용자가 직접 실행.

## 2. 시크릿 등록

```bash
cd workers
npx wrangler secret put SERVICE_KEY
# stdin 으로 키 붙여넣기

npx wrangler secret put DEV_SEED_TOKEN
# 임의의 긴 랜덤 문자열. 미설정 시 모든 /internal/* 가 503 반환 — 의도된 안전 기본값.
```

`VWORLD_KEY` (지오코더) 는 현 시점 워커 배포에서 사용하지 않음. Phase 9 Stage 3 의 `find_chargers_nearby` 는 lat/lng 만 받고 address 입력은 미지원 (Stage 6+ 에서 결정).

## 3. 배포

```bash
cd workers
npx wrangler deploy
```

처음 배포 시 워커 URL 이 출력됨 (`https://ev-mcp.<account-subdomain>.workers.dev`). 이 URL 을 메모.

## 4. 1차 검증

```bash
WORKER_URL="https://ev-mcp.<account-subdomain>.workers.dev"
TOKEN="<DEV_SEED_TOKEN 값>"

# 헬스체크
curl -s "$WORKER_URL/health"
# {"ok":true,"version":"0.1.0","platform":"cloudflare-workers"}

# sync 트리거 (1 페이지 수동 실행)
curl -s -X POST "$WORKER_URL/internal/sync" \
  -H "x-dev-seed-token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pageSize":2000,"pagesPerTick":1}'

# sync 진행 확인
curl -s "$WORKER_URL/internal/sync-status" \
  -H "x-dev-seed-token: $TOKEN"
# total_pages 와 last_completed_page 가 갱신되어 있어야 함
```

cron `*/5 * * * *` 가 활성화돼 있으므로 그대로 두면 ~21시간 안에 풀 사이클 완료. `total_rows_in_store` 가 50만 부근까지 증가.

## 5. Claude.ai Custom Connector 등록

Claude.ai 웹 (claude.ai) 또는 데스크톱 앱에서:

1. Settings → Connectors → "Add custom connector"
2. **URL**: `https://ev-mcp.<account-subdomain>.workers.dev/mcp` (트레일링 슬래시 없음)
3. **Transport**: Streamable HTTP
4. 인증 없음 (현 시점 — 추후 Phase 10+ 에서 OAuth 검토)
5. 저장 후 새 대화에서 "도구" 토글 → ev-mcp 활성화

## 6. 자연어 스모크 (Phase 5 사용 예시 3종 — Stage 3 매핑)

`find_chargers_nearby` 시그니처가 lat/lng-only 로 변경됐기 때문에 Phase 5 의 address 기반 질문은 약간 다르게 트리거됩니다.

| 자연어 질문 | 호출 도구 | 기대 |
|---|---|---|
| "위도 37.4979, 경도 127.0276 반경 1km 사용 가능한 충전기" | `find_chargers_nearby(lat=37.4979, lng=127.0276, radius_km=1, available_only=true)` | 강남역 주변 가용 충전기 거리순 |
| "충전소 ME174050 의 03 번 충전기 지금 상태?" | `get_charger_status(stat_id="ME174050", chger_id="03")` | `stat_label` + `stat_upd_dt` ISO |
| "환경부가 운영하는 서울 강남구 충전기 5개" | `list_chargers_by_operator(operator="환경부", region="서울특별시", limit=5)` 또는 `search_chargers_by_region(region="서울", district="강남구") + 운영기관 필터` | 강남구 ME 운영 충전기 |

응답 latency:
- DO 쿼리 도구 (4종): <100 ms
- 라이브 도구 (`get_charger_status`, `recent_status_changes` 첫 호출): 5–30 s
- `recent_status_changes` 두 번째 호출 (60s 캐시 윈도): 10–50 ms

## 7. 운영

### 수동 sync 트리거
```bash
curl -X POST "$WORKER_URL/internal/sync" \
  -H "x-dev-seed-token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pagesPerTick":3}'
```

### sync 일시 중단
`wrangler.toml` 의 `[triggers]` 블록 주석 처리 → `wrangler deploy`. 앱 자체는 그대로 동작.

### 롤백
```bash
cd workers
npx wrangler deployments list
npx wrangler rollback <deployment-id>
```

### 로그 실시간
```bash
cd workers
npx wrangler tail
```

`SERVICE_KEY` 가 로그에 노출되는지 확인:
```bash
npx wrangler tail --format pretty | grep -c "<key 처음 12자>"
# 0 이어야 함
```

## 8. 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| `/internal/*` → 503 | `DEV_SEED_TOKEN` 미설정. `wrangler secret put DEV_SEED_TOKEN` |
| `tools/call` → "SERVICE_KEY 가 설정되지 않았습니다" | `wrangler secret put SERVICE_KEY` 누락 또는 오타 |
| 첫 sync tick 이 504 timeout | upstream `data.go.kr` 일시 다운. cron 이 5분 뒤 자동 재시도. `pageSize` 더 줄여서 (`500`) 수동 트리거도 가능 |
| `recent_status_changes` 가 매우 느림 (>60s) | upstream 일시 부하. `period=1` 으로 줄이거나 잠시 후 재시도 |
| Claude.ai 에서 도구 목록이 안 뜸 | URL 끝의 트레일링 슬래시 확인 (`/mcp` 정확히), Transport=Streamable HTTP, 도구 토글 활성화 |

## 9. 알려진 제약

- **세션별 McpAgent DO**: agents-mcp 의 기본 라우팅. transport state 가 세션 격리됨 — 데이터는 단일 `InventoryStore` 가 모두 가짐 (`idFromName("global")`).
- **Free plan scheduled CPU 30s**: 한 tick 에 처리 가능한 페이지 수 제약. `pagesPerTick=1`, cron `*/5 * * * *` 로 분산. paid plan 은 single 일 1회 cron 으로 전환 가능 (`crons = ["0 18 * * *"]`).
- **`/internal/*` 자체가 admin surface**: 토큰만으로 보호. 더 강한 방어가 필요하면 Cloudflare Access 또는 IP allow-list 추가.
- **Python 스택 코드는 그대로 유지**: `src/ev_mcp/` 는 MCPB (Phase 7) 사용자용. Workers 와 같은 코드 테이블 (`codes/*.json`) 공유.
