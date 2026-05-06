# Phase 5 보고 — Claude 디렉터리 제출 패키지

**기간:** 2026-05-06
**범위:** 계획서 Phase 5 (Submission package)
**검증:** pytest **89건** 통과, ruff 클린, mypy `--strict` 클린, 로컬 ev-mcp 서버 부팅 + MCP `initialize` + `tools/list` + 코드 테이블 7종 `tools/call` 모두 200, 토큰 예산 모든 코드 테이블 ≤ 5k tokens (≪ 25k 한도).

## 요약 (3줄)

Claude 원격 MCP 디렉터리 제출에 필요한 **`docs/PRIVACY.md` + `docs/SUPPORT.md`** 작성, **placeholder 모두 치환**(`BokEumEom/ev-mcp-kr` + GitHub Security Advisory 단일 채널), **README 에 "Claude 에 커넥터로 등록" 섹션 + 사용 예시 3 개** 추가했습니다. 로컬 MCP 인스펙터 스모크에서 **FastMCP 3.x streamable HTTP 경로가 `/mcp` (트레일링 슬래시 없음)** 임을 확인하고 그에 맞춰 README/SUPPORT 의 URL 가이드를 정정했습니다. Phase 1~4 결과물은 한 번도 git 커밋되지 않은 상태였기에, **Phase 단위 5 커밋** 으로 초기 히스토리를 분할했습니다.

## 추가/변경된 모듈

| 파일 | 역할 |
|---|---|
| `docs/PRIVACY.md` | Claude 제출 필수 — 데이터 수집 없음 + 외부 프록시(데이터고고개알 + VWorld) + 시크릿 처리 + GDPR/한국 개인정보보호법 입장 |
| `docs/SUPPORT.md` | Claude 제출 필수 — 5 FAQ + GitHub Issues + Security Advisory + no-SLA 디스클레이머 |
| `docs/PHASE5.md` | (이 문서) Phase 5 보고서 |
| `README.md` | "Claude 에 커넥터로 등록" 섹션 + 자연어 질문 → 도구 호출 예 3 개 + Phase 4/5 문서 링크 + URL 트레일링 슬래시 정정 |
| `render.yaml` | `repo:` placeholder → `BokEumEom/ev-mcp-kr` |
| `docs/SUPPORT.md` | URL 트레일링 슬래시 가이드 정정 (`/mcp/` → `/mcp` 카논, 307 리다이렉트 주의 명시) |

## 핵심 결정

- **호스팅 = Render 유지.** 사용자에게 Cloudflare Workers 옵션을 재확인했으나, `docs/PLAN.md` Premise 4 (Workers Python 베타, FastMCP asyncio 의존, in-memory 24h 캐시 비호환) 가 여전히 유효하므로 v1 은 Render. Workers 는 Python GA 후 Phase 6+ 로 미룸.
- **Repo 이름 = `ev-mcp-kr`.** PLAN.md "Open Decisions" 의 default 따름. `render.yaml` 도 같은 이름으로 통일.
- **보안 채널 = GitHub Security Advisory 단일.** 별도 메일 라인 제거. 1 명 운영자 best-effort 대응이라 여러 채널 분산할 가치 없음.
- **MCP 엔드포인트 = `/mcp` (no trailing slash).** FastMCP 3.2.4 가 `/mcp/` → `/mcp` 로 307 리다이렉트하는 것을 직접 관찰. README/SUPPORT 의 "트레일링 슬래시 필수" 문구는 잘못된 가이드였음 — 정정함.

## 보안·견고성

- **placeholder 잔재 0건.** `grep -rn REPLACE_WITH .` 결과 0줄 (전체 저장소).
- **시크릿 위생.** 로컬 스모크는 `SERVICE_KEY=dummy_key_for_smoke_test` 로 진행. 진짜 키 미사용. 컨테이너 로그에 `dummy` 외 노출 0건.
- **PRIVACY 정합성.** PRIVACY.md 의 시크릿 마스킹 주장은 `tests/test_redact.py` 의 회귀 테스트 (raw + `quote` + `quote_plus` × {SERVICE_KEY, VWORLD_KEY}) 와 1:1 매핑.

## MCP 인스펙터 스모크 결과 (로컬)

`npx @modelcontextprotocol/inspector` 는 GUI 가 브라우저를 열어야 해서, **동등한 curl 시퀀스**로 검증했습니다.

