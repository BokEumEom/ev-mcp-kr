# Anatomy of a Claude Code Project — ev-mcp

이 프로젝트는 Claude Code(또는 다른 AI 코딩 보조 도구)와 사람이 같이 작업하는 것을 전제로 디렉터리를 짰습니다. 어디에 무엇이 있고, AI가 어떤 파일을 어떤 순서로 읽어야 하는지를 정리합니다.

---

## 1. 큰 그림

```text
ev_mcp/
├─ CLAUDE.md                     # AI가 가장 먼저 읽는 컨텍스트
├─ README.md                     # 사람(사용자)이 가장 먼저 읽는 문서
├─ pyproject.toml                # 의존성·빌드·린트 단일 진실 원천
├─ .env.example                  # 시크릿 키 템플릿 (.env 는 gitignore)
│
├─ src/ev_mcp/                   # 패키지 본체
│   ├─ __init__.py               # __version__
│   ├─ settings.py               # 환경변수 → Settings 객체
│   ├─ models.py                 # Pydantic 타입 (스펙 1:1)
│   ├─ client.py                 # 외부 API 호출
│   ├─ cache.py                  # (Phase 2) 캐시 계층
│   ├─ geocode.py                # (Phase 2) 주소 → 좌표
│   ├─ server.py                 # (Phase 3) FastMCP 진입점
│   ├─ tools/                    # (Phase 2) MCP 툴 한 파일에 하나
│   └─ codes/                    # 정적 데이터 (코드 테이블 JSON)
│
├─ tests/                        # pytest + respx
│   ├─ conftest.py               # 공통 fixture (settings 등)
│   ├─ fixtures/                 # 샘플 응답 JSON
│   ├─ test_client.py
│   ├─ test_models.py
│   └─ test_tools_*.py           # (Phase 2)
│
├─ scripts/                      # 일회성 스크립트
│   └─ extract_sigungu.py        # docx → sigungu.json
│
├─ docs/                         # 설계·운영 문서
│   ├─ ARCHITECTURE.md           # ← 이 파일
│   ├─ PHASE1.md                 # Phase별 결과 보고서
│   ├─ PRIVACY.md                # (Phase 5) Claude 제출 필수
│   └─ SUPPORT.md                # (Phase 5) Claude 제출 필수
│
├─ logs/                         # 런타임 로그 (gitignore)
└─ 한국환경공단_..._v1.23.docx    # API 명세 원본 (진실의 원천)
```

## 2. 파일별 역할 — AI가 읽어야 할 우선순위

| 우선순위 | 파일 | 언제 읽나 |
|---|---|---|
| 1 | `CLAUDE.md` | 모든 작업 시작 전 |
| 2 | `docs/PLAN.md` | 무엇을 만들지 모를 때 |
| 3 | `docs/PHASE*.md` | 직전까지 무엇이 끝났는지 알고 싶을 때 |
| 4 | `pyproject.toml` | 의존성/규칙을 알아야 할 때 |
| 5 | `한국환경공단_..._v1.23.docx` | 모델·필드 의문이 생길 때 |
| 6 | `src/ev_mcp/**` | 실제 변경이 필요할 때 |

## 3. 계층(Layer) 분리

```text
┌────────────────────────────────────────────┐
│  MCP Layer  (server.py, tools/*)           │  ← Claude가 호출하는 면
├────────────────────────────────────────────┤
│  Domain Layer  (cache.py, geocode.py)      │  ← 비즈니스 로직
├────────────────────────────────────────────┤
│  Adapter Layer  (client.py, settings.py)   │  ← 외부 시스템 어댑터
├────────────────────────────────────────────┤
│  Type Layer  (models.py, codes/*.json)     │  ← 진실의 타입
└────────────────────────────────────────────┘
```

**의존 방향은 위 → 아래만 허용.** 즉 `client.py` 는 절대 `tools/*` 를 import 하지 않습니다. `models.py` 는 어떤 다른 모듈도 import하지 않습니다(외부 라이브러리만).

## 4. AI가 변경해도 안전한 영역 vs 신중해야 할 영역

