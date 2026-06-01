# Phase 11 보고 — DuckDB 시계열 분석 기반

**기간:** 2026-05-22 ~ 2026-06-01 (요청·설계·구현·리뷰 일괄)
**범위:** Phase 10 의 단일 스냅샷 한계 해소. 날짜별 Parquet 스냅샷 축적 메커니즘 (`ev-mcp-snapshot`), `AnalyticsClient` view 레이어(`v_all`/`v_latest`), 첫 시계열 MCP 툴 2개 (`snapshot_diff`, `inventory_trend`). R2 export(Stage 10.1) 미진행 — 로컬 우선, 동일 인터페이스로 R2 슬롯인 가능하게 설계.
**검증:** pytest 135건 / ruff clean / mypy strict (26 source files) / `ev-mcp-snapshot --help` 스모크. 5단 코드 리뷰 + 1단 최종 브랜치 리뷰. 보안 회귀 0건.

## 요약 (3줄)

스냅샷을 "일별 덤프"가 아니라 **"sync 관측"**으로 모델링 — `synced_at` 컬럼을 Parquet 에 임베드해 직전 스냅샷과 동일하면 기록 스킵, 중복 파일 0. `{source}` 문자열 placeholder 를 **named view 레이어**(`v_all`/`v_latest`)로 교체 — caller SQL 에 소스 문자열이 사라져 R2 자격증명 누출 경로가 구조적으로 소멸. 첫 시계열 툴 2개(`snapshot_diff` 헤드라인·`inventory_trend` 경량 동반)가 다중 스냅샷 파이프라인을 end-to-end 증명, Phase 12 운영자/지역 추세 툴 진입 준비 완료.

## 핵심 결정 (4가지)

- **스냅샷 = "sync 관측"**. SQLite store 는 upsert 라 마지막 sync 시점만 담음. 매일 스냅샷을 찍어도 sync 가 주 1회면 7개 동일 파일이 됨 — 이를 막기 위해 `synced_at`(`store.last_synced_at()`)을 Parquet 컬럼으로 임베드하고 `ev-mcp-snapshot` 이 직전 스냅샷과 같으면 스킵. `--force` 로 강제. 시계열은 **불규칙 관측열**로 모델링, 추세 툴이 날짜 간격 들쭉날쭉해도 정상 동작.

- **데이터 정직성 surface**. PHASE10 의 가치(요일 분석 의도적 생략 — 데이터 정직성 우선) 그대로. 추세 결과에 각 관측의 `synced_at` 을 함께 노출해, "N일 추세"가 실은 동일 데이터 N벌인 상황을 숨기지 않음. `InventoryTrendRow.synced_at` / `SnapshotDiff.from_synced_at`·`to_synced_at` 필드.

- **스냅샷 ↔ sync 분리**. `ev-mcp-snapshot` 독립 콘솔이 **주 메커니즘**. `ev-mcp-sync --snapshot`(기본 on) 은 sync 전체 패스 성공 완료 후 같은 로직을 호출하는 편의 기능. 스냅샷 cadence 를 sync cadence 에 종속시키지 않음. `--no-snapshot` 으로 분리 가능.

- **`{source}` placeholder → named view**. `_ensure_connected()` 가 연결 시 in-memory conn 에 `v_all`(전체 glob)·`v_latest`(최신 snapshot_date 만) view 두 개를 생성. 툴은 평범한 SQL `FROM v_latest`/`FROM v_all`. 호출부에 소스 문자열이 아예 없음 → R2 자격증명이 caller SQL 로 샐 경로 자체 소멸. 영속 `.duckdb` 파일 안 만듦 — view 매 연결 재생성(무비용). 일별 집계 롤업(B안)은 후속 Stage (스냅샷 ~60일 후) 로 유지.

## 추가/변경된 모듈

