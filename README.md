# ev-mcp — 한국 EV 충전소 정보 MCP 서버

한국환경공단의 **전기자동차 충전소 정보 OpenAPI v1.23** 을 Claude 와 호환되는
**원격 MCP 커넥터**로 노출합니다. Claude 에서 자연어로 질문하면 7 개의 도구가
자동으로 호출되어 답을 만듭니다.

> **사용 예 (Claude)**
>
> - "강남역 근처 1km 안에 사용 가능한 DC콤보 충전기 알려줘"
> - "충전소 28260005 의 02 번 충전기 지금 상태가 어때?"
> - "최근 5분 사이 서울에서 상태가 바뀐 충전기 있어?"
> - "환경부가 운영하는 제주도 충전기 목록"

자세한 설계와 진행 상황은 `docs/` 참고:

- [`docs/PLAN.md`](docs/PLAN.md) — 전체 계획서
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 디렉터리 구조와 협업 규약
- [`docs/PHASE1.md`](docs/PHASE1.md), [`PHASE2.md`](docs/PHASE2.md), [`PHASE3.md`](docs/PHASE3.md), [`PHASE4.md`](docs/PHASE4.md) — Phase 별 보고서
- [`docs/WORKFLOW.md`](docs/WORKFLOW.md) — 8 단계 협업 사이클
- [`docs/PRIVACY.md`](docs/PRIVACY.md), [`docs/SUPPORT.md`](docs/SUPPORT.md) — Claude 디렉터리 제출 필수 문서

## 노출되는 7 개 도구

| 도구 | 설명 |
|---|---|
| `find_chargers_nearby` | 좌표/주소 기준 반경 내 검색 (haversine + bounding box) |
| `get_charger_status` | 특정 충전기 실시간 상태 |
| `search_chargers_by_region` | 시도/시군구로 검색 |
| `list_chargers_by_operator` | 운영기관(busiId) 별 목록 |
| `get_station_details` | 충전소 ID 의 모든 충전기 + 메타 |
| `recent_status_changes` | 최근 N 분(1~10) 상태 변경 |
| `lookup_codes` | 공통 코드 테이블 (sido / sigungu / charger_type / stat / busi_id / kind) |

추가로 코드 테이블은 MCP **resource template** `codes://{category}` 로도 노출됩니다.

## 빠른 시작 (로컬)

```bash
# 1. 의존성 설치
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 2. 시크릿 설정
cp .env.example .env
# .env 를 열어서 SERVICE_KEY (data.go.kr 발급) 입력
# (선택) VWORLD_KEY 입력 — 주소 → 좌표 변환에 필요

# 3. 검증
python -m pytest -q          # 78 개 테스트 통과
python -m ruff check .       # 린트
python -m mypy src/          # 타입 체크 (strict)

# 4. 로컬 실행
ev-mcp                        # http://127.0.0.1:8000/mcp 에서 streamable HTTP
# 또는 stdio (Claude Code 와 직접 연결할 때):
python -c "from ev_mcp.server import main; main(transport='stdio')"
```

`/health` 확인:

```bash
curl http://127.0.0.1:8000/health
# {"ok":true,"version":"0.1.0","station_info":{"rows":12345,"fresh":true}}
```

## 컨테이너 빌드/실행

```bash
docker build -t ev-mcp:dev .
docker run --rm -p 8000:8000 \
  -e SERVICE_KEY="$(grep ^SERVICE_KEY .env | cut -d= -f2)" \
  -e VWORLD_KEY="$(grep ^VWORLD_KEY .env | cut -d= -f2)" \
  ev-mcp:dev
```

빌드 특징:
- multi-stage Dockerfile (`python:3.12-slim` 베이스)
- non-root `app` 유저로 실행
- HEALTHCHECK 가 `/health` 폴링
- 단일 워커 — `docs/PHASE3.md` 의 per-worker 캐시 caveat 참조

## 배포 — Render

`render.yaml` 이 Blueprint 입니다. 절차:

1. 이 저장소를 fork 하고 `render.yaml` 의 `repo:` 를 본인 owner 로 교체
2. Render 대시보드 → **New Blueprint Instance** → 저장소 선택
3. **시크릿 입력**:
   - `SERVICE_KEY` — data.go.kr 에서 발급한 인증키
   - `VWORLD_KEY` — VWorld 지오코더 키 (선택)
