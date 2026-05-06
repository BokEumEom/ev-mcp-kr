# Workflow — Phase 단위 협업 사이클

이 프로젝트는 사람과 AI 가 같이 작업하면서, 각 Phase 마다 **문서 → 구현 → 리뷰 → 검증 → 보고** 가
일관되게 흐르도록 만들어졌습니다.

## 8단계 사이클

```text
①  /phase-start N      →  계획서 + 직전 PHASE{N-1}.md 읽고 todo 등록
②  TaskCreate × M      →  3~7개 작업 단위
③  impl                →  todo 한 개씩 in_progress → completed (코드+테스트 동시)
④  /verify             →  pytest + ruff + mypy 그린 확인
⑤  /phase-review N     →  code-reviewer 에이전트 디스패치
⑥  fix                 →  CRITICAL/HIGH 처리 + 회귀 테스트
⑦  /verify             →  다시 그린
⑧  /phase-doc N        →  docs/PHASE{N}.md 보고서 작성
```

## 각 단계의 산출물

| 단계 | 산출물 | 위치 |
|---|---|---|
| ① | todo 리스트 | TaskList |
| ③ | 코드 + 테스트 | `src/ev_mcp/`, `tests/` |
| ④/⑦ | verify 로그 | stdout |
| ⑤ | 리뷰 보고서 | 응답 본문 + 필요시 임시 메모 |
| ⑥ | 픽스 + 회귀 테스트 | git diff |
| ⑧ | Phase 보고서 | `docs/PHASE{N}.md` |

## .claude/ 내부 지도

```text
.claude/
├─ settings.json           # 팀 공유: 권한 allowlist
├─ commands/               # 슬래시 명령
│   ├─ verify.md           # /verify
│   ├─ phase-start.md      # /phase-start N
│   ├─ phase-review.md     # /phase-review N
│   ├─ phase-doc.md        # /phase-doc N
│   ├─ spec-check.md       # /spec-check
│   └─ extract-codes.md    # /extract-codes
├─ agents/                 # 사브 에이전트
│   ├─ spec-auditor.md     # docx ↔ 코드 일치성 감사
│   └─ mcp-tool-author.md  # 툴 한 개 작성 전문가
└─ rules/                  # 프로젝트 룰 (CLAUDE.md 보조)
    ├─ secrets.md
    ├─ spec-discipline.md
    ├─ mcp-tool-conventions.md
    └─ phase-workflow.md
```

## 사람 vs AI 책임 분담

| 항목 | 사람 | AI |
|---|---|---|
| 큰 그림 의사결정 | ✅ | (제안) |
| 시크릿 관리 | ✅ | 절대 X |
| `pyproject.toml` 변경 | ✅ 컨펌 | 제안만 |
| 코드 작성 | (리뷰) | ✅ |
| 테스트 작성 | (리뷰) | ✅ |
| 코드 리뷰 | ✅ | 1차 (code-reviewer 에이전트) |
| 보안 이슈 처리 | ✅ | 보고 |
| `.env` 편집 | ✅ | 접근 거부됨 |
| 문서 작성 | (리뷰) | ✅ |
| `git push` | ✅ | 거부됨 (settings.json) |

## Phase 진입 / 종료 체크리스트

### 진입

- [ ] 직전 Phase의 보고서 "다음 단계" 확인
- [ ] 계획서의 해당 Phase 섹션 다시 읽음
- [ ] 미해결 todo 가 없는지 확인 (`TaskList`)
- [ ] `.env` 가 채워져 있고 `python -m pytest -q` 가 그린

### 종료

- [ ] `/verify` 그린
- [ ] `/phase-review N` CRITICAL/HIGH 0건
- [ ] `docs/PHASE{N}.md` 작성됨
- [ ] todo 모두 completed
- [ ] 보안 회귀 테스트 추가됨 (해당 Phase 가 보안에 영향 시)

## 작은 변경 (single-shot)

30분 미만의 작은 픽스/리팩터에는 다음 축약 사이클:

```text
impl → /verify → 변경 노트 (커밋 메시지 또는 PHASE{N}.md 변경 이력)
```

리뷰는 변경 diff 를 다시 한 번 읽는 self-review 로 대체 가능.

## 슬래시 명령 빠른 참조

| 명령 | 언제 |
|---|---|
| `/phase-start N` | 새 Phase 시작 |
| `/verify` | 코드 변경 직후, Phase 종료 직전 |
| `/phase-review N` | Phase 구현 완료 시점 |
| `/phase-doc N` | Phase 모든 검증 통과 후 |
| `/spec-check` | docx 새 버전이 들어왔거나 의문 생길 때 |
| `/extract-codes` | docx 코드 테이블만 변경됐을 때 |
