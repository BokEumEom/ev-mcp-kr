# Phase 10 보고 — DuckDB 분석 사이드카 (Stage 10.2 + 10.3 + 10.4)

**기간:** 2026-05-11 (1일)
**범위:** ADR-001 의 결정에 따라 DuckDB 기반 분석 사이드카를 도입. 기존 7개 lookup 툴은 그대로 두고, Parquet 위에서 GROUP BY/AVG 분석을 수행하는 새 MCP 툴 2개 (`analyze_operator_health`, `regional_density`) 추가. Stage 10.1 (Workers R2 export) 는 사용자 R2 준비 후 별도 사이클.
**검증:** pytest 123건 / ruff clean / mypy strict clean / 시크릿 정적 검사 0건. 실 운영 Parquet(508,060 rows) 자연어 스모크 3건 통과 + Stage 10.4 에서 데이터 품질 정의 오류 1건 발견·수정.

## 요약 (3줄)

ADR-001 (DuckDB 분석 사이드카) 의 Stage 10.2 + 10.3 을 한 사이클에 구현. 도메인 모델 추가, `AnalyticsClient` (DuckDB lazy connect + local/R2 source 추상화 + 시크릿 마스킹), 새 MCP 툴 2개, 18개 회귀 테스트. 핵심 발견은 **Stage 10.4 (자연어 스모크) 가 ADR 의 비가동 정의 오류를 즉시 잡았다**는 점 — `stat='9'` 는 "운영중지" 가 아니라 "모니터링 미연동" 이라는 게 실 데이터에서 드러나, `DOWNTIME_CODES = ("1","4","5")` 로 재정의하고 `OperatorHealthRow` 에 `unmonitored_count` / `unmonitored_ratio` 필드를 분리 신설. Stage 10.1 (R2 export) 는 미진행 — Stage 10.2 가 로컬 Parquet 으로도 완전 동작하므로 가치 입증 후 R2 결정 가능.

## 핵심 결정

- **ATTACH mode 의도적 미사용.** PoC (`scratch/duckdb_poc.py`) 에서 SQLite ATTACH 가 분석 워크로드에 일관성 없음 확인 (Query A 에서는 SQLite 보다 2.2× 느림). 운영 코드는 Parquet 만 query.
- **`{source}` placeholder 강제.** `AnalyticsClient.query` 가 SQL 템플릿에서 `{source}` 를 `read_parquet('...')` 로 치환. 호출 측이 source URI 를 직접 만들지 않게 만들어 자격증명·경로 누출 차단.
- **검증 순서 (bucket → connect → query).** R2 설정 누락(bucket missing)이 자격증명 누락(creds missing)보다 먼저 잡히도록 `_source_expr` 을 `_ensure_connected` 전에 호출. 작은 흐름이지만 에러 메시지 정확성에 큰 차이.
- **분석 컨텍스트 분리.** `ToolContext` 에 `analytics: AnalyticsClient` 추가하지만 lazy connect — 분석 툴이 호출될 때만 in-memory DuckDB 생성. 일반 lookup 요청은 영향 0.
- **Stage 10.4 의 비가동 정의 재조정 (운영 발견).** 처음 정의했던 `DOWNTIME_CODES=("4","5","9")` 는 false alarm 양산 (미래에스디 100%, 에너넷 100% 등). 실제 의미는 `stat='9'` = 운영자가 상태 보고 안 함 ≠ 충전기 운영중지. 재정의 후 `DOWNTIME_CODES=("1","4","5")` (통신이상/운영중지/점검중) + `UNMONITORED_CODE="9"` 별도 추적. 8개 새 회귀 테스트 + fixture stat='9' 케이스 추가로 회귀 방어.

## 추가/변경된 모듈

### 신규 (`src/ev_mcp/`)
| 파일 | 역할 | 라인 |
|---|---|---|
| `analytics.py` | `AnalyticsClient` — DuckDB lazy connect, local/R2 source 추상화, `_redact` 시크릿 마스킹, `{source}` placeholder 강제 | 168 |
| `tools/analytics_operator_health.py` | `analyze_operator_health` — 운영자별 비가동률 + 미연동률 top N | 116 |
| `tools/analytics_regional_density.py` | `regional_density` — 시도/시군구 단위 충전기 밀도 + DC 비율 | 102 |

