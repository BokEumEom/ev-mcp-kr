# Phase 11 — DuckDB 시계열 분석 기반

작성일: 2026-05-22
상태: 설계 승인 대기 → 구현 계획 작성 예정

## 배경

Phase 10 은 DuckDB 분석 사이드카(ADR-001)를 도입했다 — `analytics.py` + MCP 툴 2개
(`analyze_operator_health`, `regional_density`) + web 대시보드 8 페이지. 그러나 분석은
**단일 스냅샷 Parquet** 위에서만 돈다. PHASE10.md 가 명시한 핵심 한계:

- 시계열 분석 부재 — 가동률 추세, 신규 설치 곡선, 상태 변동성을 볼 수 없다.
- 요일 분석 미구현 — 단일 스냅샷의 `last_tsdt` 편향 때문에 의도적으로 생략.

이 Phase 는 그 한계를 푸는 **시계열 분석 기반**을 만든다. 날짜별 스냅샷을 축적하고,
analytics 레이어가 다중 스냅샷을 다루게 하고, 첫 시계열 툴 2개로 파이프라인을
end-to-end 증명한다.

## 목표와 비목표

### 목표

1. 날짜별 충전기 스냅샷을 로컬에 축적하는 메커니즘.
2. `analytics.py` 가 다중 스냅샷을 다루도록 확장 — named view 레이어.
3. 첫 시계열 MCP 툴 2개 — `snapshot_diff`, `inventory_trend`.
4. 기존 분석 툴 2개는 무회귀 — 자동으로 최신 스냅샷만 본다.

### 비목표 (의도적 제외)

- **R2 export (Stage 10.1).** 로컬 우선. R2 는 사용자 준비 후 별도 사이클. 단,
  view 레이어는 `snapshot_source` 추상화를 유지해 나중 R2 교체가 깔끔하도록 설계.
- **영속 DuckDB + 일별 집계 롤업 (브레인스토밍 B안).** 로컬 우선 단계라 스냅샷이
  0~며칠치뿐 — 비어있는 롤업 테이블은 premature. view 레이어가 나중 롤업의
  슬롯인 이음새. 스냅샷이 ~60일 이상 쌓이면 후속 Stage 로 진입.
- **운영자/지역별 본격 추세 툴.** Phase 12 로.
- **자유 SQL 툴.** 의도적 제외 — 고정 툴이 예측 가능성·안전성에서 우월.
- **요일 분석.** 다중 스냅샷이 며칠 쌓인 뒤에야 의미. 본 Phase 범위 밖.

## 설계 결정

### 결정 1 — 스냅샷은 "일별 덤프"가 아니라 "sync 관측"

SQLite store(`data/chargers.db`)는 upsert 라 *마지막 sync 시점*의 상태만 담는다.
sync 를 주 1회만 돌리면 매일 스냅샷을 찍어도 7개 동일 파일이 된다.

따라서:

- 스냅샷 Parquet 에 `snapshot_date`(KST export 일자)뿐 아니라 `synced_at`
  (`store.last_synced_at()` — 실제 데이터 신선도)·`row_count` 를 컬럼으로 임베드.
- `ev-mcp-snapshot` 실행 시, 디렉터리의 마지막 스냅샷과 `synced_at` 이 동일하면
  **기록 스킵** (`--force` 로 강제). → 스냅샷 시리즈 == 실제 sync 관측 시리즈.
  중복 파일 0.
- 시계열을 "매일 연속"이 아니라 **불규칙 관측열**로 모델링. 추세 툴은 날짜 간격이
  들쭉날쭉해도 정상 동작.

### 결정 2 — 데이터 정직성 surface

PHASE10 의 가치(요일 분석 의도적 생략 — 데이터 정직성 우선) 그대로. 추세 결과에
각 관측의 `synced_at` 을 함께 노출해, "N일 추세"가 실은 동일 데이터 N벌인 상황을
숨기지 않는다.

### 결정 3 — 스냅샷은 sync 와 분리

`ev-mcp-snapshot` 독립 콘솔이 **주 메커니즘**. `ev-mcp-sync --snapshot` 은 sync 전체
패스 성공 완료 후 같은 로직을 호출하는 편의 기능. 스냅샷 cadence 를 sync cadence 에
종속시키지 않는다.

### 결정 4 — analytics 레이어를 named view 로 전환

현 `{source}` 문자열 placeholder 를 named view 로 교체. 더 깨끗하고 더 안전하다:

- `_ensure_connected()` 가 연결 시 in-memory conn 에 view 2개 생성:
  - `v_all` → `read_parquet(<glob>)` 전체 스냅샷
  - `v_latest` → `v_all WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM v_all)`
- 툴은 평범한 SQL `FROM v_latest` / `FROM v_all`. 호출부에 소스 문자열이 아예 없다
  → R2 자격증명이 caller SQL 로 샐 경로 자체가 소멸 (현 `{source}` 메커니즘의 보안
  목적을 더 잘 달성).
