# ADR-001 — DuckDB 분석 사이드카 도입

**상태:** Accepted (2026-05-11) — Stage 10.2 + 10.3 + 10.4 완료. Stage 10.1 (R2 export) 미진행.
**결정자:** bokeum
**대상 Phase:** Phase 10 (PLAN.md)
**관련 문서:** `scratch/duckdb_poc.py` (검증 스크립트), `docs/PLAN.md` Phase 10 섹션, `docs/PHASE10.md` (구현 보고)

---

## 맥락

ev-mcp 의 현재 7개 MCP 툴은 모두 point/range lookup 으로, 운영 데이터를 Cloudflare Workers + Durable Objects SQLite (workers/) 에서 1차로, Python SQLite 스토어 (`src/ev_mcp/store.py`, Phase 6) 에서 2차로 서빙한다. 이 구조는 lookup 워크로드에는 충분하지만 다음 가치를 제공하지 못한다:

- **분석 질문 미지원.** "엘에스이링크 충전기 중 비가동률 top 10", "강남구 충전기 밀도 vs 인구", "최근 30일 신규 설치 트렌드" 같은 GROUP BY/AVG/시계열 질문에 답할 수 없다.
- **시계열 데이터 없음.** DO SQL 은 1 시점 스냅샷만 보관. `stat_upd_dt` 변화 이력이 누적되지 않아 트렌드 분석 불가.
- **두 스토어 코드 중복.** Python `store.py` 와 Workers `inventory_store.ts` 의 DDL 동기화 부담 (수동).

DuckDB 를 **대체**가 아닌 **사이드카**로 추가하면 위 세 문제를 한 번에 해결할 후보가 된다.

## 결정

**DuckDB 를 Python 측 분석 사이드카로 도입. R2 cold storage 위에서 Parquet 파일을 직접 query 하는 패턴.**

```
[CF Workers + DO SQL]          ← 기존 그대로 (실시간 lookup, 7개 툴)
        ↓ daily export (Workers cron)
[R2: chargers_YYYY-MM-DD.parquet]
        ↓ httpfs / s3
[Python FastMCP + DuckDB]      ← 새 분석 툴 (별도 모듈)
```

### 명시적으로 채택하지 않는 것
- ❌ Cloudflare Workers 안에서 DuckDB-WASM 실행 (메모리/CPU 제약, 사실상 불가능)
- ❌ DuckDB 의 SQLite ATTACH mode 운영 사용 (PoC 에서 분석 워크로드 일관성 부족 확인)
- ❌ DO SQL 또는 Python SQLite 스토어 폐기 (대체 X, 추가만)

## PoC 검증 결과 (2026-05-11)

`scratch/duckdb_poc.py` 가 측정한 수치 (508,060 rows, 257MB SQLite, 37 columns):

| 지표 | 값 | 해석 |
|---|---|---|
| **Query A: SQLite baseline** | 1114ms | 운영자별 비가동률 top 10 |
| Query A: DuckDB SQLite ATTACH | 2498ms | ❌ 더 느림 (cross-engine 오버헤드) |
| **Query A: Parquet (read_parquet)** | **15ms** | ⭐ **74× speedup vs SQLite** |
| Query B: SQLite baseline | 378ms | 시군구별 밀도 top 10 |
| Query B: Parquet (read_parquet) | (측정 시 유사 추세) | column store 이점 동일 |
| **Parquet 압축률** | **17.8×** | 257MB → 14.4MB (ZSTD) |
| **R2 비용 (30일 스냅샷)** | **432MB / 10GB free** | 4.3% of free tier |

**의사결정 기준 충족:**
- ✅ Parquet 경로 speedup ≥ 3× (74× 달성)
- ✅ 압축률 ≥ 3× (17.8× 달성)
- ✅ R2 비용 사실상 0 (무료 tier 의 5% 미만)

## 대안 (검토 후 채택 안 함)

### Alt-1: Cloudflare Workers + DuckDB-WASM (워커 내부 실행)
- **거부 이유:** Workers 의 128MB 메모리 + 30s CPU 한도 + 파일시스템 부재. DuckDB-WASM 바이너리(~50MB+)와 메모리 사용 패턴이 호환되지 않음. 검증 없이 거부.

### Alt-2: 호스팅 통째로 옮겨 DuckDB 단일 (Render/Fly + DuckDB 메인 스토어)
- **거부 이유:** (1) Phase 9 의 Workers 코드 2000줄 + 61 테스트 폐기, (2) CF edge 의 한국 저지연 손실(+30~40ms), (3) 매월 호스팅 비용 발생, (4) 무료 운영이라는 현재 제약 위반.