### 신규 (`tests/`)
| 파일 | 테스트 수 | 무엇을 검증 |
|---|---|---|
| `test_analytics.py` | 7 | source 검증 (local 누락, r2 bucket 누락, 알 수 없는 source) / placeholder 강제 / 시크릿 마스킹 / close() idempotent |
| `test_tools_analytics_operator_health.py` | 6 | 해피 패스 / min_chargers 필터 / limit 캡 / 잘못된 입력 / del_yn='Y' 제외 / **unmonitored 분리 회귀 (Stage 10.4)** |
| `test_tools_analytics_regional_density.py` | 5 | sigungu 그루핑 / sido 그루핑 / 잘못된 group_by / 잘못된 limit / del_yn='Y' 제외 |

### 변경
| 파일 | 변경 |
|---|---|
| `pyproject.toml` | `duckdb>=1.5` 추가 (사용자 컨펌 후) |
| `settings.py` | `snapshot_path` / `snapshot_source` / R2 자격증명 4개 (`SecretStr | None`) 추가 |
| `.env.example` | 새 필드 5개 동기화 (빈 값 + 한 줄 코멘트) |
| `context.py` | `ToolContext.analytics: AnalyticsClient` 필드 추가 |
| `domain.py` | `OperatorHealthRow` (8 필드, unmonitored 분리), `RegionalDensityRow` (8 필드) 신설 |
| `server.py` | 새 MCP 툴 2개 등록 (`readOnlyHint=True`), lifespan teardown 에 `analytics.close()`, build_server 가 `build_analytics_client` 호출 |
| `tests/conftest.py` | `analytics_snapshot` fixture (DuckDB 로 작은 Parquet 생성) + `analytics` fixture + `ctx` fixture 에 analytics 주입 |
| `tests/test_tools_nearby.py` | 직접 `ToolContext()` 생성 위치에 `analytics=AnalyticsClient(settings)` 추가 |
| `tests/test_server.py` | tool 카운트 어설션 7개 → 9개 (analytics 2개 추가) + Phase 표시 |
| `docs/PLAN.md` | Phase 10 섹션 Stage 10.2/10.3 ✅ 진행 표시 + 진행 이력 |
| `docs/adr/ADR-001-duckdb-analytics.md` | "운영 결과" 섹션 추가 (Stage 10.4 의 정의 보정 발견 박제) |

### 보존 (Phase 1~9 영향 없음)
- 기존 7개 MCP 툴 — 시그니처·동작 변경 없음
- `src/ev_mcp/store.py` (SQLite 영속 store) — 그대로 운영
- `workers/` — Stage 10.1 진입 전까지 영향 없음

## 아키텍처

```
                       Claude.ai / Claude Desktop
                                │
                                ▼
       ┌───────────────────────────────────────────────────┐
       │  FastMCP server (build_server)                    │
       │                                                   │
       │  ToolContext                                      │
       │   ├─ client        → data.go.kr 라이브 호출        │
       │   ├─ store         → SQLite 영속 (Phase 6)         │
       │   ├─ caches        → 60s 상태 캐시 (Phase 2)       │
       │   └─ analytics     → DuckDB lazy (Phase 10) ⭐     │
       │                                                   │
       │  Tools (총 9개)                                    │
       │   ├─ lookup tools × 7 (Phase 1~9, 무변경)          │
       │   └─ analytics tools × 2 (Phase 10)               │
       │       ├─ analyze_operator_health                  │
       │       └─ regional_density                         │
       └─────────────────────────┬─────────────────────────┘
                                 │ read_parquet via {source}
                                 ▼
                ┌────────────────────────────┐
                │ Parquet snapshot           │
                │  • local: scratch/...      │ ← 현재 운영 (Stage 10.2)
                │  • r2:    s3://bucket/...  │ ← Stage 10.1 진입 후
                └────────────────────────────┘
```

분석 query 는 in-memory DuckDB → `read_parquet('{source}')` → 결과만 Python 으로. DuckDB attach mode 는 의도적으로 미사용 (ADR-001 Alt-3).

## 자연어 스모크 결과 (508,060 rows, 실 운영 Parquet)

### Q1. "운영자별로 충전기가 가장 자주 고장나는 곳 top 10"

```
운영자                코드   총     비가동률   미연동률
─────────────────────────────────────────────────────
엘쓰리일렉트릭파워     L3     138    84.1%     8.0%
차지인                EZ     2,854  72.5%     1.2%
SG생활안전            SZ     989    52.3%     8.0%
이지차저              EC     13,809 38.3%     0.2%
한솔엠에스            HU     1,457  35.7%     1.4%
```

비가동률(`stat IN ('1','4','5')`) 과 미연동률(`stat='9'`) 분리 노출. 미연동률이 모두 1~8% 수준이라 비가동률 해석의 신뢰도가 높음을 자연어 응답에 함께 활용 가능.

### Q2. "충전기가 가장 많은 시군구 top 10, 급속 비율도"