4. (선택) Custom domain 연결. CORS 화이트리스트는 자동으로 `claude.ai`/`claude.com` 포함
5. 배포 확인:
   - `curl https://your-domain/health` → `{"ok": true, ...}`
   - Claude 커넥터 등록: 원격 MCP URL = `https://your-domain/mcp/` (FastMCP 의 streamable HTTP 경로)

CI/CD: `.github/workflows/ci.yml` 가 PR 에서 lint/test, `main` 에서 docker build smoke 를 실행합니다. Render 의 auto-deploy 가 `main` 푸시를 자동 감지해 배포합니다.

## 운영 시 주의

- **단일 워커 권장.** 멀티 워커 배포 시 워커별로 24h station_info 캐시가 따로 워밍됨 → 메모리 N 배 + 워밍 트래픽 N 배. `render.yaml` 은 `numInstances: 1`. 멀티 인스턴스가 필요해지면 Redis/Upstash 같은 공유 캐시로 전환.
- **`/health` 는 liveness only.** 외부 API (data.go.kr) 가 죽어도 `/health` 는 200 을 반환합니다. readiness 체크는 캐시 fresh 여부와 무관. 필요하면 `/ready` 같은 readiness 엔드포인트 추가.
- **콜드 스타트 시 첫 요청.** 캐시 워밍이 백그라운드에서 돌아 `/health` 는 즉시 200. 첫 사용자 요청은 cold-path (시도별 단일 fetch) 로 처리되어 평균 응답 시간 +수 초.
- **`SERVICE_KEY` 위생.** `.env` 만 사용, 코드/로그/예외 어디에도 등장 X. 모든 외부 응답·예외 메시지는 `EvChargerClient.redact()` 로 마스킹.

## Claude 커넥터 디렉터리 제출

이 서버는 [Claude 원격 MCP 서버 제출 가이드](https://support.claude.com/ko/articles/12922490) 의 요건을 만족합니다:

- **Streamable HTTP 전송** (FastMCP 기본)
- **HTTPS + 유효한 TLS 인증서** (Render 가 자동)
- **CORS** — `claude.ai`/`claude.com` 화이트리스트
- **모든 도구가 `readOnlyHint: true`**
- **응답 토큰 ≤ 25,000** — `MAX_LIMIT=100`, `num_of_rows` cap, ChargerSummary 한 행 ≈ 500B
- **인증 없음** — 데이터 자체가 공공 read-only 라 OAuth 불필요
- **Privacy/Support 문서** — [`docs/PRIVACY.md`](docs/PRIVACY.md), [`docs/SUPPORT.md`](docs/SUPPORT.md)

### Claude 에 커넥터로 등록

1. Claude.ai → **Settings → Connectors → Add custom connector**
2. **Name**: `한국 EV 충전소 (ev-mcp)`
3. **Remote MCP server URL**: `https://<your-render-domain>/mcp/`
   - Render 기본 도메인 예: `https://ev-mcp.onrender.com/mcp/`
   - Custom domain 사용 시 그 도메인 + `/mcp/`
   - **마지막 슬래시 필수** — FastMCP streamable HTTP 경로 규약
4. **Authentication**: `None` (이 서버는 공공 데이터 프록시라 OAuth 미사용)
5. 저장 후 Claude 새 대화에서 자연어로 호출

### 사용 예시 3 가지

다음은 Claude 에 등록한 뒤 자연어로 던질 수 있는 대표 질문과 그때 호출되는 도구입니다.

**예 1 — 좌표/주소 기반 근처 검색**

> "강남역 근처 1km 안에 사용 가능한 DC콤보 충전기 알려줘"

Claude 가 `find_chargers_nearby` 를 호출:
```python
find_chargers_nearby(
    address="서울특별시 강남구 강남대로 396",
    radius_km=1.0,
    available_only=True,
    charger_type=["04", "06"],  # DC 콤보 단독 + 멀티
    limit=20,
)
```

**예 2 — 특정 충전기의 실시간 상태**

> "충전소 28260005 의 02 번 충전기 지금 상태가 어때?"

Claude 가 `get_charger_status` 를 호출:
```python
get_charger_status(stat_id="28260005", chger_id="02")
# → ChargerStatus(status_code=2, status_label="사용가능", ...)
```

**예 3 — 운영기관 + 지역 필터**

> "환경부가 운영하는 제주특별자치도 충전기 100 곳 알려줘"

Claude 가 `list_chargers_by_operator` 를 호출:
```python
list_chargers_by_operator(
    operator="ME",          # 환경부 busiId
    region="제주특별자치도",
    limit=100,
)
```

추가 사용 패턴은 각 도구의 한국어 docstring 참고.

## 라이선스

MIT
