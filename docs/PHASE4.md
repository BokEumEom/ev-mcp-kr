# Phase 4 보고 — 컨테이너화 + Render 배포 + CI

**기간:** 2026-04-30
**범위:** 계획서 Phase 4 (Containerize & deploy)
**검증:** pytest **84건** 통과, ruff 클린, mypy `--strict` 클린, `docker build .` 성공, 컨테이너 boot + `/health` 200, 특수문자 SERVICE_KEY (`abc+def/ghi=jkl`) raw/URL-encoded 모두 로그 누출 0.

## 요약 (3줄)

Phase 3 의 FastMCP 서버를 **multi-stage Docker 이미지**로 패키징하고, **Render Blueprint** + **GitHub Actions CI** 까지 갖췄습니다. 로깅이 stdlib(uvicorn 포함) + structlog 단일 JSON 싱크로 통일됐고, **특수문자 SERVICE_KEY 의 URL-encoded 변형까지 마스킹**되도록 보안을 강화했습니다. data.go.kr 호출은 **HTTPS** 로 강제 — 평문 쿼리에 키 노출 위험 차단.

## 추가/변경된 모듈

| 파일 | 역할 |
|---|---|
| `Dockerfile` | multi-stage(builder+runtime) python:3.12-slim + apt 보안 패치 + non-root user + HEALTHCHECK |
| `.dockerignore` | .env / 테스트 / 문서 / docx 제외, scripts/healthcheck.py 만 포함 |
| `scripts/healthcheck.py` | 독립 헬스체크 스크립트 (stdlib only) |
| `render.yaml` | Render Blueprint (Singapore, single instance, autoDeploy) |
| `.github/workflows/ci.yml` | lint + mypy + pytest + docker build smoke |
| `src/ev_mcp/server.py` | `configure_logging()` idempotent + uvicorn 통합 + `access_log=False` |
| `src/ev_mcp/cache.py`, `client.py`, `geocode.py`, `tools/nearby.py` | stdlib `logging` → `structlog.get_logger` 통일 |
| `src/ev_mcp/settings.py` | `api_base_url` http → **https** |
| `src/ev_mcp/client.py`, `geocode.py` | `redact()` URL-encoded SERVICE_KEY 변형까지 마스킹 |
| `README.md` | 운영/배포/제출 가이드 풀버전 |
| `tests/test_redact.py` | URL-encoded 변형 마스킹 회귀 테스트 4건 |
| `tests/test_logging.py` | configure_logging idempotency 회귀 테스트 2건 |

## 핵심 설계 결정

- **HTTPS 강제.** 운영 기본값을 `http://...` 에서 `https://...` 로 교체. data.go.kr 은 HTTPS 지원하므로 옵션이 아니라 default.
- **Multi-stage Dockerfile.** builder 가 venv 만들고 runtime 은 venv + src 만 복사. apt 보안 패치는 두 stage 모두에 적용해 베이스 이미지 high CVE 차단.
- **non-root 실행.** 모든 runtime 명령이 `app:app` 으로 실행. `useradd --system` + `USER app`.
- **구조화 헬스체크.** inline f-string 대신 `scripts/healthcheck.py` (stdlib `urllib.request`) 로 분리. 디버그 가능성 + 캐시 무효화 동작 정확.
- **로깅 단일 사이크.** `configure_logging()` 가 root logger 의 핸들러를 우리 JSON 핸들러로 대체하고 uvicorn의 named logger를 propagate. 두 번 호출되어도 idempotent.
- **`access_log=False`.** 모든 트래픽이 POST `/mcp` 로 가는 streamable HTTP 라 access log 가치 낮고, 프록시가 Forwarded 헤더에 query 박을 위험만 있음.

## 보안·견고성 (리뷰 반영)

code-reviewer Phase 4 리뷰 → 즉시 패치:

| 발견 | 심각도 | 처리 |
|---|---|---|
| `api_base_url` 기본값 http (SERVICE_KEY 평문 전송) | CRITICAL | https 로 변경 |
| `redact()` 가 URL-encoded variant 못 잡음 (data.go.kr 키는 base64 라 +/= 포함) | CRITICAL | `urllib.parse.quote` + `quote_plus` variant 모두 마스킹. client.py + geocode.py 양쪽 |
| `configure_logging` 멀티 호출 시 root logger handler 누적 | HIGH | `_LOGGING_CONFIGURED` 가드로 idempotent |
| inline HEALTHCHECK 코드 (f-string + `__import__` hack) | HIGH | `scripts/healthcheck.py` 분리 |
| `access_log=True` proxy Forwarded 누출 가능성 | HIGH | `access_log=False` |
| `python:3.12-slim` 베이스 high CVE | (Phase 4 발견) | builder + runtime 둘 다 `apt-get upgrade -y` |
| stdlib + structlog 혼용으로 traceback 의 `exc_info` 자동 첨부 | (스모크 발견) | 모든 모듈 structlog 으로 통일, `client.redact()` 로 메시지만 로그 |