### 신규 (`src/ev_mcp/`)
| 파일 | 역할 | 라인 |
|---|---|---|
| `snapshot.py` | `write_snapshot()` + `ev-mcp-snapshot` CLI. DuckDB sqlite-ATTACH(READ_ONLY)→ COPY, `synced_at` 중복 스킵 + `--force` | 117 |
| `tools/_analytics_shared.py` | 분석 툴 공유 상수 (`DC_CODES`) — `regional_density`·`inventory_trend` 양쪽에서 import | 7 |
| `tools/analytics_snapshot_diff.py` | `snapshot_diff` — 두 스냅샷 사이 충전기 변화. FULL OUTER JOIN on (stat_id, chger_id), `del_yn='N'` 필터, 자동 from/to=직전 2개 관측 | 103 |
| `tools/analytics_inventory_trend.py` | `inventory_trend` — 관측일별 인벤토리 곡선. `v_all` GROUP BY snapshot_date, Python LAG 로 delta 계산 | 105 |

### 신규 (`tests/`)
| 파일 | 테스트 수 | 무엇을 검증 |
|---|---|---|
| `test_snapshot.py` | 4 | Parquet 컬럼 임베드 / `synced_at` 중복 스킵 / `--force` 강제 / 미sync store RuntimeError |
| `test_analytics_snapshot_diff.py` | 4 | 자동 날짜 → 최근 2개 관측 / 명시 날짜 + synced_at 양쪽 확인 / 알 수 없는 날짜 ValueError / 스냅샷 부족 ValueError |
| `test_analytics_inventory_trend.py` | 4 | 관측일별 1행 + delta 계산 / 단일 스냅샷 delta None / 빈 디렉터리 AnalyticsError / 잘못된 limit ValueError |

### 변경
| 파일 | 변경 |
|---|---|
| `settings.py` | `snapshot_dir: Path = data/snapshots` 추가. `snapshot_path` DEPRECATED 명시(호환 위해 필드만 남김). `snapshot_source` 설명을 `snapshot_dir` 기준으로 갱신 |
| `analytics.py` | `_source_expr` 제거. `_create_views(conn)` 신설 — local/R2 소스에 따라 `v_all`·`v_latest` view 생성. `query()` 가 `{source}` 검증 없이 평범한 SQL 실행. `_ensure_connected` 가 view 생성 실패 시 conn 닫음(누수 방지). R2 Parquet 스키마 컨트랙트 NOTE 주석 추가 |
| `domain.py` | `SnapshotDiff` (8 필드, 스칼라 집계) / `InventoryTrendRow` (7 필드, delta_total `int \| None`) 신설 |
| `tools/analytics_operator_health.py` | `FROM {source}` → `FROM v_latest` (1줄) |
| `tools/analytics_regional_density.py` | `FROM {source}` → `FROM v_latest`, 로컬 `DC_CODES` 삭제 → `_analytics_shared` import |
| `sync.py` | `sync(snapshot=True)` 인자 + `--no-snapshot` 플래그 + 전체 패스 성공 후 `write_snapshot(settings.snapshot_dir, ...)` 호출 (split-brain 방지: `settings.snapshot_dir` 사용) |
| `server.py` | `snapshot_diff`·`inventory_trend` MCP 툴 2개 등록 (`readOnlyHint=True`) |
| `pyproject.toml` | `ev-mcp-snapshot = "ev_mcp.snapshot:main"` 콘솔 엔트리 (의존성 추가 아님) |
| `.gitignore` | `data/snapshots/` 추가 |
| `tests/conftest.py` | `analytics_snapshot` 단일 Parquet → `analytics_snapshot_dir` 2개 dated Parquet 디렉터리 (older ME=180, latest ME=200). 신규 `ctx_single_snapshot`·`ctx_empty_snapshot` 픽스처 |
| `tests/test_analytics.py` | view 레이어 위로 전체 재작성 (7 tests). `v_latest` 최신 스냅샷 정확성 회귀 가드, `v_all` 다중 관측 확인, R2/source/redact 보존 |
| `tests/test_server.py` | tool 카운트 어설션 9개 → 11개 (`snapshot_diff`·`inventory_trend` 추가) |

### 보존 (Phase 1~10 영향 없음)
- 기존 9개 MCP 툴 — 시그니처·동작 변경 없음
- `src/ev_mcp/store.py` (SQLite 영속 store) — 그대로 운영
- `workers/` — Stage 10.1 진입 전까지 영향 없음
- web/ 대시보드 — Phase 10 그대로 (web 은 단일 스냅샷 Parquet 기반, 시계열 페이지 추가는 Phase 12 이후)

