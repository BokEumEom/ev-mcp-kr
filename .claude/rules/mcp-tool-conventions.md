# Rule: MCP 툴 작성 규약

이 프로젝트의 모든 MCP 툴은 다음 규약을 따릅니다.

## 파일 구조

- 한 파일에 한 툴. `src/ev_mcp/tools/{tool_name}.py`.
- 코드 테이블 룩업 같은 작은 유틸은 같은 폴더의 `_helpers.py` 또는 `codes/` 모듈에.

## 시그니처

- 모든 입력은 keyword-only (`*` 뒤에).
- 입력 타입은 명시. `lat: float | None = None`.
- 옵셔널은 항상 `None` 기본값. 빈 문자열 금지.
- 출력은 Pydantic 모델 또는 `list[...]`. dict 금지 (직렬화는 FastMCP가 처리).

## 안전 어노테이션

```python
@mcp.tool(annotations={"readOnlyHint": True})
```

- 이 프로젝트 v1 의 모든 툴은 read-only. `destructiveHint=True` 사례 없음.

## 도크스트링 (= Claude 가 읽는 툴 설명)

- 첫 줄: 한국어 한 줄 요약. (Claude가 가장 비중 있게 봄)
- 본문: 언제 이 툴을 쓰는지, 입력 의미, 출력 구조 한 단락씩.
- 마지막에 "예시" 섹션, 자연어 질문 1~2개 + 그때의 입력 예.

```python
def find_chargers_nearby(
    *,
    lat: float | None = None,
    lng: float | None = None,
    address: str | None = None,
    radius_km: float = 2.0,
    available_only: bool = False,
    limit: int = 20,
) -> list[ChargerNearby]:
    """좌표/주소 기준 반경 내 충전기 찾기.

    위치 정보를 lat+lng 또는 address 중 하나로 제공해야 합니다. address 만 있으면
    내부적으로 VWorld 지오코더로 좌표 변환 후 반경 검색.

    예시
    ----
    "강남역 근처에 사용 가능한 급속 충전기 있어?"
        → address="서울 강남구 강남대로 396", available_only=True, charger_type=["04","06"]
    """
```

## 토큰 예산

- 한 응답 25,000 토큰 미만. `limit` 의 합리적 기본값 (보통 20~50)으로 강제.
- 너무 큰 결과가 예상되면 `head_only=True` 같은 옵션 또는 페이지네이션 인자.

## 에러 처리

- 외부 호출 실패 → `EvChargerError` 그대로 raise. FastMCP 가 알아서 user-facing 에러로 직렬화.
- 잘못된 입력은 `ValueError` 로 즉시 raise (예: lat/lng/address 모두 없음).
- 절대 빈 결과를 silent하게 반환하지 말 것. 0건이면 그렇게 명시.

## 테스트

- 한 툴당 최소 3개 테스트:
  1. 해피 패스
  2. 0건 / 빈 결과
  3. 잘못된 입력 → ValueError
- 외부 호출은 respx 로 모킹. 실제 data.go.kr 호출 금지 (CI에서 키 사용 X).

## readOnlyHint 와 안전성

- "조회만 한다"는 의미. 사용자 데이터 변경, 결제, 외부 알림 발송 등 어떤 사이드 이펙트도 없어야 함.
- 캐시 워밍 같은 내부 사이드 이펙트는 OK.
