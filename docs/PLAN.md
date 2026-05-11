# Plan: Korean EV Charging Station MCP Server (Claude Remote Connector)

**Date:** 2026-04-30
**Working dir:** `/home/bokeum/ai/ev_mcp`
**Source spec:** `한국환경공단_전기자동차 충전소 정보_OpenAPI활용가이드_v1.23.docx`
**Reference:** Claude Remote MCP Server Submission Guide (support.claude.com/ko/articles/12922490)

---

## Context

The Korea Environment Corporation (한국환경공단) publishes a public REST OpenAPI for EV charging station info and live status (`http://apis.data.go.kr/B552584/EvCharger`). Two operations: `getChargerInfo` (location, type, hours, operator, ~30 fields) and `getChargerStatus` (live charger state, last charge times). Auth is a single server-side `serviceKey` issued by data.go.kr. Data is public.

The goal is to expose this API as a **remote MCP server** that any Claude user can register as a connector and query in natural language ("내 위치 근처에 사용 가능한 급속 충전기 있어?"). The deliverable is a hosted HTTPS endpoint + a GitHub repo, submitted to Claude's MCP directory.

---

## Goals & Non-Goals

**Goals**
- 5–7 value-add MCP tools that map intent to API calls (not 1:1 endpoint passthrough).
- Production-ready remote MCP server: Streamable HTTP, HTTPS, CORS, safety annotations.
- Server holds the data.go.kr `serviceKey` as a secret. **No user auth** (no OAuth required because the MCP server itself does not gate user-specific data).
- Submit to Claude connector directory.

**Non-goals**
- No user-supplied API keys / OAuth / per-user quotas in v1.
- No write operations (this API is read-only).
- No mobile app, no web UI.
- No custom regional logic beyond what the spec defines (zcode/zscode/kind are pass-through).

---

## Premises (must agree before execution)

1. The data is public read-only → connector is **no-auth MCP**. Claude's submission guide makes OAuth mandatory **only when auth is needed**; no-auth servers are valid in the directory.
2. data.go.kr `serviceKey` lives only as a server env var; it is never returned in tool responses.
3. The Korean API supports up to 9999 rows/page; total stations (~12k–20k) makes bulk-prefetch viable for the info endpoint.
4. Hosting on **Render** (long-lived container, FastMCP/uvicorn) is the right call. Cloudflare Workers Python is still beta and lacks the asyncio/stdlib surface FastMCP relies on. Workers stays on the roadmap for when Python GAs.
5. Token budget: each tool response stays under 25,000 tokens; results are paginated and trimmed.

---

## Architecture

```
                       ┌──────────────────────────────────────┐
   Claude.ai user  →   │  Render container (HTTPS, ko-region) │
   Claude connector    │  ┌────────────────────────────────┐  │
                       │  │ FastMCP 2.x app                │  │
                       │  │  • Streamable HTTP /mcp        │  │
                       │  │  • CORS (claude.ai, claude.com)│  │
                       │  │  • Safety annotations          │  │
                       │  │  • In-memory cache             │  │
                       │  │     - station_info: 24h TTL    │  │
                       │  │     - status: 60s TTL          │  │
                       │  │  • httpx client → data.go.kr   │  │
                       │  └────────────────────────────────┘  │
                       │     env: SERVICE_KEY (secret)        │
                       └──────────────────────────────────────┘
                                    │
                                    ▼
                http://apis.data.go.kr/B552584/EvCharger
                  • getChargerInfo  (info fields, ~30)
                  • getChargerStatus (state + timestamps)
```

---

## Tech Stack (locked)

