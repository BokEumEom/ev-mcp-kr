---
description: 새 Phase 진입 — 계획서·직전 Phase 보고서 읽고 todo 만들기. 인자로 Phase 번호 (예 /phase-start 2).
---

Phase **$ARGUMENTS** 를 시작합니다.

다음 순서로 진행하세요:

1. **계획서 읽기**: `docs/PLAN.md` 의 "Phase $ARGUMENTS" 섹션을 읽고 범위·목표 확인.

2. **직전 Phase 보고서 읽기**: `docs/PHASE$((ARGUMENTS - 1)).md` 의
   "다음 단계" 와 "변경 이력" 섹션 확인. 미해결 이슈가 있으면 todo에 반영.

3. **워크플로우 룰 재확인**: `.claude/rules/phase-workflow.md`,
   `.claude/rules/mcp-tool-conventions.md` (해당 Phase가 툴 작성 포함 시).

4. **TaskCreate 호출**: 이 Phase 의 작업을 3~7개 todo 로 쪼개 등록.
   - 각 todo는 한 파일 또는 한 책임 단위.
   - 테스트는 별도 todo 가 아니라 구현 todo 안에 포함 ("코드 + 테스트 같이").

5. **첫 번째 todo 를 in_progress** 로 마크하고 즉시 작업 시작.

todo 등록이 끝나면 사용자에게 한 줄 요약: "Phase $ARGUMENTS 시작. {N}개 todo 등록. 첫 작업: {subject}".