## 아키텍처

```text
ev-mcp-sync  ──(data.go.kr)──▶  data/chargers.db  (SQLite, upsert)
                                      │
                  ev-mcp-snapshot     │  synced_at 중복 검사 → 스킵 가능
                                      ▼
                      data/snapshots/chargers_YYYY-MM-DD.parquet
                      (snapshot_date · synced_at · row_count 컬럼 임베드)
                                      │
                  AnalyticsClient._ensure_connected()
                      in-memory DuckDB conn 에 view 생성
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

## 검증

### 자동
- pytest 135건 — Phase 10 102건 + Task 1~9 신규 33건(`+33`)
- ruff clean, mypy strict (26 source files) clean
- 5단 per-task 코드 리뷰 + 1단 최종 브랜치 리뷰 — CRITICAL 0건, IMPORTANT 모두 해소

### 스모크
- `ev-mcp-snapshot --help` → argparse 정상
- `python -c "from ev_mcp.server import build_server; build_server()"` → 11개 툴 등록 확인 (test_server.py 회귀)

### 보안 회귀
- R2 자격증명: view 레이어 전환으로 caller SQL 에 소스 문자열 자체가 없어짐 → 누출 경로 구조적 소멸
- `AnalyticsError` + `_redact` 패턴 유지
- snapshot.py 의 f-string 보간: 운영자 통제 값(`db_path`/날짜/synced_at_iso/row_count)만 — datetime.isoformat 출력은 single quote 부재로 안전

## 발견된 인사이트 / 회고

- **리뷰가 코드 품질을 끌어올렸다.** Task 1~6 각 단계의 코드 리뷰가 IMPORTANT 이슈 9건을 잡음(테스트 패턴 정렬, 누락 분기 커버, fixture 스키마 정합, 커넥션 누수, 회귀 가드 축소, docstring 모호). subagent-driven 의 2단 리뷰가 비용 대비 분명한 가치.
- **plan 의 작은 누락.** sync.py 의 `write_snapshot` 호출이 `DEFAULT_SNAPSHOT_DIR` 하드코딩 — settings 와 split-brain 위험. 최종 브랜치 리뷰가 잡음. 플랜에 "settings.snapshot_dir 사용" 명시 안 한 것이 원인. 다음 Phase 의 플랜 작성 시 "설정값 사용처 매핑" 체크포인트 추가.
- **테스트 fixture 가 다음 툴의 위험을 미리 드러냄.** Task 5 의 단일 스냅샷 픽스처가 9 컬럼이라 Task 6 의 `inventory_trend` 가 깨질 위험 → 코드 리뷰가 사전 검출 → 12 컬럼으로 정렬. fixture 일관성은 미래 툴까지 영향.

## 한계 / 다음 단계

- **R2 export (Stage 10.1) 미진행** — 사용자 R2 준비 후 별도 사이클. `analytics.py` 의 R2 분기와 forward dependency 주석은 갖춤. Workers 측 export 구현 시 Parquet 컬럼 규약(`snapshot_date`·`synced_at`·`row_count`)을 반드시 따를 것.
- **시계열 추세 툴이 1·2개뿐** — `snapshot_diff`·`inventory_trend` 가 파이프라인을 증명. 운영자별 가동률 추세, 신규 설치 곡선, 지역별 증가율 등 본격 추세 툴은 Phase 12.
- **롤업 테이블(B안) 미도입** — 영속 DuckDB + 일별 집계 사전 계산. 스냅샷이 ~60일 이상 쌓이면 진입할 후속 Stage. view 레이어가 그 이음새.
- **web 대시보드 시계열 페이지 부재** — Phase 12 와 함께 추가 가능.
- **`Settings.snapshot_path` deprecation** — 현재는 deprecated 명시만. 다음 cleanup pass 에 필드 제거.

## 변경 이력

- 2026-05-22 — 브레인스토밍·spec 작성·plan 작성. v1 → v2 (spec 자체 비판 후 "sync 관측" 모델·named view 로 강화).
- 2026-05-22 ~ 2026-06-01 — Task 1~10 구현 (subagent-driven, per-task 코드 리뷰 + 최종 브랜치 리뷰). 14 commits.