## 회귀 테스트 추가 (총 84건, +6건)

`tests/test_redact.py`:
1. raw key 마스킹
2. `urllib.parse.quote` 변형 마스킹
3. `urllib.parse.quote_plus` 변형 마스킹
4. VWORLD_KEY 도 동일하게 (raw + 두 변형)

`tests/test_logging.py`:
5. `configure_logging` 두/세 번 호출해도 핸들러 1개 유지
6. JSON 라인 출력이 깨지지 않음 (구조 검증)

## 컨테이너 스모크 결과 (로컬 검증)

```text
$ docker build --no-cache -t ev-mcp:smoke .
... naming to docker.io/library/ev-mcp:smoke done

$ docker run -d -e SERVICE_KEY="abc+def/ghi=jkl" -p 18002:8000 ev-mcp:smoke
$ sleep 5 && curl http://127.0.0.1:18002/health
{"ok":true,"version":"0.1.0","station_info":{"rows":0,"fresh":false}}

$ docker logs ev-mcp-smoke
{"event":"station_info refresh aborted ...: getChargerInfo HTTP 401","level":"warning","logger":"ev_mcp.cache","timestamp":"..."}
{"error":"getChargerInfo HTTP 401","event":"cache_warm_failed","level":"warning","logger":"ev_mcp.server","timestamp":"..."}

$ docker logs ev-mcp-smoke | grep -c "abc+def"      # 0
$ docker logs ev-mcp-smoke | grep -ci "abc%2bdef"   # 0
```

- 부팅 시간: ~4초 (워밍은 백그라운드)
- `/health` 즉시 200
- 모든 로그가 valid JSON 한 줄
- SERVICE_KEY 형태(raw/encoded) 모두 로그에 0회 등장

## 변경 이력

- 2026-04-30 19:00 Phase 4-1 Dockerfile + .dockerignore
- 2026-04-30 19:10 Phase 4-2 render.yaml
- 2026-04-30 19:20 Phase 4-3 CI 워크플로우
- 2026-04-30 19:30 Phase 4-4 로그 통합 (uvicorn + structlog)
- 2026-04-30 19:45 Phase 4-5 README 운영 섹션 + 컨테이너 스모크 (보안 이슈 추가 발견 → cache.py redact)
- 2026-04-30 20:00 Phase 4 종합 리뷰
- 2026-04-30 20:15 리뷰 반영 (CRITICAL 2 + HIGH 4 + 베이스이미지 보안 패치)

## 운영 가이드 (READMEMy 의 운영 섹션 발췌)

- **롤백:** Render 대시보드 → 서비스 → "Manual Deploy" → 이전 커밋 선택
- **시크릿 회전:** Render 대시보드 → Environment → SERVICE_KEY 교체 → 자동 재시작
- **Cold start 첫 요청:** 워밍 백그라운드 task — 평균 +수 초 (한 번)
- **로그:** stdout JSON 라인. 모든 라인이 `{"event":..., "level":..., "logger":..., "timestamp":...}` 구조
- **단일 워커 권장:** `numInstances: 1` 유지. 멀티 워커 필요시 Phase 6+ 에서 Redis 캐시

## 다음 단계 (Phase 5 — Claude 디렉터리 제출 패키지)

1. `docs/PRIVACY.md` — 데이터 수집/보관/공유 정책 (Claude 제출 필수)
2. `docs/SUPPORT.md` — 이슈 트래커 + 연락처
3. README 의 "Claude 커넥터로 등록" 섹션을 실제 URL 로 채우고 3 개 사용 예시
4. MCP 인스펙터 스모크: `npx @modelcontextprotocol/inspector https://your-domain/mcp/` 결과 캡처
5. 토큰 예산 실측 (한국어 응답이 12k 안인지)
6. Google Form 제출 (필수 항목: 서버 정보, 문서 링크, 테스트 계정 (불필요), 사용 예시 ≥3개)
7. `autoDeploy: true` + 롤백 절차 문서화 마무리