```
시도         시군구       충전기   운영자   DC비율
─────────────────────────────────────────────────
경기도       용인시        14,607    66    6.5%
경기도       화성시        13,550    73    7.3%
경기도       수원시        12,567    59   11.3%
...
```

### Q3. "광역시도 단위로도"

```
시도            코드   충전기    운영자   DC비율
─────────────────────────────────────────────────
경기도          41    150,680   108    8.4%
서울특별시      11     74,039    99    7.5%
...
경상북도        47     21,890    82   18.6%   ← 비도시권 고DC
강원특별자치도  51     17,067    77   16.1%
```

**도시 vs 비도시의 DC 비율 격차** 가 즉시 드러나는 인사이트. 기존 lookup 툴로는 절대 불가능했던 응답.

## 검증

- pytest: **123건 통과** (분석 신규 18건 + 운영 105건 회귀 0)
- ruff: clean
- mypy strict: clean
- 시크릿 정적 검사: 0건 (R2 자격증명, SERVICE_KEY 패턴)
- 자연어 스모크: 3건 통과 (`scratch/smoke_analytics.py`)
- 의존성 추가: `duckdb>=1.5` (사용자 컨펌 후)

## 회귀 방어 (이 Phase 가 추가한 테스트)

1. **`test_query_requires_source_placeholder`** — `{source}` 누락 시 명확 에러. 호출 측이 SQL 에 source URI 를 직접 넣는 실수 방지.
2. **`test_missing_local_snapshot_raises` / `test_r2_without_credentials_raises` / `test_unknown_source_raises`** — 설정 누락 케이스 모두 명확 메시지로 raise. 시크릿 누출 없이.
3. **`test_redact_masks_known_secrets`** — `_redact` 가 R2 secret 값을 실제로 `***` 로 치환. 향후 누군가 logger 추가 시 회귀 방어.
4. **`test_unmonitored_separate_from_downtime`** ⭐ — Stage 10.4 의 데이터 품질 발견 박제. ME fixture 의 stat='9' 15건이 `downtime_count` 가 아니라 `unmonitored_count` 에 들어가는지 검증. 미래에 누가 `DOWNTIME_CODES` 에 `'9'` 다시 넣으면 즉시 fail.
5. **`test_del_yn_y_excluded` × 2** — 두 분석 툴 모두 del_yn='Y' 행 제외 검증. WHERE 절 누락 회귀 방어.

## 다음 단계

### Stage 10.1 — Workers R2 export (사용자 R2 준비 후 진입)

**사용자 액션 (사이클 진입 전):**
```bash
cd workers
npx wrangler r2 bucket create ev-mcp-snapshots
# Cloudflare 대시보드 → R2 → "Manage R2 API Tokens" → 토큰 발급
npx wrangler secret put R2_ACCOUNT_ID
npx wrangler secret put R2_ACCESS_KEY_ID
npx wrangler secret put R2_SECRET_ACCESS_KEY
```

**구현 계획 (워커 측):**
- `workers/wrangler.toml` 에 R2 bucket binding 추가 (`SNAPSHOTS`)
- `workers/src/snapshot.ts` 신설 — DO SQL 의 chargers 전체를 Parquet 으로 직렬화 + ZSTD + R2 PUT (예상 14.4MB/일)
- `workers/src/sync.ts` 의 cycle 완료 시점에서 1회 export 호출
- vitest: R2 mock 으로 export 단위 테스트

**Python 측 액션:**
- `.env` 에 R2 자격증명 4개 채우고 `SNAPSHOT_SOURCE=r2` 로 전환
- `SNAPSHOT_PATH` 는 unused 가 됨 (또는 fallback 으로 유지)

### Stage 10.4 의 잔여 (선택)

R2 사용량 모니터링 — 현재 수동(Cloudflare 대시보드). 후속 Phase 에서 자동화 검토 (Stage 10.4 의 R2 사용량 알람).

### ADR-001 의 트리거 재검토 항목

PoC 검증 후 운영 진입했으므로 다음 조건이 발생하면 ADR 재검토:
- R2 무료 tier 50% 초과
- DuckDB 호출 빈도 일 10만+
- 분석 MCP 툴이 5개+ 로 증가 (Python store 통합 검토)

## 변경 이력

- 2026-05-11 — Phase 10 Stage 10.2 + 10.3 + 10.4 한 사이클 완료. ADR-001 의 결정에 따른 첫 운영 구현. Stage 10.4 자연어 스모크에서 데이터 품질 정의 오류 발견·수정. Stage 10.1 (R2 export) 는 사용자 R2 준비 후 별도 사이클.
