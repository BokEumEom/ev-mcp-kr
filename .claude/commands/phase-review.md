---
description: 현재 Phase 의 변경분을 code-reviewer 에이전트로 리뷰. 인자로 Phase 번호.
---

Phase **$ARGUMENTS** 의 변경분을 보안·견고성 관점에서 리뷰합니다.

## 1. 변경 범위 식별

- git 저장소가 초기화된 경우: `git diff main --stat` 로 변경 파일 확인
- 아니면 `docs/PHASE$ARGUMENTS.md` 또는 todo 리스트에서 변경 파일 추정

## 2. code-reviewer 에이전트 디스패치

`Agent` 툴로 `code-reviewer` 서브에이전트 호출. 다음 프롬프트 사용:

> 한국환경공단 EV 충전소 OpenAPI v1.23 을 Claude 원격 MCP 커넥터로 노출하는 프로젝트입니다.
> 작업 디렉터리: `/home/bokeum/ai/ev_mcp`
>
> 컨텍스트 파일:
> - 계획서: `docs/PLAN.md`
> - 가이드: `CLAUDE.md`, `AGENTS.md`
> - 룰: `.claude/rules/secrets.md`, `.claude/rules/spec-discipline.md`,
>        `.claude/rules/mcp-tool-conventions.md`
>
> Phase $ARGUMENTS 의 변경 파일: {여기에 변경 파일 목록}
>
> 리뷰 관점 (우선순위):
> 1. CRITICAL: SERVICE_KEY 누출 가능성 (로그/예외/응답)
> 2. HIGH: 에러 처리 견고성, 모델 정확성, 재시도 정책
> 3. MEDIUM: 타입 안전, 테스트 커버리지, 캐시·페이지네이션 가드
> 4. LOW/NIT: 가독성, 매직 넘버
>
> 발견은 `[심각도] 파일:라인 — 한 줄 / WHY: / FIX:` 포맷. 마지막에 verdict 한국어로
> ("Phase 진행 OK" / "수정 후 진행" / "지금 멈춤").
> 응답은 한국어, 200~500단어.

## 3. 결과 보고

리뷰 결과를 사용자에게 그대로 전달. CRITICAL 또는 HIGH 가 있으면:
- TaskCreate 로 "리뷰 결과 반영" todo 추가
- 워크플로우 룰의 ⑥ fix 단계로 진행

CRITICAL/HIGH 가 없으면 ⑦ verify-again 단계로 바로 진행 권장.
