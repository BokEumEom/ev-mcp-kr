---
name: phase-cycle
description: ev-mcp 프로젝트의 Phase 8단계 사이클(plan→tasks→impl→verify→review→fix→verify→doc)을 팀으로 자동 실행하는 오케스트레이터. "Phase N 시작", "/phase-cycle N", "Phase N 진행해줘" 같은 표현이 나오면 반드시 사용. phase-orchestrator 에이전트가 트리거.
---

# Phase Cycle — 8단계 자동 진행 오케스트레이터

ev-mcp 의 `docs/WORKFLOW.md` 가 정의한 8단계 사이클을 한 팀으로 끝까지 수행한다.

## 실행 모드

**에이전트 팀.** 세션 시작 시 `TeamCreate` 로 다음 팀 구성:

```
team_name: "ev-mcp-phase-{N}"
members: [python-builder, workers-builder, quality-gate, spec-auditor]
leader: phase-orchestrator (자신)
```

## 8단계 흐름

```
①plan-read    → phase-orchestrator
②tasks        → phase-orchestrator (TaskCreate × 3~7)
③impl         → python-builder OR workers-builder (todo별 위임)
④verify       → quality-gate (verify-stack)
⑤review       → quality-gate (code-review + secret-hygiene)
⑥fix          → builder (CRITICAL/HIGH 처리)
⑦verify-again → quality-gate
⑧doc          → phase-orchestrator (phase-doc-format)
```

## 단계별 상세

### ① plan-read
**책임:** phase-orchestrator
- `docs/PLAN.md` 의 "Phase N" 섹션 읽기
- `docs/PHASE{N-1}.md` "다음 단계" + "변경 이력" 확인
- 미해결 이슈가 있으면 todo 에 반영
- `.claude/rules/phase-workflow.md` 와 `.claude/rules/mcp-tool-conventions.md` 재확인

### ② tasks
**책임:** phase-orchestrator
- `TaskCreate` 로 3~7개 todo 등록
- 각 todo 는 한 파일 또는 한 책임 단위
- 테스트는 별도 todo 가 아니라 구현 todo 안에 포함
- 위 todo 마다 `metadata.area = "python" | "workers"` 부여 (위임 대상 결정)

### ③ impl
**책임:** python-builder 또는 workers-builder
- todo 의 `metadata.area` 에 따라 `TaskUpdate(owner=...)` 로 위임
- builder 는 in_progress 마크 → 코드+테스트 작성 → 자기 검증 → completed
- 양쪽 다 변경되는 todo 는 의존성 설정 후 순차

**위임 메시지 템플릿 (SendMessage):**
```
to: python-builder (또는 workers-builder)
body: "todo #{id} 작업 시작 요청.
       범위: {파일 또는 책임}.
       관련 룰: {.claude/rules/...}
       완료 후 자기 검증(pytest/ruff/mypy 또는 vitest/tsc) 결과와 함께 보고."
```

### ④ verify
**책임:** quality-gate
- `verify-stack` 스킬 트리거
- 변경 경로에 `src/` 가 있으면 pytest+ruff+mypy
- 변경 경로에 `workers/` 가 있으면 vitest+tsc
- 양쪽 다면 둘 다

**그린 아니면 ⑤ 진행 금지.** 한 라운드 픽스 요청 후 재실행. 두 번째도 실패 시 사용자에게 보고.

### ⑤ review
**책임:** quality-gate
- 변경 파일 기준 code-review (CRITICAL/HIGH/MEDIUM/LOW 분류)
- `secret-hygiene` 정적 검사 동시 수행
- verdict 셋 중 하나: "Phase 진행 OK" / "수정 후 진행" / "지금 멈춤"

**"지금 멈춤" = 사용자에게 즉시 보고 + 사이클 중단.** secret 누출은 무조건 멈춤.

### ⑥ fix
**책임:** builder (review 발견 사항이 어느 영역인지에 따라)
- quality-gate 가 builder 에게 픽스 요청 메시지 발신
- CRITICAL/HIGH 만 필수, MEDIUM 은 가능하면, LOW/NIT 은 todo 백로그
- 회귀 테스트 추가 필수

### ⑦ verify-again
**책임:** quality-gate
- ④ 와 동일한 절차 재실행
- 그린이 아니면 다시 ⑥ — 무한 루프 방지를 위해 3회 시도 후 정지 + 사용자 보고

### ⑧ doc
**책임:** phase-orchestrator
- `phase-doc-format` 스킬 트리거
- `docs/PHASE{N}.md` 작성: 변경 파일 / 테스트 / 회귀 / 다음 단계 / 변경 이력
- 마지막 todo `completed` 마크
- 팀 해산 안내 한 줄

## 정지 신호 (자동 중단 조건)

| 조건 | 조치 |
|---|---|
| ④ verify 2회 연속 fail | 사용자 보고, 사이클 정지 |
| ⑤ review CRITICAL 발견 | 사이클 일시 정지, 사용자 확인 후 재개 |
| 시크릿 누출 의심 | 즉시 정지, `.claude/rules/secrets.md` 사고 대응 |
| docx 와 모델 불일치 의심 | spec-auditor 호출, 결과 확인 후 재개 |
| `pyproject.toml` 또는 `package.json` 수정 필요 | 사용자 컨펌 받기 전 정지 |

## 단축 규칙

**⑤ review 생략 가능 조건:**
- 변경이 docstring/주석 only
- 또는 한 줄 typo
- 또는 `docs/*.md` 만 변경

**⑧ doc 생략 가능 조건:**
- Phase 가 다른 Phase 의 단순 픽스만 다루는 경우
- 이때는 `docs/PHASE{N}.md` 의 "변경 이력" 섹션에 한 줄 추가

## 사용자에게 보여주는 진행 상태

각 단계 시작/종료 시 한 줄:

```
[①plan-read] PLAN.md Phase 8 + PHASE7.md 읽음. 범위: SQLite WAL 모드.
[②tasks] todo 4개 등록: store.py / sync.py / tests / 회귀
[③impl] python-builder ← store.py 위임...
  └ python-builder: src/ev_mcp/store.py + tests/test_store.py 작성. pytest 5건 그린.
[④verify] VERIFY OK — pytest 107건 / ruff clean / mypy clean
[⑤review] verdict: Phase 진행 OK (HIGH 0, MEDIUM 2 todo 백로그)
[⑦verify-again] (skipped — review verdict OK)
[⑧doc] docs/PHASE8.md 작성됨.
✅ Phase 8 완료.
```

## 테스트 시나리오

**정상 흐름:** "Phase 9 시작" → 8단계 자동 진행, 최종 `docs/PHASE9.md` 생성, 모든 todo completed.

**에러 흐름:** ⑤ review 에서 CRITICAL (SERVICE_KEY 가 새 로그 라인에 들어감) 발견 → 사이클 즉시 정지, 사용자에게 "CRITICAL [심각도] 파일:라인" 보고 → 사용자 컨펌 후 ⑥ fix 재개.
