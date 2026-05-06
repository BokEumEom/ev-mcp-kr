# Phase 3 보고 — FastMCP 서버 와이어링

**기간:** 2026-04-30
**범위:** 계획서 Phase 3 (MCP server wiring)
**검증:** pytest **78건** 통과, ruff 클린, mypy `--strict` 클린.

## 요약 (3줄)

Phase 2 의 7 개 툴을 **FastMCP 앱**으로 묶고 Streamable HTTP 로 노출했습니다. **ToolContext** dataclass 로 의존성을 단일 인자로 통일했고, **Starlette 래퍼**로 `/health` + CORS + 백그라운드 캐시 워밍 lifespan 을 추가했습니다. Render 같은 PaaS 의 healthcheck 타임아웃을 피하려고 워밍을 백그라운드 task 로 띄워 lifespan 자체는 즉시 yield 합니다.

## 추가된 모듈

| 파일 | 역할 |
|---|---|
| `src/ev_mcp/context.py` | `ToolContext` dataclass — settings + client + caches 묶음 |
| `src/ev_mcp/server.py` | FastMCP 앱 + 7 개 툴 + 코드 resource 템플릿 + Starlette + /health + lifespan |
| `tests/conftest.py` | `ctx` fixture 추가 (모든 tool 테스트가 공유) |
| `tests/test_server.py` | 통합 테스트 10 건 |

## 핵심 설계 결정

- **ToolContext 단일 의존성.** Phase 2 의 `(client, caches, settings)` 트리플 → `ctx: ToolContext` 단일 인자. FastMCP 데코레이터는 closure 로 ctx 잡고 Phase 2 함수에 위임.
- **Streamable HTTP 전송.** Claude 디렉터리 제출 가이드의 mandatory 요건. `mcp.http_app(transport="streamable-http")` 를 Starlette `Mount("/")` 에 마운트.
- **MCP resources 로 코드 테이블 노출.** `codes://{category}` 단일 템플릿이 7 개 코드 테이블을 모두 서빙. Claude 가 도구 호출 없이도 읽을 수 있음.
- **백그라운드 캐시 워밍.** 워밍이 lifespan 의 `yield` 를 막지 않도록 `asyncio.create_task` 로 분리. cold-start 시 첫 요청은 cold path (zcode 단일 fetch) 로 처리되고, 백그라운드에서 전국 12k+ 행 prefetch 가 끝나면 그 다음 요청부터 hot path. Render healthcheck 가 30s 안에 200 받음.
- **structlog JSON 로깅.** stdout 으로 JSON 라인. uvicorn 자체 로그와 섞이는 부분은 Phase 4 에서 logger 통합.

## 보안·견고성 (리뷰 반영)

code-reviewer 에이전트의 Phase 3 리뷰에서 잡힌 항목 처리:

| 발견 | 심각도 | 처리 |
|---|---|---|
| lifespan 캐시 워밍 실패 시 `logger.exception` 의 traceback 에 SERVICE_KEY 가 들어갈 수 있음 | CRITICAL | `logger.warning(..., error=client.redact(e))` 로 변경. traceback 자체를 안 찍음. 회귀 테스트(`test_lifespan_redacts_service_key_in_warm_failure_log`) 추가 |
| 코드 resource ValueError 가 사용자 입력 그대로 echo | CRITICAL | echo 제거 + 화이트리스트만 반환 |
| lifespan 진입 전 예외 시 client 누수 가능 | HIGH | `try/finally` + `contextlib.suppress` 로 워밍 task cancel 보장 |
| Render healthcheck 타임아웃 충돌 | HIGH | 워밍을 background task 로 분리, lifespan 즉시 yield |
| FastMCP 데코레이터 시그니처 keyword-only 가드 부재 | MEDIUM | 7 개 툴 모두 `*` 추가 |
| `EvChargerClient._redact` 가 private — 외부에서 호출 못함 | INFO | `redact()` public 메서드로 승격 (server.py 가 호출해야 함) |

## 통합 테스트 추가 (총 78건, +10건)

`tests/test_server.py`:

1. 7 개 툴 등록 검증
2. 모든 툴이 `readOnlyHint=True` 인지
3. `codes://{category}` resource 템플릿 등록
4. 7 개 코드 카테고리별 resource 가 JSON 반환
5. `lookup_codes` 도구 직접 호출 (FastMCP `call_tool`)
6. `/health` 엔드포인트 — cache 상태 (rows, fresh) 보고
7. CORS preflight (claude.ai origin) → `access-control-allow-origin` 에코
8. lifespan 백그라운드 워밍 — 요청 호출 횟수 ≥1, 캐시 fresh 확인
9. 503 일 때 lifespan 죽지 않고 cold cache 로 진입
10. 503 응답 본문에 SERVICE_KEY 가 echo 되어도 로그에 누출 없음

## 변경 이력

- 2026-04-30 17:30 Phase 3-1 ToolContext 마이그레이션
- 2026-04-30 17:50 Phase 3-2 server.py FastMCP 와이어링
- 2026-04-30 18:05 Phase 3-3 lifespan + 백그라운드 캐시 워밍
- 2026-04-30 18:20 Phase 3-4 통합 테스트 10 건
- 2026-04-30 18:35 Phase 3 종합 리뷰
- 2026-04-30 18:50 리뷰 반영 (CRITICAL 2 + HIGH 2 + MEDIUM 1)

## 운영 시 주의 (Phase 4 에 반영 필요)

- **단일 워커 권장.** 멀티 워커 배포 시 워커별로 24h station_info 캐시가 따로 워밍됨 → 메모리 N 배 + 워밍 트래픽 N 배. Render 는 single instance 로 시작; 멀티가 필요해지면 Redis/Upstash 같은 공유 캐시.
- **`/health` 는 liveness only.** 외부 API 가 죽어도 200 반환. readiness/외부 의존성 헬스체크는 Phase 4 에서 옵션으로.
- **cold start 시 첫 요청.** 워밍이 백그라운드라 첫 요청은 cold path 로 처리. 평균 응답 시간 +수 초.

## 다음 단계 (Phase 4 — 컨테이너화 + Render 배포)

1. `Dockerfile` (multi-stage, non-root user, healthcheck).
2. `render.yaml` Blueprint.
3. `.github/workflows/ci.yml` (PR 에서 lint/test, main 에서 image build + Render webhook).
4. Render 대시보드: `SERVICE_KEY`, `VWORLD_KEY` 시크릿 설정, custom domain.
5. uvicorn 자체 로그를 structlog 으로 통합.
6. README 의 운영 섹션 (single-worker, /health 의미 등) 업데이트.
