# web/ — ev-mcp 분석 대시보드

DuckDB-WASM + Chart.js + Leaflet 으로 만든 **순수 정적** 분석 도구. 한국환경공단 EV 충전소 Parquet 스냅샷을 브라우저가 직접 읽고 분석. 서버 부담 0, 빌드 step 0, npm 의존성 0.

## 페이지 구조 (8 페이지)

```
web/
├── index.html        — 메인 대시보드 (전체 데이터, 508k rows)
└── highway/          — 고속도로 휴게소 전용 (kind_detail='C001', 1979대)
    ├── index.html    — 차트 (KPI 6, 인사이트 5, 차트 4)
    ├── map.html      — Leaflet 지도 (622곳 마커, 노선 필터)
    ├── operators.html — 운영자 deep dive (ranking 표 + 히트맵 + 진입 연도 + 산점도)
    ├── activity.html — 활성도 분석 (시간대 + 회전율 + 노선별 + 휴면)
    ├── route.html    — 노선 deep dive (노선 선택 시 휴게소/출력/운영자/거리)
    ├── station.html  — 휴게소 상세 (drill-down, 검색 + 충전기 list + mini 지도)
    └── compare.html  — 비교 분석 (운영자/노선 2~4 entity, radar + 자동 인사이트)
```

각 페이지 헤더에 다른 6개 페이지로 자유 네비게이션. URL query string 으로 deep link 공유 (`?hw=`, `?id=`, `?type=&entities=`).

## 메인 대시보드 (`/web/`)

**전체 508,060대 충전기** 데이터. 일반 시내·아파트·휴게소 모두 포함.

- **KPI 8개:** 총 충전기 / 운영자 수 / 시군구 수 / 즉시 사용 가능 / DC 비율 / 24h 운영 / 무료 주차 / 평균 출력
- **자동 인사이트 5개**
- **차트 7개:** 운영자 비가동률 top 10 · 시군구 밀도 · 광역 DC 비율 · 충전기 타입 분포 · 출력 분포 · 연도별 신규 설치 · 충전소 종류

## 고속도로 deep dive (`/web/highway/`)

`kind_detail = 'C001'` 필터 후 더 깊이 분석. 1,979대 = 전체의 0.4% 지만 완전히 다른 인프라 (DC 99.2%, 평균 196.8 kW, 일반의 12×).

### 1. **차트** (`/highway/`) — 일반 개요
KPI 6 + 인사이트 4 + 차트 4 (운영자별 / 시도별 / 출력 분포 / 휴게소 top 12).

### 2. **지도** (`/highway/map.html`) — Leaflet 시각화
- 622곳 휴게소 CircleMarker (다크 모드 OSM 타일)
- 색상 = 평균 출력, 크기 = 충전기 수
- 노선 필터 드롭다운 (경부/서해안/영동 등)
- 클릭 popup 에 "상세 보기 →" 링크 (drill-down 진입)

### 3. **운영자** (`/highway/operators.html`) — 시장 구조
- 12 운영자 종합 ranking 표 (충전기/휴게소/시도/평균kW/비가동/미연동/점유율)
- 운영자 × 노선 히트맵 (top 8 × top 8, CSS Grid)
- 진입 연도 line chart (top 6 운영자 시계열)
- 규모 vs 출력 산점도 (log scale)

### 4. **활성도** (`/highway/activity.html`) — 실 사용 패턴
- KPI 6 (24h/7일/30일 내 사용 비율, 60일+ 휴면, 현재 사용중)
- 시간대별 충전 분포 (24-bar) — 점심 피크
- 충전기 회전율 (출력대별 평균 분 — AC 30.8 vs 350+kW 20.3)
- 노선별 평균 활성도 (작을수록 활성)
- 휴면 기간 분포 (60~90 / 91~180 / 181~365 / 365+ 일) + 노선별 휴면

### 5. **노선** (`/highway/route.html`) — 단일 노선 deep dive
- 드롭다운 노선 선택 (URL `?hw=`)
- KPI 6 (휴게소/충전기/평균kW/DC비율/평균간격km/운영자)
- 인사이트 5 (전체 대비 우월/열세, 가장 먼 무충전 구간 등)
- 휴게소 list (동적 높이 + 6 정렬 옵션 + 클릭 시 drill-down)
- 출력 분포 비교 (노선 vs 전체), 운영자 점유 donut, haversine 거리 분포

### 6. **휴게소 상세** (`/highway/station.html`) — drill-down
- 622곳 검색 input (자동완성)
- 기본 정보 카드 (운영자/고객센터/운영시간/주차/연도/노선)
- KPI 6 (충전기/평균kW/DC비율/사용가능/사용중/최근활동)
- 충전기 list 표 (정렬 4종) + 상태/출력 분포 차트
- mini 지도 (인근 휴게소 popup 으로 chain 탐색)

### 7. **비교** (`/highway/compare.html`) — 인사이트 도구 ⭐
- Entity picker (chip-based, 2~4 선택)
- Type 토글 (운영자 ↔ 노선)
- 추천 preset (top 4 / 신규 / 기존 강자)
- **자동 인사이트 5** (격차 큰 순 + 모순 패턴)
- **Radar chart** (6축 정규화, 면적 = 종합 강도)
- KPI 표 (최고 녹색 / 최저 빨강 자동 강조)
- Drill-down 3 (출력 분포 / 노선·운영자 점유 / KPI 정규화)

