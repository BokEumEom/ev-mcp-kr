---
description: Phase N 의 8단계 사이클을 팀 모드로 자동 진행. 인자로 Phase 번호 (예 /phase-cycle 9). 기존 /phase-start ~ /phase-doc 의 자동화 버전.
---

Phase **$ARGUMENTS** 의 사이클을 처음부터 끝까지 팀으로 자동 진행합니다.

## 1. 스킬 트리거

`phase-cycle` 스킬을 호출하세요. 이 스킬은 ev-mcp 의 8단계 사이클(`docs/WORKFLOW.md`)을 정의합니다.

## 2. 팀 구성

다음 팀을 띄우세요 (모두 `model: opus` 또는 정의된 모델 사용):

```
TeamCreate(
  team_name="ev-mcp-phase-$ARGUMENTS",
  members=["python-builder", "workers-builder", "quality-gate", "spec-auditor"]
)
```

리더는 **당신(phase-orchestrator)**.

## 3. 사이클 진행

`phase-cycle` 스킬의 8단계를 그대로 따르세요:

1. **plan-read** — `docs/PLAN.md` 의 Phase $ARGUMENTS 섹션 + `docs/PHASE$(($ARGUMENTS - 1)).md` 읽기
2. **tasks** — TaskCreate 로 3~7 todo, 각 todo 에 `metadata.area = "python" | "workers"` 부여
3. **impl** — todo 의 area 에 따라 python-builder 또는 workers-builder 에게 위임 (TaskUpdate owner 변경 + SendMessage)
4. **verify** — quality-gate 호출 (verify-stack 스킬 트리거)
5. **review** — quality-gate 의 code-review + secret-hygiene
6. **fix** — verdict 가 "수정 후 진행" 또는 "지금 멈춤" 이면 builder 에게 픽스 위임
7. **verify-again** — quality-gate 재호출
8. **doc** — phase-doc-format 스킬 트리거, `docs/PHASE$ARGUMENTS.md` 작성

## 4. 정지 신호 (자동 중단)

다음 중 하나라도 발생하면 즉시 정지하고 사용자에게 보고:

- ④ verify 2회 연속 fail
- ⑤ review verdict 가 "지금 멈춤" (CRITICAL 발견)
- 시크릿 누출 의심
- `pyproject.toml` 또는 `package.json` 변경 필요
- docx 와 모델 불일치 의심 (spec-auditor 호출 후 결과 보고)

## 5. 종료 보고

8단계 모두 완료되면:

```
✅ Phase $ARGUMENTS 완료
- 변경 파일: {N}개
- 테스트: pytest {N} / vitest {M}
- 리뷰: {verdict}
- 보고서: docs/PHASE$ARGUMENTS.md
```

팀은 자동 해산 (다음 Phase 진입 시 재구성).

## 수동 단축 옵션

사용자가 특정 단계만 원하면 기존 슬래시 명령 사용:
- `/phase-start $ARGUMENTS` — ①+② 만
- `/verify` — ④ 만 (Python 만, workers/ 변경분은 빠짐 — 보완은 verify-stack 스킬 사용 권장)
- `/phase-review $ARGUMENTS` — ⑤ 만
- `/phase-doc $ARGUMENTS` — ⑧ 만