- **Language:** Python 3.12
- **Framework:** [FastMCP 2.x](https://github.com/jlowin/fastmcp) (`fastmcp>=2.0`)
- **HTTP client:** `httpx` (async)
- **Coordinate math:** `geopy` (haversine) — pure Python, no C extensions
- **Optional geocoding:** VWorld (`https://api.vworld.kr`) — free Korean government geocoder; fall back gracefully if unavailable
- **Server:** uvicorn + Starlette (FastMCP default)
- **Container:** Dockerfile, `python:3.12-slim`
- **Host:** Render (Standard plan, single instance, ko-equivalent region = Singapore until Render adds Seoul)
- **Tests:** pytest + respx (httpx mocks)
- **Lint/format:** ruff + mypy

---

## Tool Spec (5–7 tools, all `readOnlyHint: true`)

> All tools return Pydantic-modeled JSON. Korean labels are preserved in user-facing fields. Codes are translated server-side (e.g., `stat: "2"` → `status_code: 2, status_label: "사용가능"`).

### 1. `find_chargers_nearby`
Find chargers near a coordinate or address. **Most common user intent.**
```python
def find_chargers_nearby(
    lat: float | None = None,
    lng: float | None = None,
    address: str | None = None,         # geocoded via VWorld if lat/lng absent
    radius_km: float = 2.0,             # max 20
    charger_type: list[str] | None = None,  # e.g. ["04", "06"] DC combo / multi
    available_only: bool = False,       # filter stat == 2
    limit: int = 20,
) -> list[ChargerNearby]
```
Backed by cached station_info; live status merged from cached status (60s TTL).

### 2. `get_charger_status`
Live status for a specific charger.
```python
def get_charger_status(stat_id: str, chger_id: str) -> ChargerStatus
```
Bypasses cache; hits `getChargerStatus` directly with `statId`/`chgerId`.

### 3. `search_chargers_by_region`
Browse by 시도/시군구.
```python
def search_chargers_by_region(
    sido: str,                  # "서울특별시" or zcode "11"
    sigungu: str | None = None, # "강남구" or zscode "11680"
    charger_type: list[str] | None = None,
    available_only: bool = False,
    limit: int = 50,
) -> list[ChargerSummary]
```

### 4. `list_chargers_by_operator`
Filter by operator (busiId).
```python
def list_chargers_by_operator(
    operator: str,              # "환경부" or busiId "ME"
    region: str | None = None,  # optional sido
    limit: int = 50,
) -> list[ChargerSummary]
```

### 5. `get_station_details`
Full info for one station (all fields, all chargers at the station).
```python
def get_station_details(stat_id: str) -> StationDetails
```

### 6. `recent_status_changes`
What changed in the last N minutes (the API's native `period` param, 1–10 min).
```python
def recent_status_changes(
    period_min: int = 5,
    region: str | None = None,
    limit: int = 50,
) -> list[StatusChange]
```

### 7. `lookup_codes`
Code-table reference (sido, charger_type, stat, busiId, kind). Returned as MCP tool **and** exposed as MCP **resources** (`mcp://codes/sido`, etc.) so Claude can read them without a tool call.
```python
def lookup_codes(category: Literal["sido","sigungu","charger_type","stat","busi_id","kind"]) -> dict[str, str]
```

---

## Data Flow & Caching

| Cache key | TTL | Refresh trigger | Stored |
|---|---|---|---|
| `station_info` (full list) | 24h | first request after expiry; background refresh task | dict[stat_id → list[Charger]] |
| `status` (per region) | 60s | per-tool-call basis | dict[(stat_id, chger_id) → status] |
| Code tables | static | shipped as JSON in repo | imported once at boot |

Cold start: bulk-fetch `getChargerInfo` with `numOfRows=9999` paginated until `totalCount` reached. Expect ~3–5 pages, ~5–10 seconds. Subsequent requests served from RAM.

---

## Hosting & Deployment

- **Render** Web Service, Docker runtime, Standard plan ($25/mo, always-on, 2GB RAM).
- Region: Singapore (closest to Korea until Seoul added).
- HTTPS + cert: managed by Render.
- Custom domain: `ev-mcp.<your-domain>` (TBD by user).
- Secrets: `SERVICE_KEY` set via Render dashboard.
- CORS allowlist: `https://claude.ai`, `https://claude.com`, `http://localhost:6274` (for local Inspector debugging).
- IP allowlist (optional): Claude's MCP IPs, per submission guide.
- Health check: `GET /health` returns `{"ok": true, "cache_age_s": N}`.

CI/CD: GitHub Actions on push to `main` → build & push image → Render auto-deploys via webhook.

---

## Project Layout

```
ev_mcp/
├── pyproject.toml              # fastmcp>=2.0, httpx, geopy, pydantic
├── Dockerfile                  # python:3.12-slim, uvicorn entry
├── render.yaml                 # Render Blueprint
├── .github/workflows/ci.yml    # ruff, mypy, pytest, build image
├── README.md                   # setup, tools, examples, privacy
├── docs/
│   ├── PRIVACY.md              # required by Claude submission
│   └── SUPPORT.md              # required by Claude submission
├── src/ev_mcp/
│   ├── __init__.py
│   ├── server.py               # FastMCP app, tool registration, CORS
│   ├── client.py               # httpx-based data.go.kr client
│   ├── cache.py                # in-memory TTL cache
│   ├── geocode.py              # VWorld geocoder + fallback
│   ├── tools/
│   │   ├── nearby.py           # find_chargers_nearby
│   │   ├── status.py           # get_charger_status, recent_status_changes
│   │   ├── region.py           # search_chargers_by_region
│   │   ├── operator.py         # list_chargers_by_operator
│   │   ├── station.py          # get_station_details
│   │   └── codes.py            # lookup_codes + resources
│   ├── models.py               # Pydantic types: Charger, Station, StatusChange
│   ├── codes/                  # static JSON code tables
│   │   ├── sido.json
│   │   ├── sigungu.json        # zscode → name
│   │   ├── charger_type.json
│   │   ├── stat.json
│   │   ├── busi_id.json        # ~180 operators
│   │   └── kind.json
│   └── settings.py             # pydantic-settings, SERVICE_KEY
└── tests/
    ├── test_client.py
    ├── test_cache.py
    ├── test_tools_*.py
    └── fixtures/
        └── sample_responses.json
```

---

## Implementation Phases

### Phase 1 — Skeleton & client (1–2 days)
1. `pyproject.toml`, lockfile (uv or pip-tools).
2. `client.py`: typed httpx wrapper for `getChargerInfo` and `getChargerStatus`. Handle XML/JSON, retries, `resultCode != "00"` errors.
3. `models.py`: Pydantic models for every documented field (full, not partial — boil the lake).
4. `codes/*.json`: extract every code table from the docx (busiId ~180 entries, sigungu ~250+ entries, charger_type 11 entries, stat 8, sido 17, kind/kindDetail).
5. Unit tests with `respx` for the client + sample response fixtures.

### Phase 2 — Cache & tools (2–3 days)
1. `cache.py`: TTLCache with async refresh-ahead.
2. Tools: implement 7 tools above, each in its own file. Each tool: typed inputs (Pydantic), typed outputs, docstring including realistic examples (Claude reads docstrings as tool descriptions).
3. `geocode.py`: VWorld client + fallback to lat/lng-only mode if `VWORLD_KEY` unset.
4. Tool tests: every tool covered, edge cases (empty results, invalid codes, status fail).

### Phase 3 — MCP server wiring (1 day)
1. `server.py`: FastMCP app, register all tools with `readOnlyHint=True`, register code-table resources.
2. CORS middleware, allowlist origins.
3. `/health` endpoint.
4. Logging to `logs/ecs-mcp-server.log` (JSON lines, request_id, tool, latency).
5. Local Inspector smoke test (`mcp inspect http://localhost:8000/mcp`).

### Phase 4 — Containerize & deploy (1 day)
1. Dockerfile (multi-stage, non-root user, healthcheck).
2. `render.yaml` Blueprint.
3. GitHub Actions: lint + test + image build on PR; deploy on `main`.
4. Set `SERVICE_KEY` in Render dashboard.
5. Custom domain + DNS CNAME.

### Phase 5 — Submission package (0.5 day)
1. `README.md`: description, 7 tools with examples, setup, privacy link, support link.
2. `docs/PRIVACY.md`: what we collect (none), what we proxy, retention.
3. `docs/SUPPORT.md`: GitHub issues + email.
4. Three end-to-end usage examples in README (per submission requirement).
5. Submit Google Form to Claude's MCP directory.

**Total estimate (Phase 1~5):** ~6 days end-to-end.

> Phase 6~9 는 사후에 추가된 확장 트랙. 각 Phase 보고서 (`docs/PHASE6.md` ~ `docs/PHASE9.md`) 가 진실의 원천이고, 본 PLAN.md 의 Phase 섹션은 초기 출시(1~5) + 새로 합의된 확장(10+) 만 다룬다.

### Phase 10 — DuckDB analytics sidecar (2~3 days)

**근거 ADR:** `docs/adr/ADR-001-duckdb-analytics.md`. PoC (`scratch/duckdb_poc.py`) 결과 — Parquet 위에서의 분석 쿼리가 SQLite 대비 74× 빠르고, 압축률 17.8× (257MB→14.4MB), R2 비용 무료 tier 의 5% 미만.

**목표:** 기존 7개 lookup 툴을 그대로 둔 채 **분석 전용 MCP 툴 1~2개**를 Python 측에 추가. 시계열 누적(R2 일별 Parquet 스냅샷)으로 트렌드 질문 가능하게.

**Non-goals (Phase 10):**
- Workers 또는 Python SQLite 스토어 폐기 X
- Workers 내부에서 DuckDB 실행 X (ADR Alt-1 거부)
- DuckDB ATTACH mode 운영 사용 X (ADR Alt-3 거부)
- 분석 툴 5개+ 일괄 추가 X (먼저 1~2개로 가치 확인 후 확장)

#### Stage 10.1 — Workers daily R2 Parquet export (1 day)
1. `wrangler.toml` 에 R2 bucket binding 추가 (`SNAPSHOTS`). 사용자가 `wrangler r2 bucket create ev-mcp-snapshots` 직접 실행.
2. `workers/src/snapshot.ts` 신설 — `exportSnapshot(env, date)`: DO SQL 의 `chargers` 테이블 전체를 Parquet 으로 직렬화 + ZSTD 압축 + R2 PUT (`chargers_YYYY-MM-DD.parquet`).
3. `workers/src/sync.ts` 의 cycle 완료 시점(`last_completed_page == total_pages`)에서 1회 export 호출. 실패 시 다음 cycle 에서 재시도, 3회 실패면 sync_state 에 마지막 에러 기록.
4. vitest: export 단위 테스트 (R2 mock + Parquet schema 검증) + sync 통합 테스트.

#### Stage 10.2 — Python analytics 모듈 + DuckDB 연결 (0.5~1 day) ✅ 2026-05-11
1. `pyproject.toml` 에 `duckdb` 의존성 추가 — **사용자 컨펌 필요**.
2. `src/ev_mcp/analytics.py` 신설 — `AnalyticsClient`: DuckDB in-memory + `httpfs` extension + R2 자격증명 (S3 호환).
3. `Settings` 에 `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` (SecretStr) 추가. `.env.example` 빈 값 + 한 줄 코멘트.
4. `client._redact()` 와 동등한 R2 자격증명 마스킹 헬퍼.
5. pytest: `httpfs` mock 으로 read_parquet 호출 검증, 자격증명 누출 회귀 테스트.

#### Stage 10.3 — 새 분석 MCP 툴 1~2개 (1 day) ✅ 2026-05-11
1. `src/ev_mcp/tools/analytics_operator_health.py` — `analyze_operator_health` (운영자별 비가동률 top N).
   - 입력: `limit: int = 10`, `min_chargers: int = 100`, `days_back: int = 1` (스냅샷 1일 = 최신 1개)
   - 출력: Pydantic `OperatorHealthRow` list
2. `src/ev_mcp/tools/analytics_regional_density.py` — `regional_density` (시군구별 충전기 밀도 + 운영자 수 + DC 비율).
3. `server.py` 등록 (`readOnlyHint=True`).
4. 각 툴 3 테스트 (해피 / 빈결과 / 잘못된 입력).
5. 도크스트링 예시: "엘에스이링크 같은 운영자 중 가장 자주 고장나는 곳", "강남구 충전기 밀도".

#### Stage 10.4 — 보고 + 모니터링 (0.5 day)
1. `docs/PHASE10.md` — 보고서 (Phase 9 톤 참고).
2. R2 사용량 모니터링 — 현 시점 수동 (CF 대시보드). 자동화는 후속 Phase.
3. ADR-001 상태를 "Accepted" → 실제 운영 결과 반영 (성공/조정/롤백) 한 줄 추가.

**검증 (Phase 10 종료 게이트):**
- vitest + pytest 그린 (회귀 0)
- 실 R2 export 1회 성공 + 분석 툴 자연어 스모크 통과 ("강남구 충전기 밀도 알려줘")
- `/spec-check` 통과 (docx 변경 없음, 새 툴은 derived 데이터)
- `/phase-review 10` CRITICAL/HIGH 0건 (특히 R2 자격증명 누출)

**롤백:** ADR-001 의 "롤백 계획" 그대로. Stage 단위 가역.

**진행 이력:**
- 2026-05-11 — Stage 10.2 + 10.3 완료. `src/ev_mcp/analytics.py`, `tools/analytics_operator_health.py`, `tools/analytics_regional_density.py` + 18개 새 테스트. 전체 verify 그린 (pytest 122 / ruff clean / mypy strict clean). 로컬 Parquet 위에서 동작 확인. Stage 10.1 (Workers R2 export) 은 사용자 R2 준비 후 별도 사이클.

---

## Open Decisions

| Decision | Default | Trigger to revisit |
|---|---|---|
| GitHub repo name | `ev-mcp-kr` | user picks |
| Custom domain | `ev-mcp.<user-domain>` | user picks during phase 4 |
| Geocoder | VWorld (free, KR govt) | if rate-limited, switch to Naver/Kakao (requires their key) |
| License | MIT | user picks |
| Cache backing store | in-memory only | if multi-instance scale needed → Redis/Upstash |
| Logging sink | Render logs only | if observability needed → axiom/logtail |

---

## Verification

End-to-end checks before submission:

1. **Local Inspector:** `mcp dev src/ev_mcp/server.py` → click each tool, verify schema and a real call.
2. **Curl Streamable HTTP:**
   ```bash
   curl -N -H 'Accept: text/event-stream' \
     -X POST https://ev-mcp.<domain>/mcp \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
   ```
3. **Real query via Claude Code:** add the deployed URL as a connector locally; ask:
   - "강남역 근처에 사용 가능한 DC콤보 충전기 있어?"
   - "충전소 ID 28260005 지금 상태가 어때?"
   - "최근 5분 사이 상태가 바뀐 충전소 알려줘"
4. **Token budget check:** every tool's largest realistic response < 25,000 tokens (verified in tests).
5. **Pytest:** `pytest -q` green; coverage ≥80%.
6. **Lint/type:** `ruff check . && mypy src/`.
7. **Container smoke:** `docker run --rm -e SERVICE_KEY=$KEY -p 8000:8000 ev-mcp` then hit `/health` and `/mcp`.

---

## Risks

- **Cloudflare Workers Python beta gap.** Mitigated by choosing Render. Document Workers as future state in README.
- **data.go.kr rate limits.** Bulk prefetch every 24h is one big sweep (~3 page calls); status is per-call. If 503s show up, add exponential backoff + circuit breaker.
- **Korean address geocoding accuracy.** VWorld is fine for street addresses but flaky for landmarks. Plan: accept lat/lng as primary, address as best-effort with a clear error if geocoding fails.
- **Stale cache after charger added/removed.** 24h TTL means new stations appear within a day. Acceptable for v1; add admin refresh endpoint later if needed.
- **Connector directory acceptance.** Claude's review may push back on no-auth servers if they decide public proxies need attribution. Mitigation: clear PRIVACY.md noting the upstream API and our service-key arrangement.

---

## Critical Files (created in implementation)

- `src/ev_mcp/server.py` — FastMCP app entry; tool/resource registration.
- `src/ev_mcp/client.py` — typed data.go.kr client (the heart).
- `src/ev_mcp/cache.py` — TTL cache + refresh-ahead.
- `src/ev_mcp/tools/nearby.py` — most-used tool; haversine + filter.
- `src/ev_mcp/codes/*.json` — code tables extracted from the docx.
- `Dockerfile`, `render.yaml`, `.github/workflows/ci.yml` — deployment.
- `README.md`, `docs/PRIVACY.md`, `docs/SUPPORT.md` — submission required.

No existing code in this repo to reuse — `/home/bokeum/ai/ev_mcp/` is empty except for the docx and an empty log file.

---

## After Approval

I'll execute Phase 1 first (skeleton, client, models, code tables) and stop for review before moving to Phase 2. Each phase ends with green tests + a committed checkpoint.