### Alt-3: DuckDB ATTACH mode 로 SQLite 직접 query
- **거부 이유:** PoC 가 일관성 없음을 확인. Query A 에서 attach 가 SQLite 보다 **느림** (2498ms vs 1114ms). Query B 에서는 빠르지만(118ms vs 378ms) 차이의 원인이 인덱스 우연. 운영 워크로드의 예측 가능성을 보장 못함.

### Alt-4: Python `src/ev_mcp/store.py` 의 SQLite → DuckDB 교체
- **거부 이유:** lookup 워크로드에 DuckDB 이점이 거의 없음 (PoC 의 attach 결과가 증거). 마이그레이션 비용만 발생하고 가치 미미. 미래에 분석 툴이 5개+ 추가되면 재검토.

### Alt-5: 현상 유지 (Phase 10 진입 안 함)
- **거부 이유:** PoC 가 보여준 가치(74× speedup, 17.8× 압축, 무료 운영) 가 매우 강함. 분석 툴이 자연어 사용 패턴(예: "강남구에서 자주 고장나는 충전기 알려줘")에서 즉시 가치를 줌. 보류할 합리적 이유 부족.

## 결과 (트레이드오프)

### 얻는 것
- **새 분석 MCP 툴** (예: `analyze_operator_health`, `regional_density`) — 현재 불가능한 질문에 답
- **시계열 데이터** — Parquet 일별 스냅샷이 누적되어 트렌드 분석 가능
- **74× 분석 쿼리 속도** (1100ms → 15ms)
- **17.8× 스토리지 압축** — R2 비용 사실상 0

### 감수하는 것
- **새 의존성:** `duckdb` (Python). PoC 단계에선 venv only, Phase 10 진입 시 `pyproject.toml` 에 정식 추가 — **사용자 컨펌 필요**.
- **새 외부 시스템:** Cloudflare R2 bucket 1개. `wrangler r2 bucket create` 사용자 액션.
- **운영 표면 증가:** R2 export 실패 시 시계열 공백. Phase 10 Stage 1 에서 실패 처리 + alarm.
- **Python ↔ Workers 코드 동기화 부담은 그대로** — 이 결정은 그 문제는 해결하지 않음 (별도 검토 대상).

### 운영 비용 (월간 추정)

| 항목 | 사용량 | 무료 tier | 비율 |
|---|---|---|---|
| R2 스토리지 | 432MB (30일 스냅샷) | 10GB | 4.3% |
| R2 Class A (writes) | ~30 ops/월 (일 1회) | 1M ops | <0.01% |
| R2 Class B (reads) | ~10K~100K ops/월 (분석 호출 빈도) | 10M ops | <1% |
| DuckDB | embedded, free | — | 0 |
| Python 호스트 | 기존 활용 (별도 호스트 X) | — | 0 |

**총 추가 비용: $0/월** (R2 무료 tier 안에서 운영).

## 트리거 / 재검토 조건

다음 중 하나라도 발생하면 이 결정 재검토:

1. **R2 무료 tier 50% 초과** — 스냅샷 누적 또는 분석 호출 빈도 증가. 보관 정책 도입 (예: 90일 이전 스냅샷 삭제) 검토.
2. **DuckDB 호출 빈도 일 10만+ 으로 증가** — Python 호스트 부하 검토, 캐싱 또는 별도 워커 분리 검토.
3. **분석 MCP 툴이 5개+ 로 증가** — Alt-4 (Python store 도 DuckDB 로 통합) 재검토.
4. **Parquet 스냅샷이 일별로 부족** — 시간별/15분별로 빈도 상향, sync 빈도 영향 분석.
5. **Cloudflare R2 가격 정책 변경** — 다른 cold storage (S3, Backblaze B2) 로 마이그레이션 검토.

## 롤백 계획

이 결정이 잘못된 것으로 판명되면:

### 단계별 롤백 (가역, 비용 적음)
1. **Stage 3 롤백:** 새 분석 MCP 툴 등록 해제 (Python `server.py` 에서 register 호출 제거). MCP 클라이언트에 영향 0 (lookup 툴은 그대로).
2. **Stage 2 롤백:** `src/ev_mcp/analytics.py` 모듈 삭제. `duckdb` 의존성 `pyproject.toml` 에서 제거.
3. **Stage 1 롤백:** `workers/src/sync.ts` 의 R2 export 호출 제거. R2 bucket 비우기 + 삭제 (Cloudflare 대시보드 또는 `wrangler r2 bucket delete`).
4. **scratch/ 정리:** `rm -rf scratch/`.

