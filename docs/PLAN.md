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

**Total estimate:** ~6 days end-to-end.

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
