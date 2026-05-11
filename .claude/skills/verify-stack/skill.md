---
name: verify-stack
description: ev-mcp 의 통합 verify 스킬 — Python(pytest+ruff+mypy)과 Workers(vitest+tsc) 모두 한 번에 실행하고 결과를 한 줄로 요약. /verify 슬래시 명령보다 강화된 버전 (workers/ 검증 포함). quality-gate 에이전트가 ④/⑦ 단계에서 트리거.
---

# Verify Stack — Python + Workers 통합 검증

ev-mcp 는 두 코드베이스(`src/ev_mcp/` Python + `workers/` TypeScript)를 가진다. 기존 `/verify` 슬래시 명령은 Python 만 본다. 이 스킬은 둘 다 본다.

## 언제 실행하는가

변경 경로를 보고 결정:
- `src/ev_mcp/**` 또는 `tests/**` 변경 → **Python 스택**
- `workers/**` 변경 → **Workers 스택**
- 둘 다 → 둘 다

확인 방법:
```bash
git diff main --name-only 2>/dev/null | head -50
# 또는 phase-orchestrator 가 알려준 파일 목록 사용
```

## Python 스택 실행

```bash
source .venv/bin/activate
echo "--- pytest ---"
python -m pytest -q
echo "--- ruff ---"
python -m ruff check .
echo "--- mypy ---"
python -m mypy src/
```

**자동 수정 금지** — `ruff --fix`, mypy 자동 패치 등 X.

## Workers 스택 실행

```bash
cd workers
echo "--- vitest ---"
npx vitest run 2>&1 | tail -15
echo "--- tsc ---"
npx tsc --noEmit 2>&1 | tail -20
echo "EXIT=$?"
```

`tail` 로 마지막 줄만 — 출력이 길면 핵심 메시지만 추출.

## 출력 포맷

### 모두 그린

```
VERIFY OK — pytest {N}건 / ruff clean / mypy strict clean / vitest {M}건 / tsc clean
```

한쪽만 실행했으면 해당 부분만:
```
VERIFY OK — pytest {N}건 / ruff clean / mypy clean (Python only — workers/ 변경 없음)
```

### 하나라도 실패

```
VERIFY FAIL — {tool}: {파일:라인 또는 핵심 메시지 한 줄}
```

예시:
```
VERIFY FAIL — mypy: src/ev_mcp/tools/nearby.py:42 — Argument 1 to "haversine" has incompatible type "str"; expected "float"
```

여러 도구가 동시 실패하면 가장 심각한 것부터 (mypy > pytest > vitest > ruff > tsc 순).

## 보고 본문 + verdict

전체 stdout 그대로 노출 + 마지막 줄에 위 포맷 한 줄. 그게 전부.

추가 작업 X. 자동 수정 X. 픽스는 builder 가.

## 에러 케이스

| 상황 | 처리 |
|---|---|
| `.venv` 없음 | 실행 안 함, "환경 미준비: `uv venv .venv && source .venv/bin/activate && uv pip install -e .[dev]`" 보고 |
| `workers/node_modules` 없음 | "워커 의존성 미설치: `cd workers && npm install`" 보고 |
| pytest 가 collection error | failed tests 가 아니라 collection error 임을 명시 |
| `git diff main` 실패 (main 없음) | `git diff --name-only HEAD~1` 시도, 그것도 실패면 전체 검증 |

## phase-cycle 과의 연결

quality-gate 가 이 스킬을 트리거할 때:
1. `SendMessage(from=phase-orchestrator)` 로 변경 파일 목록 수신
2. 위 스택 결정 로직으로 실행 범위 결정
3. 결과를 `SendMessage(to=phase-orchestrator)` 로 회신
4. 실패 시 어느 builder 에게 픽스 요청할지도 함께 제안 (파일 경로 기준)