| 영역 | 안전도 | 비고 |
|---|---|---|
| `tests/` | 매우 안전 | 실패하면 알려줌 |
| `tools/*.py` | 안전 | 한 파일에 한 툴, 격리됨 |
| `cache.py`, `geocode.py` | 보통 | 단위 테스트 충분히 |
| `client.py` | 신중 | 외부 API 변화·에러 처리 민감 |
| `models.py` | 매우 신중 | docx 스펙과 1:1 대응 필수 |
| `codes/*.json` | 매우 신중 | 직접 편집 X. `scripts/extract_*.py` 로 재생성 |
| `settings.py` | 신중 | env var 추가 시 `.env.example` 도 같이 |
| `pyproject.toml` | 사람만 | 사용자 확인 후 변경 |

## 5. 협업 사이클(Phase 단위)

각 Phase는 다음 6단계로 진행합니다.

1. **계획**: 계획서의 Phase 섹션 다시 읽기.
2. **TaskCreate**: 작업을 3~7개 항목으로 쪼개 todo 리스트.
3. **구현**: 한 작업씩 `in_progress` → 코드 작성 → `completed`.
4. **검증**: `pytest`, `ruff`, `mypy` 셋 다 그린.
5. **리뷰**: `code-reviewer` 에이전트로 변경분 점검. CRITICAL/HIGH 처리.
6. **보고**: `docs/PHASE{N}.md` 에 결과 정리.

## 6. 시크릿·보안 규약

- `SERVICE_KEY` 는 `.env` 에서만. 절대 코드, 테스트, 로그, 에러 메시지에 등장 금지.
- `Settings.service_key` 는 `SecretStr` — 실수로 `print(settings)` 해도 마스킹됨.
- 외부 API 응답을 그대로 사용자에게 노출할 때, 시크릿이 섞여 있지 않은지 확인.
- 새 외부 API 키가 필요하면 사용자에게 먼저 문의 → `.env.example` 에 빈 값 추가 → `Settings` 에 `SecretStr` 필드 추가.

## 7. 의사결정 기록 (ADR + Phase 보고서)

큰 의사결정은 두 곳에 기록합니다:

1. **`docs/PHASE{N}.md`** — Phase 별 결과 보고서 (인라인 의사결정 + 산출물)
2. **`docs/adr/ADR-{NNN}-{title}.md`** — Phase 10 부터 신설. 외부 시스템 도입·폐기·교체 같이 6개월 후 "왜?" 라고 물을 만한 결정 박제. 결정 근거 + 대안 비교 + 롤백 계획. 인덱스는 `docs/adr/README.md`.

핵심은 **계획서** + **Phase 보고서** + **ADR** 세 곳을 보면 의사결정 흐름이 보이도록 한다는 것.

이미 정해진 큰 결정들:

- **하스팅:** Render (Python). CF Workers 는 Phase 9 에서 TypeScript 로 별도 포팅됨.
- **인증:** No-auth MCP. 데이터가 공공이므로 OAuth 불필요.
- **언어/프레임워크:** Python 3.12 + FastMCP 2.x (메인) / TypeScript + agents-mcp (Workers).
- **도구 디자인:** 9개 가치 추가형 툴 (raw passthrough 아님). Phase 10 에서 분석 툴 2개 추가.
- **저장소:** in-memory cache (Phase 2) → SQLite 영속 (Phase 6) → DuckDB 분석 사이드카 (Phase 10, ADR-001).
- **시각화:** 인터랙티브 web 대시보드 (Phase 10 Stage 10.5). 순수 정적 자산.

## 8. 부가 디렉토리 (Phase 6+ 추가)

- **`workers/`** (Phase 9) — Cloudflare Workers + Durable Objects TypeScript 포팅. `src/` 와 독립 sister codebase. 두-DO 아키텍처. vitest.
- **`web/`** (Phase 10 Stage 10.5) — DuckDB-WASM + Chart.js + Leaflet 인터랙티브 분석 대시보드 8 페이지. 빌드 step 없음. 자세히는 `web/README.md`.
- **`scratch/`** (Phase 10, gitignore) — PoC + Parquet 스냅샷.
- **`data/`** (Phase 6, gitignore) — SQLite 영속 store (`chargers.db`).

## 8. AI에게 주는 명시적 신호

- `CLAUDE.md` 에 적힌 룰은 시스템 프롬프트보다 우선합니다.
- 모르는 게 있으면 질문. 추측 금지.
- 새 의존성 추가 시 사용자 컨펌.
- 시크릿 노출 의심되면 즉시 멈추고 보고.
- 사용자가 한국어로 말하면 한국어로 답하세요.