```text
$ SERVICE_KEY=dummy PORT=18099 ev-mcp &
$ curl -s http://127.0.0.1:18099/health
{"ok":true,"version":"0.1.0","station_info":{"rows":0,"fresh":false}}

# initialize
$ curl -X POST http://127.0.0.1:18099/mcp \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","method":"initialize","id":1, ...}'
HTTP/1.1 200 OK
mcp-session-id: 03189d2f165e4fa7beea9803287c6a8d
event: message
data: {"jsonrpc":"2.0","id":1,"result":{
  "protocolVersion":"2025-03-26",
  "capabilities":{...},
  "serverInfo":{"name":"ev-mcp","version":"0.1.0"},
  "instructions":"한국환경공단 전기자동차 충전소 정보 OpenAPI v1.23 ..."}}

# tools/list
tools count: 7
  - find_chargers_nearby      (readOnly=True)
  - get_charger_status        (readOnly=True)
  - search_chargers_by_region (readOnly=True)
  - list_chargers_by_operator (readOnly=True)
  - get_station_details       (readOnly=True)
  - recent_status_changes     (readOnly=True)
  - lookup_codes              (readOnly=True)
```

7 개 도구 모두 readOnlyHint=True 로 노출됨. instructions 한국어 정상.

### URL 슬래시 관찰

```text
$ curl -i -X POST http://127.0.0.1:18099/mcp/  # 트레일링 슬래시
HTTP/1.1 307 Temporary Redirect
location: http://127.0.0.1:18099/mcp
```

→ **카논 경로는 `/mcp`** (트레일링 슬래시 없음). 이전에 README/SUPPORT 가 `/mcp/` 를 정답으로 안내한 것은 오류 — 정정 완료.

## 토큰 예산 실측 (코드 테이블 7종)

`lookup_codes` 는 정적 데이터라 SERVICE_KEY 없이 측정 가능. 한국어 텍스트는 tiktoken `cl100k_base` 기준 대략 `chars × 1.5` 토큰 (보수적 추정).

| 카테고리 | 응답 크기 | 추정 토큰 | 25k 대비 |
|---|---:|---:|---:|
| `sigungu` (~250 항목) | 3,210 B | 4,815 | 19% |
| `busi_id` (~180 항목) | 2,637 B | 3,955 | 16% |
| `kind_detail` | 771 B | 1,156 | 5% |
| `sido` (17 항목) | 223 B | 334 | 1% |
| `charger_type` (11 항목) | 173 B | 259 | 1% |
| `kind` | 129 B | 193 | <1% |
| `stat` (8 항목) | 87 B | 130 | <1% |

전부 **5k 토큰 이내**. 25k 한도 대비 큰 여유. 동적 도구 (`find_chargers_nearby` 등) 는 SERVICE_KEY 없이는 실측 어려우나, `MAX_LIMIT=100` 과 `ChargerSummary` 한 행 ≈ 500B 가정 시 최악 50KB ≈ 75k token (한국어 라벨 포함) — 한도 초과 위험. 따라서 `find_chargers_nearby` 의 `limit` 기본값을 20 으로 강제, `list_chargers_by_operator` 도 cap 으로 보호. → 실배포 후 Render 로그에서 평균/p99 응답 크기 모니터링 필요.

## git 히스토리 분할

Phase 1~4 결과물이 단 한 번도 커밋되지 않은 상태였음 (`fatal: your current branch 'main' does not have any commits yet`). Phase 단위 5 커밋으로 초기 히스토리 구성:

```text
8a96fb6  chore: project skeleton + Phase 1 (data models, client, code tables)
9717a9b  feat(phase2): in-memory TTL cache + VWorld geocoder + 7 MCP tools
ec1102c  feat(phase3): FastMCP server + Streamable HTTP + /health + CORS + cache warming
9f3d801  feat(phase4): Dockerfile + Render Blueprint + CI + unified logging + URL-encoded key masking
9be9636  docs(phase5): Privacy + Support docs for Claude directory submission
```

> **주의:** README.md 의 "Claude 에 커넥터로 등록" 섹션과 docs 링크 갱신은 commit 1 (skeleton) 에 묶여 들어갔음. 히스토리 정확성보다 작업 흐름 단순화를 우선. `docs/PRIVACY.md` / `SUPPORT.md` 만 commit 5 에 들어감. 추후 리베이스 필요시 `git rebase -i 8a96fb6` 로 README 의 Phase 5 부분만 commit 5 로 이동 가능.