- 소스 해석(local glob vs R2 s3 glob)은 view 생성 시점으로 이동. 설정 오류(R2 버킷
  미설정 등)는 connect 시점에 surface — query 시점보다 이르다.
- 영속 `.duckdb` 파일은 만들지 않는다. view 는 매 연결 재생성(무비용).

## 아키텍처

```text
ev-mcp-sync  ──(data.go.kr)──▶  data/chargers.db  (SQLite, upsert, 이력 없음)
                                      │
                  ev-mcp-snapshot     │  (synced_at 중복 검사 → 스킵 가능)
                                      ▼
                      data/snapshots/chargers_YYYY-MM-DD.parquet
                      (snapshot_date · synced_at · row_count 컬럼 임베드)
                                      │
                  AnalyticsClient._ensure_connected()
                      │  in-memory DuckDB conn 에 view 생성
                      ▼
              v_all  ─────────────────┐
              v_latest ───────────────┤
                                      ▼
        ┌─────────────────────────────┴─────────────────────────────┐
        │  FROM v_latest                       FROM v_all            │
        │  analyze_operator_health             snapshot_diff         │
        │  regional_density                    inventory_trend       │
        └───────────────────────────────────────────────────────────┘
```

## 컴포넌트

### `src/ev_mcp/snapshot.py` (신규)

스냅샷 export 의 단일 입구. SQLite store → 날짜별 Parquet.

- DuckDB 로 `data/chargers.db` ATTACH (sqlite extension) → `COPY (SELECT *,
  DATE '<KST>' AS snapshot_date, TIMESTAMP '<synced_at>' AS synced_at,
  <n> AS row_count FROM s.chargers) TO 'data/snapshots/chargers_YYYY-MM-DD.parquet'
  (FORMAT parquet)`.
- 멱등: 디렉터리의 최신 스냅샷 `synced_at` 과 현재 store `synced_at` 이 같으면 스킵
  (`--force` 로 강제). 같은 날 재실행은 덮어쓰기.
- 임포트 가능 함수 `write_snapshot(store, snapshot_dir, *, force=False) -> Path | None`
  (None = 스킵). CLI 엔트리 `ev-mcp-snapshot`.
- `data/snapshots/` 가 없으면 생성.

### `src/ev_mcp/analytics.py` (수정)

- `_source_expr()` 제거, `_create_views(conn)` 추가 — local/R2 소스에 따라 `v_all`·
  `v_latest` 생성.
- `_ensure_connected()` 가 view 생성을 포함.
- `query(sql_template, params)` — `{source}` 검증 제거. 평범한 SQL 실행. 시크릿
  마스킹(`_redact`)·`AnalyticsError` 래핑 유지.
- 빈 스냅샷 디렉터리(또는 매칭 Parquet 0개) → `AnalyticsError` 에 친절한 메시지
  ("`ev-mcp-sync` 후 `ev-mcp-snapshot` 을 한 번 실행하세요").

### `src/ev_mcp/settings.py` (수정)

- `snapshot_dir: Path` 추가 (기본 `data/snapshots/`). 로컬 소스의 진입점.
- 기존 `snapshot_path`(단일 파일) 는 로컬 모드에서 더 이상 쓰지 않음 — 제거 또는
  R2 외 용도 없음 확인 후 정리. (R2 모드는 `r2_bucket` 사용, 영향 없음.)

### `src/ev_mcp/sync.py` (수정)

- `--snapshot/--no-snapshot` 플래그 (기본 on). sync 전체 패스 성공 완료 후
  `snapshot.write_snapshot()` 호출. 부분 동기화 상태로는 안 찍음.

### `src/ev_mcp/tools/analytics_snapshot_diff.py` (신규)

두 스냅샷 날짜 사이 변화 집계.

- 입력 (keyword-only): `from_date: str | None = None`, `to_date: str | None = None`.
  None 이면 from=직전 관측, to=최신 관측.
- 출력: `SnapshotDiff` 단일 모델 — `from_date`·`to_date`·`from_synced_at`·
  `to_synced_at`·`appeared`·`disappeared`·`stat_changed`·`net_change`. 스칼라
  집계만 (508k 행 나열 금지 — 토큰 예산).
- SQL: `v_all` 을 from/to 로 필터해 충전기 고유키(`stat_id` + `chger_id`)로 full
  outer join.
- 엣지: 스냅샷 < 2개 → `ValueError`. 잘못된 날짜 문자열 → `ValueError`.
- `@mcp.tool(annotations={"readOnlyHint": True})`.

### `src/ev_mcp/tools/analytics_inventory_trend.py` (신규)

관측일별 인벤토리 곡선.

- 입력 (keyword-only): `limit: int = 30` (최근 관측 수, 최대 90).
- 출력: `list[InventoryTrendRow]` — `snapshot_date`·`synced_at`·`total_chargers`·
  `dc_count`·`available_count`·`distinct_operators`·`delta_total`(직전 관측 대비,
  SQL LAG 윈도우, 첫 행은 None).
