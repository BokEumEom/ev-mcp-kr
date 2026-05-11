---
name: mcp-tool-recipe
description: ev-mcp 프로젝트에서 새 MCP 툴(`src/ev_mcp/tools/*.py` 또는 `workers/src/tools/*.ts`)을 작성하는 표준 레시피. 시그니처·도크스트링·테스트·에러 처리·토큰 예산까지 한 번에. 새 MCP 툴 추가, 기존 툴 시그니처 변경, "툴 만들어줘" 같은 요청에 반드시 트리거. python-builder / workers-builder 가 사용.
---

# MCP Tool Recipe — 새 툴 작성 레시피

ev-mcp 의 모든 MCP 툴은 이 레시피를 따른다. `.claude/rules/mcp-tool-conventions.md` 의 확장판.

## 파일 구조 규칙

**Python (`src/ev_mcp/tools/`):**
- 한 파일에 한 툴: `src/ev_mcp/tools/{tool_name}.py`
- 헬퍼는 `_helpers.py` 또는 `codes_lookup.py`
- 테스트: `tests/test_tools_{tool_name}.py`

**Workers (`workers/src/tools/`):**
- 한 파일에 한 툴: `workers/src/tools/{tool-name}.ts`
- 헬퍼는 `_helpers.ts`
- 테스트: 같은 디렉토리의 `{tool-name}.test.ts` 또는 `workers/test/`

## 시그니처 규칙

### Python

```python
@mcp.tool(annotations={"readOnlyHint": True})
async def tool_name(
    *,                                # keyword-only
    lat: float | None = None,         # optional 은 항상 None 기본값
    address: str | None = None,
    radius_km: float = 2.0,
    limit: int = 20,                  # 기본값 합리적 (20~50)
) -> list[ChargerNearby]:             # Pydantic 모델 또는 list[...]
    ...
```

규칙:
- 모든 입력 keyword-only (`*` 뒤)
- 타입 명시
- Optional 은 `None` 기본값 (빈 문자열 금지)
- 반환은 Pydantic 모델 또는 `list[Model]` (dict 금지 — FastMCP 가 직렬화)

### Workers (TypeScript)

```ts
export const findChargersNearby = tool(
  {
    name: "find_chargers_nearby",
    description: "...",
    inputSchema: z.object({
      lat: z.number().optional(),
      address: z.string().optional(),
      radius_km: z.number().default(2.0),
      limit: z.number().int().default(20),
    }),
    readOnlyHint: true,
  },
  async (input, ctx) => { ... }
);
```

## 도크스트링 (= Claude 가 읽는 툴 설명)

**Python:**
```python
def find_chargers_nearby(...):
    """좌표/주소 기준 반경 내 충전기 찾기.

    위치 정보를 lat+lng 또는 address 중 하나로 제공. address 만 있으면
    내부 VWorld 지오코더로 좌표 변환 후 반경 검색.

    예시
    ----
    "강남역 근처에 사용 가능한 급속 충전기 있어?"
        → address="서울 강남구 강남대로 396", available_only=True, charger_type=["04","06"]
    """
```

규칙:
- 첫 줄: 한국어 한 줄 요약 (Claude 가 가장 비중 있게 본다)
- 본문: 언제 쓰는지 / 입력 의미 / 출력 구조 각 한 단락
- 마지막 "예시" 섹션에 자연어 질문 1~2개 + 입력 매핑

## 토큰 예산

- 한 응답 **25,000 토큰 미만**
- `limit` 기본값 합리적 (20~50)
- 큰 결과 예상되면 `head_only=True` 또는 페이지네이션 인자 (`offset`/`cursor`)
- 큰 텍스트 필드(`note`, `addr`)는 길면 잘라서 반환 (`addr_short` 같은 필드 신설 검토)

## 에러 처리

**Python:**
```python
try:
    rows = await client.get_charger_info(...)
except EvChargerError:
    raise  # FastMCP 가 user-facing 으로 직렬화
except httpx.HTTPStatusError as e:
    raise EvChargerError(f"데이터고고개알 호출 실패: status={e.response.status_code}")
    # ^ 절대 e.request.url 그대로 넣지 말 것 — SERVICE_KEY 누출
```

**Workers (TypeScript):**
```ts
try {
  const rows = await fetchChargerInfo(input);
} catch (e) {
  if (e instanceof Response && e.status >= 500) {
    throw new ToolError("upstream 5xx");
  }
  throw e;
}
```

규칙:
- 외부 호출 실패 → 의미 있는 도메인 예외 (Python: `EvChargerError`, TS: `ToolError`)
- 잘못된 입력 → 즉시 `ValueError` (Python) / Zod 검증 (TS)
- **빈 결과를 silent 반환 금지** — 0건이면 빈 list + 보고 메시지에 명시
- **httpx/fetch 예외 메시지에 URL 그대로 노출 금지** — SERVICE_KEY 는 URL 쿼리에 있음

## 테스트 최소 셋 (한 툴 = 3 테스트 필수)

### 1) 해피 패스
정상 입력 → 기대한 모델 반환. respx 또는 msw 로 외부 호출 모킹.

### 2) 빈 결과
응답이 0건일 때 → 빈 list 또는 적절한 sentinel. 에러 던지지 않음.

### 3) 잘못된 입력
필수 인자 누락 또는 타입 위반 → 즉시 ValueError (또는 Zod 검증 실패).

**테스트 작성 시:**
- 실제 data.go.kr 호출 금지 (CI 키 없음)
- 응답 fixture 는 docx 예시 또는 실제 응답 마스킹본 사용
- SERVICE_KEY 가 fixture URL 에 들어가면 마스킹 (예: `serviceKey=REDACTED`)

## 안전 어노테이션

이 프로젝트 v1 의 모든 툴은 read-only:
```python
@mcp.tool(annotations={"readOnlyHint": True})
```

`destructiveHint=True` 사례 0. 사이드 이펙트 있으면 즉시 멈추고 검토.

## 작성 후 자기 검증 (필수)

**Python:**
```bash
source .venv/bin/activate
python -m pytest tests/test_tools_{name}.py -q
python -m ruff check src/ev_mcp/tools/{name}.py tests/test_tools_{name}.py
python -m mypy src/
```

**Workers:**
```bash
cd workers
npx vitest run src/tools/{name}.test.ts 2>&1 | tail -10
npx tsc --noEmit 2>&1 | head -20
```

3개(또는 2개) 모두 그린 확인 후 phase-orchestrator 에게 완료 보고.

## 절대 금지

- SERVICE_KEY 직접 다루기 (Settings 통해서만)
- 외부 응답 본문 그대로 사용자 노출 — Pydantic/Zod 모델 한 번 거치기
- 도크스트링/주석에 "TODO: 나중에..." — 그 자리에서 끝내거나 todo 등록
- 추측으로 docx 필드 만들기 — 반드시 docx 인용
- dict 반환 (FastMCP/Workers 가 직렬화 — Pydantic/Zod 모델로)
