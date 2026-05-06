# Phase 1 보고 — 골격 + 클라이언트 + 모델 + 코드 테이블

**기간:** 2026-04-30
**범위:** 계획서 Phase 1 (Skeleton & client)
**검증:** `pytest` 11건 통과, `ruff` 클린, `mypy --strict` 클린.

---

## 1. 코드 테이블 (`src/ev_mcp/codes/`)

docx v1.23에서 모든 공통 코드를 추출해 정적 JSON으로 저장. 런타임에 한 번 로드하고 메모리에 상주시킬 예정.

| 파일 | 항목 수 | 설명 |
|---|---:|---|
| `sido.json` | 17 | 시도 zcode (11=서울, 50=제주, 51=강원특별자치도, 52=전북특별자치도) |
| `sigungu.json` | 230 | 시군구 zscode (예: 11680=강남구, 28260=인천 서구) |
| `charger_type.json` | 11 | 01=DC차데모 ~ 11=DC콤보2(버스전용) |
| `stat.json` | 8 | 0=알수없음, 2=충전대기, 3=충전중, 6=예약중, 9=상태미확인 |
| `busi_id.json` | 180 | 운영기관 (ME=기후에너지환경부, EV=에버온, KM=카카오모빌리티 …) |
| `kind.json` | 10 | 충전소 구분 대분류 (A0~J0) |
| `kind_detail.json` | 56 | 충전소 구분 상세 (A001~J007) |

**시군구 추출 자동화:** `scripts/extract_sigungu.py` 가 docx의 `word/document.xml` 을 직접 파싱해 230행을 뽑아냅니다. 목차에도 같은 헤더가 있어 `rfind` 로 본문 섹션만 잡아냈습니다. 다음 v1.24 개정 시 한 번만 다시 돌리면 됩니다.

## 2. 프로젝트 골격

- `pyproject.toml`: hatchling 빌드, Python 3.12+, 의존성 목록(아래), dev 그룹 분리.
- 의존성: `fastmcp>=2.0`, `httpx>=0.27`, `pydantic>=2.7`, `pydantic-settings>=2.4`, `geopy>=2.4`, `uvicorn[standard]`, `starlette`, `structlog`.
- dev 의존성: `pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy`.
- 린트: ruff `E,F,I,UP,B,SIM,RET,PL,RUF`. tests/scripts에는 `PLR2004`(매직 넘버) 면제.
- 타입: mypy `strict=true`, `ignore_missing_imports`.
- `src/ev_mcp/settings.py`: Pydantic-settings로 `.env` 자동 로드. `SERVICE_KEY` 는 `SecretStr`.
- `.env.example`, `.gitignore`, 스텁 `README.md`.

## 3. 모델 (`src/ev_mcp/models.py`)

스펙의 모든 필드를 1:1로 모델링했습니다.

### `ChargerInfo` (30개 필드)
`getChargerInfo` 응답 한 행. 주요 항목:
- 식별자: `stat_id`, `chger_id`
- 위치: `addr`, `addr_detail`, `location`, `lat`, `lng`, `zcode`, `zscode`, `kind`, `kind_detail`
- 운영: `busi_id`, `bnm`, `busi_nm`, `busi_call`, `use_time`
- 상태/충전: `stat`, `stat_upd_dt`, `last_tsdt`, `last_tedt`, `now_tsdt`, `output`, `method`, `power_type`
- 부가: `parking_free`, `note`, `limit_yn`, `limit_detail`, `del_yn`, `del_detail`, `traffic_yn`
- v1.16+: `addr_detail`, v1.19+: `year`, v1.20+: `floor_num`, `floor_type`

### `ChargerStatusRow` (8개 필드)
`getChargerStatus` 응답 한 행. busiId, statId, chgerId, stat + 4종 일시.

### 공통
- `ChargerStatusCode` StrEnum: 0/1/2/3/4/5/6/9 (v1.21에서 확장된 6=예약중, 9=상태미확인 포함).
- alias로 영문 필드명(`statNm`, `chgerType` 등) 그대로 받음 → 파이썬은 snake_case.
- 빈 문자열 → `None` 자동 변환 (`OptStr`).
- `YYYYMMDDHHMMSS` 14자리 → `datetime` 자동 변환 (`OptDt`).
- 업스트림은 KST naive datetime. 시간대 변환은 안 함(원본 유지).

## 4. 클라이언트 (`src/ev_mcp/client.py`)

비동기 httpx 기반. `dataType=JSON` 만 사용 (XML 미지원).

### 두 오퍼레이션
- `get_charger_info(...)` → `getChargerInfo`
- `get_charger_status(...)` → `getChargerStatus`

### 핵심 동작
- **응답 봉투 정규화 `_unwrap_items`:** `{"response": {"header": ..., "body": {"items": {"item": [...]}}}}` 와, 1건일 때 `item` 이 dict로 오는 케이스를 모두 list로 통일.
- **에러 처리:** `resultCode != "00"` → `EvChargerError(result_code=...)`.
- **재시도:** 네트워크/HTTP 에러는 지수 백오프 최대 3회 (0.5s → 1s → 2s).
- **검증:** `period` 1~10, `num_of_rows` ≤ 9999 (스펙 한계).
- **시크릿:** `serviceKey` 는 매 요청마다 settings에서 꺼내 쿼리 파라미터로 주입. 로그에는 들어가지 않음.

### `iter_all_charger_info()`
Phase 2의 캐시 워밍 잡에서 사용. `totalCount` 를 보고 모든 페이지를 비동기로 흘려줌. 약 12k~20k 충전소를 9999행 페이지로 2~3회에 끝냄.

## 5. 테스트 (`tests/`)

11건 전부 통과. respx로 httpx를 모킹.

| 테스트 | 검증 항목 |
|---|---|
| `test_charger_info_full_row_parses` | 전체 필드 파싱 + datetime 변환 + StrEnum |
| `test_charger_info_optional_fields_become_none_on_empty_string` | 빈 문자열 → None |
| `test_charger_status_row_parses` | 상태 행 파싱 |
| `test_get_charger_info_success` | 성공 경로 + 헤더/아이템 분리 |
| `test_get_charger_info_propagates_service_key` | 쿼리에 serviceKey, dataType=JSON 전달 |
| `test_get_charger_info_error_result_code_raises` | resultCode "30" → 예외 |
| `test_get_charger_status_success` | 성공 경로 |
| `test_get_charger_status_handles_single_item_dict` | 1건일 때 `item` 이 dict인 케이스 |
| `test_iter_all_charger_info_pagination` | 25행을 10행씩 3페이지로 페이지네이션 |
| `test_period_validation` | period=15, num_of_rows=10000 → ValueError |
| `test_retry_on_transport_error` | ConnectError 2회 후 성공 |

픽스처는 스펙 v1.23 의 샘플 응답을 그대로 옮겼고, 누락 필드 확인용 minimal row, 단일 dict 케이스, 페이지네이션 합성 케이스를 추가했습니다.

## 6. 검증 결과

```
$ python -m pytest -q
...........                                                              [100%]
$ python -m ruff check .
All checks passed!
$ python -m mypy src/
Success: no issues found in 4 source files
```

## 7. 다음 단계 (Phase 2)

1. `cache.py`: 24h TTL 충전소 정보 + 60s TTL 상태 캐시 (refresh-ahead).
2. `geocode.py`: VWorld 지오코더 + `VWORLD_KEY` 미설정 시 graceful fallback.
3. `tools/`: 7개 가치 추가형 툴.
4. 각 툴별 단위 테스트 (목표 커버리지 ≥80%).