- SQL: `v_all` GROUP BY `snapshot_date`, ORDER BY `snapshot_date`.
- 엣지: 단일 스냅샷 → 1행 `delta_total=None`. 0개 → `AnalyticsError`(레이어에서).
- DC 충전기 정의는 `regional_density` 의 `DC_CODES` 와 동일 — 공유 상수로 추출.

### `src/ev_mcp/domain.py` (수정)

- `SnapshotDiff` — 위 스칼라 필드.
- `InventoryTrendRow` — 위 필드.

### `src/ev_mcp/tools/analytics_operator_health.py` · `analytics_regional_density.py` (수정)

- `_QUERY_TEMPLATE` 의 `FROM {source}` → `FROM v_latest`. 그 외 무변경 — 최신
  스냅샷 의미가 view 로 보존된다.

### `src/ev_mcp/server.py` (수정)

- `snapshot_diff`·`inventory_trend` 툴 2개 등록.

### `pyproject.toml` · `.gitignore` (수정)

- `[project.scripts]` 에 `ev-mcp-snapshot = "ev_mcp.snapshot:main"` (의존성 추가
  아님 — 스크립트 엔트리만).
- `.gitignore` 에 `data/snapshots/`.

## 데이터 흐름

1. `ev-mcp-sync` → `data/chargers.db` 갱신 (기존 동작).
2. `ev-mcp-snapshot` (또는 `ev-mcp-sync --snapshot`) → store 의 `synced_at` 확인.
   마지막 스냅샷과 동일하면 스킵, 아니면 `data/snapshots/chargers_<date>.parquet` 기록.
3. MCP 툴 호출 → `AnalyticsClient` 가 in-memory conn 에 `v_all`·`v_latest` view 생성.
4. `analyze_operator_health`·`regional_density` → `v_latest` 조회 (최신 스냅샷).
5. `snapshot_diff`·`inventory_trend` → `v_all` 조회 (전체 관측열).

## 에러 처리

- 외부 호출 없음 — data.go.kr API 호출 경로 없음.
- DuckDB 예외 → `AnalyticsError` 래핑 + `_redact` (기존 패턴 유지).
- 빈 스냅샷 디렉터리 → `AnalyticsError` 에 복구 방법 안내.
- 잘못된 툴 입력(날짜 형식, limit 범위, 스냅샷 부족) → `ValueError` 즉시 raise.
- 시크릿: R2 자격증명은 view 생성 시점 한 곳에서만 사용. caller SQL 에 소스 문자열
  없음 — 누출 경로 소멸.

## 테스트 전략

API 호출이 없으므로 respx 불필요. 테스트는 tmp 디렉터리에 합성 Parquet/SQLite 생성.

- `tests/test_snapshot.py` — SQLite seed → 스냅샷 export 가 올바른 컬럼
  (`snapshot_date`·`synced_at`·`row_count`) 으로 Parquet 생성 / `synced_at` 중복
  스킵 / `--force` 강제 기록.
- `tests/test_analytics.py` (확장) — view 레이어: `v_latest`·`v_all` 정확성 /
  빈 디렉터리 → `AnalyticsError`.
- `tests/test_analytics_snapshot_diff.py` — happy(나타남·사라짐·`stat` 변경 탐지) /
  기본 날짜 = 최근 2개 관측 / 스냅샷 < 2개 → `ValueError`.
- `tests/test_analytics_inventory_trend.py` — happy 다중 스냅샷 + delta 계산 /
  단일 스냅샷(delta None) / 빈 디렉터리 → `AnalyticsError`.
- 기존 `analyze_operator_health`·`regional_density` 테스트 — view 레이어 위에서
  무회귀 확인.
- `/verify` (pytest + ruff + mypy) 그린. 현 123건 → ~140건.

## Forward dependency

R2 모드 진입(Stage 10.1, Workers R2 export) 시, R2 에 export 되는 Parquet 도
`snapshot_date`·`synced_at`·`row_count` 컬럼을 동일하게 임베드해야 view 레이어가
local/R2 양쪽에서 일관 동작한다. Phase 11 범위 밖 — Workers 측 export 구현 시
이 컬럼 규약을 반드시 따를 것.

## 작업 순서 (구현 계획용 개요)

1. `snapshot.py` + `ev-mcp-snapshot` 엔트리 + `test_snapshot.py`.
2. `settings.py` 에 `snapshot_dir`.
3. `analytics.py` view 레이어 전환 + `test_analytics.py` 확장.
4. 기존 툴 2개 `{source}` → `v_latest` + 회귀 테스트 확인.
5. `domain.py` 모델 2개.
6. `snapshot_diff` 툴 + 테스트.
7. `inventory_trend` 툴 + 테스트.
8. `server.py` 툴 등록.
9. `sync.py` `--snapshot` 플래그.
10. `.gitignore` · `pyproject.toml` 정리.
11. `/verify` 그린 → `/phase-review 11` → fix → `docs/PHASE11.md`.