## 기술 스택

| 컴포넌트 | 버전 | 출처 |
|---|---|---|
| DuckDB-WASM | 1.28.0 | jsDelivr CDN |
| Chart.js | 4.4.0 | jsDelivr CDN |
| Leaflet | 1.9.4 | jsDelivr CDN |
| 타일 | CARTO Dark Matter | OpenStreetMap 기반 |
| 빌드 | 없음 | ES modules + `<script type="module">` |

**의존성 zero.** package.json 없음, npm install 없음, 빌드 step 없음.

## 로컬 실행

**프로젝트 루트에서** 정적 서버 실행 (절대 경로 `/scratch/...`, `/src/ev_mcp/codes/...` 해결 위해):

```bash
cd /home/bokeum/ai/ev_mcp
python -m http.server 8000
# 브라우저: http://localhost:8000/web/
```

### 첫 실행 시 필요한 파일

```
/home/bokeum/ai/ev_mcp/
├── scratch/
│   └── chargers_snapshot.parquet     ← 14.4MB (PoC 가 생성)
├── src/ev_mcp/codes/
│   ├── sido.json
│   ├── sigungu.json
│   ├── busi_id.json
│   ├── charger_type.json
│   ├── kind.json
│   ├── kind_detail.json
│   └── stat.json
└── web/  (이 디렉토리)
```

Parquet 없으면:

```bash
source .venv/bin/activate
ev-mcp-sync                            # data.go.kr → data/chargers.db
python scratch/duckdb_poc.py           # SQLite → Parquet (1.5초)
```

## 데이터 흐름

```
data.go.kr API
   │ (ev-mcp-sync, 일별)
   ▼
data/chargers.db (SQLite, Phase 6, 257MB)
   │ (scratch/duckdb_poc.py)
   ▼
scratch/chargers_snapshot.parquet (14.4MB, ZSTD 압축)
   │ (브라우저 HTTP fetch, ~15MB)
   ▼
DuckDB-WASM (Web Worker, in-memory)
   │ (SQL: GROUP BY / AVG / haversine)
   ▼
Chart.js / Leaflet 렌더링
```

**Stage 10.1 (R2 export) 진입 후**: Parquet URL 만 R2 public URL 로 변경 → 글로벌 CDN 배포 가능.

## 첫 로드 비용 (한 번만, 이후 캐시)

| 자원 | 크기 |
|---|---|
| DuckDB-WASM 번들 | ~15MB |
| Chart.js | ~200KB |
| Leaflet (지도/휴게소 페이지만) | ~150KB |
| Parquet 스냅샷 | ~15MB |
| 코드 JSON × 5~7 | ~80KB |
| **총** | **~30MB** |

이후 브라우저 캐시. 쿼리 자체는 매번 즉시 (1~2초).

## URL Deep Link (공유 가능)

| 페이지 | URL 파라미터 | 예시 |
|---|---|---|
| 노선 | `?hw=경부고속도로` | `route.html?hw=서해안고속도로` |
| 휴게소 | `?id=KP005347` | `station.html?id=ME000010` |
| 비교 | `?type=&entities=` | `compare.html?type=operator&entities=ME,SG,BE,ST` |

## 안전성

- **innerHTML 사용 0** — 모든 동적 DOM 은 `createElement` + `textContent` + `append`. 보안 후크가 잡았던 XSS 잠재성 모두 해소.
- **DuckDB SQL 인터폴레이션** — 사용자 입력은 `replace(/'/g, "''")` SQL escape 후 사용.
- **시크릿 노출 0** — 클라이언트는 SERVICE_KEY 안 씀. Parquet 만 read.
- **lat/lng bounds 필터** — 33~39, 124~132 (한반도) 외 row SQL 에서 제외.

## 배포 (선택)

정적 자산이라 어떤 호스팅에도 가능. 단, Parquet 도 같이 호스팅 또는 R2 URL 로 변경.

| 호스팅 | 방법 | 비용 |
|---|---|---|
| Cloudflare Pages | `wrangler pages deploy web/` | 무료 |
| GitHub Pages | `web/` → `gh-pages` 브랜치 | 무료 |
| Vercel | drag-and-drop | 무료 tier |

배포 후 `app.js` 의 `PARQUET_URL` 을 R2 public URL 로 변경 + R2 bucket CORS 설정 필요.

## 한계 / 알려진 이슈

- **첫 로드 ~30MB** — 모바일 셀룰러에서 무거움
- **데이터 신선도** — 일별 스냅샷 (실시간 X). 실시간 상태는 ev-mcp MCP 툴 (`get_charger_status`) 사용
- **요일 분석 부재** — 단일 스냅샷 편향이 커서 의도적 생략
- **시계열 분석 부재** — Stage 10.1 후 R2 일별 스냅샷 누적 시 가능

## 정체성

**"인사이트 제공 도구"** — SQL 능력을 제공하는 게 아니라, 사용자가 entity 만 선택하면 도구가 자동으로 차이/우열/모순을 추출. 대표 페이지 = `compare.html`.

ev-mcp 의 자매 도구: MCP 서버는 **자연어 분석**, web/ 은 **시각적 분석**.