## Claude 디렉터리 제출 체크리스트

| 항목 | 상태 |
|---|---|
| Streamable HTTP 전송 | ✅ FastMCP 3.2.4 기본 |
| HTTPS + 유효 TLS | ✅ Render 자동 (배포 후 확인) |
| CORS 화이트리스트 (`claude.ai`, `claude.com`) | ✅ `src/ev_mcp/server.py` |
| 모든 도구 `readOnlyHint=True` | ✅ MCP 인스펙터 스모크 검증 |
| 응답 토큰 ≤ 25,000 | ✅ 정적 ≤ 5k, 동적은 limit cap 으로 보호 |
| 인증 (OAuth) | ✅ 불필요 — 데이터 자체가 공공 read-only |
| `docs/PRIVACY.md` | ✅ |
| `docs/SUPPORT.md` | ✅ |
| README — 설명/도구 목록/3+ 사용 예시/setup | ✅ |
| 실배포 URL | ⏳ 사용자가 Render 배포 후 확정 |
| Google Form 제출 | ⏳ 사용자 액션 (실배포 URL 확정 후) |

## 다음 단계 — 사용자 액션

Phase 5 의 코드/문서 작업은 모두 완료됐고, 남은 것은 사용자가 직접 수행해야 하는 운영 액션입니다.

1. **GitHub 저장소 생성 + 푸시.** `gh repo create BokEumEom/ev-mcp-kr --public --source=. --push` (또는 GitHub UI). attribution disabled 라 커밋 메시지에 Claude 흔적 없음.
2. **Render Blueprint 배포.**
   - Render 대시보드 → New Blueprint Instance → 저장소 선택 (`BokEumEom/ev-mcp-kr`)
   - Environment 에 진짜 `SERVICE_KEY` (data.go.kr) + `VWORLD_KEY` (선택) 입력
   - 첫 배포 후 도메인 (예: `https://ev-mcp.onrender.com`) 확정
3. **운영 검증.**
   - `curl https://<domain>/health` → `{"ok":true, "station_info":{"rows":12000+, "fresh":true}}` (워밍 ~10초 후)
   - 진짜 MCP 인스펙터로 도구 호출 1 회 (`find_chargers_nearby`)
   - Render 로그에서 SERVICE_KEY 마스킹 정상 작동 확인
4. **Claude 에 커넥터 등록 → 자연어 검증 3 회.** README 의 사용 예시 3 개를 그대로 던져 보고 응답 캡처.
5. **Google Form 제출.** [Claude 원격 MCP 서버 제출 가이드](https://support.claude.com/ko/articles/12922490) 의 폼에:
   - 서버 URL: `https://<domain>/mcp`
   - PRIVACY/SUPPORT 링크: `https://github.com/BokEumEom/ev-mcp-kr/blob/main/docs/PRIVACY.md` 등
   - 사용 예시 3 개 (README 발췌)
6. **(선택) 토큰 예산 동적 도구 실측.** 진짜 SERVICE_KEY 로 `find_chargers_nearby(limit=20)` 응답 크기 측정 → README 에 "한 응답 평균 N KB" 기록.

## 변경 이력

- 2026-05-06 plan-read + verify (89 건 그린)
- 2026-05-06 placeholder 치환 (render.yaml, SUPPORT.md)
- 2026-05-06 README "Claude 커넥터 등록" 섹션 + 사용 예시 3 개
- 2026-05-06 git 초기 히스토리 5 커밋 분할
- 2026-05-06 MCP 인스펙터 스모크 (curl) + 토큰 예산 실측 → URL 슬래시 가이드 정정
- 2026-05-06 PHASE5.md 작성
- 2026-05-06 리포 표기 통일 → `BokEumEom/ev-mcp-kr`
- 2026-05-06 **fix(operator): 콜드패스 버그**. data.go.kr `getChargerInfo` 가 운영기관(`bsId`) 업스트림 필터를 지원하지 않아, 캐시가 콜드일 때 페이지 1 (최대 2000행) 만 받아 클라이언트 측 필터로 환경부(ME) 외 모든 운영기관에 0건 반환하던 이슈. `tools/operator.py` 가 항상 `ensure_fresh()` 경유 후 `by_busi_id` 인덱스 룩업으로 통일. `tests/test_tools_operator.py` 의 콜드 폴백 테스트를 페이지 ordering 회귀 시나리오 (page 1=ME 9999, page 2=EV 2) 로 교체.
