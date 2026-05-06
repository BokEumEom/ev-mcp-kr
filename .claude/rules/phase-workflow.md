# Rule: Phase 워크플로우

각 Phase 는 다음 8단계 사이클을 따릅니다. 단축 가능하지만 **건너뛰면 안 되는 것: ④ verify, ⑤ review**.

```text
① plan-read    →  계획서의 Phase 섹션 다시 읽기
② tasks         →  TaskCreate 로 3~7개 todo
③ impl          →  한 todo 씩 in_progress → completed (코드 + 테스트 같이)
④ verify        →  /verify (pytest + ruff + mypy 셋 다 그린)
⑤ review        →  /phase-review N (code-reviewer 에이전트)
⑥ fix           →  CRITICAL/HIGH 처리, 회귀 테스트 추가
⑦ verify-again  →  /verify
⑧ doc           →  /phase-doc N (docs/PHASE{N}.md 기록)
```

## 단축 규칙

- **⑤ review 생략 가능 조건:** 변경이 도크스트링/주석 only 또는 한 줄 typo. 그 외에는 무조건 실행.
- **③/④ 미니 루프:** 큰 Phase 는 todo 한두 개 끝날 때마다 mini-verify 가능. ⑤는 Phase 끝에 한 번.
- **⑧ doc 생략 가능 조건:** 한 Phase 가 다른 Phase의 단순 픽스만 다루는 경우 (e.g., 리뷰 반영). 이때는 PHASE{N}.md 의 "변경 이력" 섹션에 한 줄 추가.

## 작은 변경 (single-shot)

Phase 단위가 아닌 작은 픽스(<30분)는 다음 축약 사이클:

```text
tasks(생략) → impl → verify → review(가벼운) → 변경 노트
```

review 는 code-reviewer 에이전트 대신 inline self-review (변경 diff 다시 읽기) 도 OK.

## Phase 진입 가이드

- Phase 진입 전 항상 직전 Phase 의 `docs/PHASE{N-1}.md` 의 "다음 단계" 섹션 확인.
- 새 Phase 의 todo 는 계획서를 그대로 옮겨 적지 말고, 직전 Phase 결과를 반영해 재계산.

## 정지 신호

- ④ 또는 ⑦ verify 가 그린이 아니면 다음 단계 진행 금지.
- ⑤ review 가 CRITICAL 을 던지면 사용자에게 보고하고 fix 우선.
- 시크릿 누출 의심되면 → `.claude/rules/secrets.md` 의 사고 대응.
