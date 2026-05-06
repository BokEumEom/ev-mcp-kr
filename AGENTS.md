# AGENTS.md

이 파일은 Claude Code 외 다른 AI 코딩 도구(Codex, Cursor, Aider, Continue 등)가
이 프로젝트에서 일관된 컨벤션으로 작업할 수 있도록 합니다.
Claude Code 사용자는 `CLAUDE.md` 와 `.claude/` 디렉터리를 먼저 보세요.

## 프로젝트

한국환경공단 EvCharger OpenAPI v1.23 → Claude 원격 MCP 커넥터.

- **언어:** Python 3.12+
- **프레임워크:** FastMCP 2.x
- **호스트:** Render (예정)
- **빌드:** uv + hatchling

## 시작

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env  # SERVICE_KEY 입력
python -m pytest -q
```

## 진실의 원천 (Source of Truth)

- **API 스펙:** `한국환경공단_전기자동차 충전소 정보_OpenAPI활용가이드_v1.23.docx`
- **계획서:** `docs/PLAN.md`
- **아키텍처:** `docs/ARCHITECTURE.md`
- **워크플로우:** `docs/WORKFLOW.md`

## 룰 요약

자세한 룰은 `.claude/rules/` 의 4개 파일:

1. `secrets.md` — `SERVICE_KEY` 는 `.env` 만, 로그/예외 마스킹.
2. `spec-discipline.md` — docx 가 진실의 원천, 코드 테이블 직접 편집 금지.
3. `mcp-tool-conventions.md` — keyword-only 시그니처, Pydantic I/O, readOnlyHint, 한국어 도크스트링.
4. `phase-workflow.md` — 8단계 사이클(plan → tasks → impl → verify → review → fix → verify → doc).

## 코딩 컨벤션

- `from __future__ import annotations` 항상.
- mypy `--strict` 통과. `Any` 회피.
- ruff 룰: `E,F,I,UP,B,SIM,RET,PL,RUF`. line-length 100.
- 한 파일 800줄 미만. 응집도 > 결합도.
- 불변성 우선. mutation 지양.
- 커밋 메시지: `feat: ...`, `fix: ...`, `refactor: ...`, `test: ...`, `docs: ...`, `chore: ...`.

## 검증

작업 종료 전 항상:

```bash
python -m pytest -q && python -m ruff check . && python -m mypy src/
```

세 개 다 그린 아니면 작업 완료로 보고 X.

## 주의

- `pyproject.toml` 변경은 사용자 컨펌 후.
- 새 외부 의존성 추가 금지(컨펌 전).
- `src/ev_mcp/codes/*.json` 직접 편집 금지. `scripts/extract_*.py` 만 사용.
- `.env` 와 진짜 `SERVICE_KEY` 는 절대 커밋·로그·이슈에 노출 X.

## 사용자 응대

- 한국어 응답이 기본.
- 보안 이슈 발견 즉시 멈추고 보고.
- 모르는 건 추측하지 말고 질문.
