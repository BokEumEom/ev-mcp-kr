# CLAUDE.md — ev-mcp 프로젝트 가이드

이 파일은 Claude Code(또는 다른 AI 코딩 보조 도구)가 이 저장소에서 작업할 때 먼저 읽어야 할 컨텍스트입니다.

## 프로젝트 한 줄 요약

한국환경공단 전기자동차 충전소 정보 OpenAPI v1.23을 **Claude 원격 MCP 커넥터**로 노출하는 서버. 사용자는 자연어로 "강남역 근처 사용 가능한 DC콤보 충전기" 같은 질문을 던지면 됩니다.

## 빠른 시작

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env   # SERVICE_KEY 입력
python -m pytest -q
python -m ruff check .
python -m mypy src/
```

## 진행 상황

- **Phase 1 (완료):** 골격, 모델, 데이터고고개알 클라이언트, 코드 테이블 7종, 테스트 21건. → `docs/PHASE1.md`
- **Phase 2 (완료):** 캐시(24h/60s) + 지오코더 + 7개 MCP 툴 + 도메인 모델, 테스트 68건. → `docs/PHASE2.md`
- **Phase 3 (완료):** FastMCP 서버 + Streamable HTTP + /health + CORS + 백그라운드 캐시 워밍, 테스트 78건. → `docs/PHASE3.md`
- **Phase 4 (완료):** Dockerfile + Render Blueprint + GitHub Actions CI + 통합 로깅 + URL-encoded 키 마스킹 + HTTPS 강제, 테스트 84건. → `docs/PHASE4.md`
- **Phase 5 (완료):** PRIVACY/SUPPORT 문서, README 등록 가이드 + 사용 예시 3개, MCP 인스펙터 스모크. → `docs/PHASE5.md`
- **Phase 6 (완료):** SQLite 영속 store + sync 스크립트 분리. in-memory 24h 캐시 → `data/chargers.db`. 테스트 102건. → `docs/PHASE6.md`
- **Phase 7 (완료):** MCPB 번들 (`ev-mcp.mcpb`) — Claude Desktop 직접 설치. stdio CLI + `ev-mcp-sync` 콘솔 + manifest.json. → `docs/PHASE7.md`
- **Phase 9 (완료):** TypeScript Cloudflare Workers 포팅 (`workers/`). 두-DO 아키텍처 (per-session McpAgent + 단일 글로벌 InventoryStore), cron sync, smart upsert (rows-written cap 회피). → `docs/PHASE9.md`
- **Phase 10 Stage 10.2~10.5 (완료):** DuckDB 분석 사이드카 (ADR-001). `src/ev_mcp/analytics.py` + 새 MCP 툴 2개 (`analyze_operator_health`, `regional_density`) + 인터랙티브 web 대시보드 8 페이지. Stage 10.4 데이터 품질 수정 (`stat='9'` 미연동 분리). → `docs/PHASE10.md`, `docs/adr/ADR-001-duckdb-analytics.md`, `web/README.md`
- **Phase 10 Stage 10.1 (미진행):** Workers R2 일별 Parquet export. 사용자 R2 준비 후 별도 사이클.
- **Phase 11 (완료):** 시계열 분석 기반 — 날짜별 스냅샷 export (`ev-mcp-snapshot`, synced_at 중복 스킵) + analytics view 레이어 (`v_all`/`v_latest`, `{source}` placeholder 제거) + 시계열 MCP 툴 2개 (`snapshot_diff`, `inventory_trend`). pytest 135건. → `docs/PHASE11.md`

전체 계획서: `docs/PLAN.md`. ADR: `docs/adr/`.

## 워크플로우

각 Phase 는 **plan → tasks → impl → verify → review → fix → verify → doc** 8단계를 따릅니다.
자세한 흐름은 `docs/WORKFLOW.md`. 슬래시 명령은 `.claude/commands/`:

- `/phase-start N` — 새 Phase 시작
- `/verify` — pytest + ruff + mypy 한 번에
- `/phase-review N` — code-reviewer 에이전트 디스패치
- `/phase-doc N` — `docs/PHASE{N}.md` 보고서 작성
- `/spec-check` — docx ↔ 코드 일치성 감사
- `/extract-codes` — 코드 테이블 재추출

## 룰 (CLAUDE.md 보조)

`.claude/rules/` 의 4개 파일을 작업 시작 전 참조:

1. `secrets.md` — SERVICE_KEY 위생.
2. `spec-discipline.md` — docx 가 진실의 원천.
3. `mcp-tool-conventions.md` — 툴 작성 규약.
4. `phase-workflow.md` — Phase 단위 사이클.

## 디렉터리 구조

자세한 구조와 협업 규약은 `docs/ARCHITECTURE.md` 참고. 핵심만:

```text
src/ev_mcp/        # Python 패키지 본체 (Phase 1~7, 10)
  client.py        # data.go.kr 호출
  models.py        # Pydantic 타입 (스펙 1:1)
  settings.py      # 환경변수 로더 (Phase 10 에서 R2/snapshot 필드 추가)
  store.py         # SQLite 영속 store (Phase 6)
  analytics.py     # DuckDB 분석 사이드카 (Phase 10)
  codes/*.json     # 공통 코드 테이블 (정적 데이터)
  tools/           # MCP 툴 9개 (Phase 2 + Phase 10 분석 툴 2개)
tests/             # pytest + respx (123건)
scripts/           # 일회성 스크립트 (코드 테이블 추출 등)
docs/              # 설계·운영 문서 (PHASE1~10, ADR)
  adr/             # Architecture Decision Records (Phase 10에서 신설)
workers/           # Cloudflare Workers + Durable Objects (Phase 9, TypeScript)
web/               # 인터랙티브 분석 대시보드 8 페이지 (Phase 10 Stage 10.5)
data/              # SQLite 영속 store (gitignore, Phase 6+)
scratch/           # PoC + Parquet 스냅샷 (gitignore, Phase 10)
logs/              # 런타임 로그 (gitignore됨)
```

## 코딩 규약

- **언어:** Python 3.12+ (`from __future__ import annotations` 항상)
- **타입:** mypy `strict=true` 통과해야 함. `Any` 남발 금지.
- **린트:** ruff (`pyproject.toml` 규칙). 매직 넘버는 `MAX_NUM_OF_ROWS` 같은 모듈 상수로.
- **포맷:** ruff format (line-length=100).
- **불변성:** mutation 지양. 새 객체 반환.
- **파일 크기:** 한 파일 800줄 넘기지 말 것. 응집도 높게 분할.
- **에러 처리:** 외부 호출은 항상 try/except + 의미 있는 메시지. 시크릿(SERVICE_KEY)은 절대 메시지에 포함 X.
- **주석:** WHAT 설명 금지(코드가 함). WHY가 비자명할 때만.
- **UI/디자인:** `web/` 대시보드 변경 시 루트 `DESIGN.md` 를 진실의 원천으로 따를 것 (색·모서리·간격 토큰, 2단계 내비 IA, 차트 색 단일 소스, docs 읽기모드 서브브랜드). 새 디자인 결정은 DESIGN.md 먼저 갱신 후 코드.

## 시크릿

- `SERVICE_KEY` (data.go.kr) — 절대 커밋 X. `.env` 만 사용. `.env.example`에 빈 값으로 표기.
- `VWORLD_KEY` (선택) — 지오코딩용.

## 자주 쓰는 명령

| 목적 | 명령 |
|---|---|
| 테스트 | `python -m pytest -q` |
| 린트 | `python -m ruff check .` |
| 타입체크 | `python -m mypy src/` |
| 코드 테이블 재생성 | `python scripts/extract_sigungu.py` |
| 로컬 서버 (Phase 3 이후) | `ev-mcp` |

## AI 보조 도구에게

- Phase 단위로 작업하고, 각 Phase 끝에서 그린 테스트 + 린트 + 타입체크 확인 후 리포트.
- 새 의존성 추가 시 `pyproject.toml` 만지지 말고 사용자에게 먼저 확인.
- `한국환경공단_..._v1.23.docx` 는 진실의 원천. 모델/필드 변경 시 반드시 이 문서와 대조.
- 한국어 응답이 기본. 코드 식별자는 영어, 사용자 노출 라벨/에러는 한국어.
