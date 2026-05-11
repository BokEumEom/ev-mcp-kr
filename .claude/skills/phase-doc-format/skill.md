---
name: phase-doc-format
description: ev-mcp 의 `docs/PHASE{N}.md` 보고서 작성 포맷. Phase 종료 시(⑧단계) 변경 파일·테스트·회귀·다음 단계·변경 이력을 일관된 구조로 기록. phase-orchestrator 가 사이클 마지막에 트리거.
---

# Phase Doc Format — PHASE{N}.md 작성 표준

ev-mcp 의 Phase 보고서는 `docs/PHASE{N}.md` 한 파일. 다음 구조를 따른다.

## 기존 보고서 참조

작성 전 반드시 직전 1~2개 보고서 읽고 톤·디테일 수준 맞추기:
- `docs/PHASE7.md`, `docs/PHASE9.md` (가장 최근)
- `docs/PHASE6.md` (SQLite 영속 — 큰 Phase 예시)

## 표준 섹션

```markdown
# Phase {N} — {한 줄 제목}

**기간:** {YYYY-MM-DD} (단일일) 또는 {시작}~{종료}
**범위:** {1~2 문장. Phase 의 목적과 결과물}

---

## 산출물

### 코드
- `{경로}` — {한 줄 설명}
- ...

### 테스트
- `{경로}` — {N개 테스트, 무엇을 검증}
- ...

### 문서
- `{경로}` — {변경/신규 표시}

---

## 핵심 변경 사항

{2~5개 bullet. 각 bullet 은 1~3 문장. WHY 중심으로 (WHAT 은 코드가 함).}

예시:
- **Smart upsert 도입** (`workers/src/inventory_store.ts`): DO SQL rows-written 무료 캡(~1M/월)을 우회하기 위해 stat_upd_dt 변경된 row 만 INSERT OR REPLACE. processedRows / writtenRows 분리 계측.

---

## 검증

- pytest: {N}건 통과 (커버리지 {%})
- ruff: clean
- mypy strict: clean
- vitest: {M}건 (해당 시)
- tsc: clean (해당 시)
- 리뷰 verdict: {phase-cycle ⑤ 의 verdict 인용}

---

## 회귀 방어

이 Phase 가 추가한 회귀 테스트:
- `{경로}::{테스트명}` — {어떤 회귀를 막는가}

---

## 다음 단계

다음 Phase 진입 시 반드시 확인할 사항:
- {미해결 todo 또는 백로그}
- {외부 의존성 변경 여파}
- {운영 모니터링 항목 추가}

---

## 변경 이력

- {YYYY-MM-DD} {한 줄}
- (작은 fixup commit 도 여기에 누적 — 별도 Phase 만들 정도 아니면)
```

## 작성 규칙

1. **한국어 기본.** 코드 식별자/경로는 영어, 본문은 한국어.
2. **WHY 중심.** WHAT 은 코드가 설명함. 보고서는 "왜 이렇게 했나"에 집중.
3. **검증 섹션은 사실만.** "통과했음" 같은 추정 X. 실제 `/verify` 출력 숫자 그대로.
4. **회귀 방어 섹션은 필수.** 이 Phase 가 픽스한 버그가 있으면 그것을 막는 테스트를 명시.
5. **다음 단계는 actionable.** "추가 고려" 같은 막연한 표현 X. "PHASE10 진입 시 X 확인" 식.
6. **변경 이력은 누적.** 같은 Phase 의 fixup commit 도 새 줄 추가 (별도 PHASE 만들지 않음).

## 단축 모드 (fixup-only Phase)

Phase 가 다른 Phase 의 단순 픽스만 다루는 경우, 별도 PHASE{N}.md 생성하지 말고 해당 PHASE 의 "변경 이력" 섹션에 한 줄 추가:

```markdown
## 변경 이력
- 2026-04-30 Phase 6 보고서 작성
- 2026-05-08 SQLite WAL 모드 활성화 (`docs/PHASE6.md` 의 후속 픽스, sync 충돌 회귀 막음)
```

## 길이 가이드

- 작은 Phase (변경 < 5 파일): 30~80줄
- 중간 Phase (5~15 파일): 80~150줄
- 큰 Phase (15+ 파일, 새 서브시스템): 150~300줄

300줄 넘으면 분할 검토 (별도 docs/PHASE{N}_DETAIL.md).

## 파일 작성 후 자기 검증

```bash
ls -la docs/PHASE{N}.md  # 파일 존재
wc -l docs/PHASE{N}.md   # 라인 수
grep -c '^## ' docs/PHASE{N}.md  # 섹션 수 (보통 6~7)
```

마지막으로 git diff 로 다른 PHASE 보고서 톤과 비교.

## phase-cycle 과의 연결

phase-orchestrator 가 ⑧ doc 단계에서:
1. 이 스킬 트리거
2. ② tasks 의 todo 목록 + 실제 변경된 파일(`git diff main --stat`) + ⑤ review verdict 를 입력으로
3. 위 포맷에 채워 작성
4. 완료 후 사용자에게 경로 + 한 줄 요약 보고