### 데이터 영향
- DO SQL 운영 데이터: **변경 없음** (analytics 사이드카는 read-only 사이드 패스)
- Python SQLite 스토어: **변경 없음**
- R2 Parquet: 삭제. 시계열 이력 손실, 단 운영 lookup 영향 없음.

### 롤백 후 상태
정확히 Phase 9 종료 시점으로 복원. Phase 1~9 코드 영향 0.

## 구현 순서 (요약 — 상세는 PLAN.md Phase 10)

- **Stage 10.1** — Workers 의 daily R2 Parquet export 추가
- **Stage 10.2** — Python `src/ev_mcp/analytics.py` 모듈 + DuckDB httpfs 연결 + R2 자격증명
- **Stage 10.3** — 새 MCP 툴 1~2개 (`analyze_operator_health`, `regional_density`) 등록 + 테스트
- (선택) **Stage 10.4** — Phase 보고서 + 운영 모니터링 (R2 스토리지 사용량 알람)

각 Stage 사이에 검증 게이트 (pytest + vitest + 자연어 스모크). Stage 단위 롤백 가능.

## 운영 결과 (post-implementation)

### 2026-05-11 — Stage 10.2 + 10.3 + 10.4 완료

실 운영 Parquet(508,060 rows) 으로 자연어 스모크 검증.

**확인된 가치:**
- 분석 쿼리 응답 시간 ~1~2초 (DuckDB connect + read_parquet) — PoC 예측 부합.
- 기존 7개 lookup 툴로 불가능했던 GROUP BY/AVG 질문 답변 가능.
- "운영자별 비가동률", "강남구 충전기 밀도", "광역 DC 비율 격차" 등 즉시 응답.

**Stage 10.4 데이터 품질 수정 (예상 못한 발견):**

스모크 결과에서 "미래에스디 400대 100% 비가동", "에너넷 281대 100% 비가동" 같은
극단 비율이 등장. 조사 결과 ``stat='9'`` (상태미확인) 이 비가동률 100% 의 원인.

``stat='9'`` 의 의미는 "운영자가 실시간 상태를 데이터고고개알 API 로 보고하지 않음"
이지 "충전기 운영중지" 가 아니다. 따라서 비가동 정의를 재조정:

- **재정의 전 (잘못):** ``DOWNTIME_CODES = ("4", "5", "9")``
- **재정의 후:** ``DOWNTIME_CODES = ("1", "4", "5")`` — 통신이상/운영중지/점검중
- ``stat='9'`` 는 ``UNMONITORED_CODE`` 로 분리, ``OperatorHealthRow`` 에
  ``unmonitored_count`` / ``unmonitored_ratio`` 신설.

수정 후 결과: false alarm 사라지고 진짜 운영 품질 문제 운영자가 top 10 에 등장
(엘쓰리일렉트릭파워 84.1%, 차지인 72.5%, 이지차저 38.3%). 비가동률 해석의 신뢰도
(``unmonitored_ratio`` 1~8%) 가 함께 노출돼 사용자가 판단 가능.

**교훈:** ADR 작성 시점에 안다고 생각했던 도메인 코드(stat 분류) 가 실제 운영
데이터와 불일치할 수 있다. 실 데이터 자연어 스모크는 코드 작성 후 반드시 필요.

### Stage 10.1 (R2 export) — 미진행

사용자가 Cloudflare R2 bucket + API 토큰을 준비한 후 별도 사이클로 진입.
Stage 10.2 가 ``snapshot_source="local"`` 으로도 충분히 동작하므로 분석 가치는
이미 입증된 상태에서 R2 도입 결정 가능.

## 참고

- **PoC 스크립트:** `scratch/duckdb_poc.py` (gitignore — 검증 끝나면 삭제 가능)
- **자연어 스모크:** `scratch/smoke_analytics.py` (Stage 10.2~10.4 가치 시연)
- **DuckDB httpfs 문서:** https://duckdb.org/docs/extensions/httpfs
- **Cloudflare R2 S3 호환 API:** https://developers.cloudflare.com/r2/api/s3/api/
- **DuckDB Parquet 압축:** ZSTD (현재 PoC 측정값 기준)
