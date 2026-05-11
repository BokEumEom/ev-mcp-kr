# web/ — ev-mcp 분석 대시보드

DuckDB-WASM + Chart.js 로 만든 정적 HTML 분석 페이지. 한국환경공단 EV 충전소 Parquet 스냅샷을 **브라우저가 직접** 읽어 분석 — 서버 부담 0, 의존성 단 2개 (CDN).

## 무엇이 보이는가

- **KPI 4개:** 총 충전기 / 운영자 수 / 시군구 수 / 즉시 사용 가능 수
- **차트 1:** 운영자별 비가동률 top 10 + 미연동률(stat='9') 동반 노출 (Stage 10.4 의 데이터 정의 그대로)
- **차트 2:** 시군구별 충전기 밀도 top 10 + 운영자 다양성 + DC 비율 (tooltip)
- **차트 3:** 광역시도별 급속(DC) 충전기 비율 — 도시 vs 비도시 격차 시각화

분석 쿼리는 `src/ev_mcp/tools/analytics_*.py` 의 SQL 과 100% 동일. ev-mcp 의 MCP 툴이 답하는 질문을 사람이 클릭해서 볼 수 있는 형태로.

## 로컬 실행

**중요:** 반드시 **프로젝트 루트** (`/home/bokeum/ai/ev_mcp`) 에서 정적 서버를 실행해야 합니다. `web/` 안에서 실행하면 `/scratch/...` 와 `/src/ev_mcp/codes/...` 절대 경로를 찾지 못합니다.

```bash
cd /home/bokeum/ai/ev_mcp
python -m http.server 8000
# 브라우저에서 열기:
# http://localhost:8000/web/
```

또는 Node 의 `npx serve` / Bun 의 `bun serve` 등 어떤 정적 서버든 OK.

### 첫 실행 시 필요한 것

```
/home/bokeum/ai/ev_mcp/
├── scratch/
│   └── chargers_snapshot.parquet     ← scratch/duckdb_poc.py 가 생성한 14.4MB Parquet
├── src/ev_mcp/codes/
│   ├── sido.json
│   ├── sigungu.json
│   └── busi_id.json
└── web/
    ├── index.html
    ├── styles.css
    ├── app.js
    └── README.md
```

Parquet 이 없으면:

```bash
source .venv/bin/activate
python scratch/duckdb_poc.py    # scratch/chargers_snapshot.parquet 을 생성
```

## 기술 스택

| 컴포넌트 | 버전 | 출처 |
|---|---|---|
| DuckDB-WASM | 1.28.0 | `cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm` |
| Chart.js | 4.4.0 | `cdn.jsdelivr.net/npm/chart.js` |
| 빌드 | 없음 | ES modules + `<script type="module">` |

**의존성 zero.** package.json 없음, npm install 없음.

## 작동 원리 (Stage 10.2 의 클라이언트 버전)

```
브라우저 (이 페이지)
   │
   ├─ ES module import: duckdb-wasm  (~15MB WASM, jsDelivr CDN)
   ├─ ES module import: chart.js     (~200KB, CDN)
   │
   ├─ DuckDB-WASM 초기화 (Web Worker)
   │
   ├─ HTTP fetch: /scratch/chargers_snapshot.parquet  (14.4MB, 압축됨)
   │   ↳ DuckDB-WASM 이 직접 읽음 (전체 다운로드 후 in-memory)
   │
   ├─ 쿼리 4건 병렬 실행 (KPI / 운영자 / 시군구 / 광역 DC)
   │   ↳ SQL 은 src/ev_mcp/tools/analytics_*.py 와 동일
   │
   └─ Chart.js 로 렌더
```

**첫 로드 시 ~30MB 다운로드** (DuckDB-WASM 15MB + Parquet 14.4MB + Chart.js 200KB). 이후 브라우저 캐시.

## 데이터 소스 전환 (Stage 10.1 진입 후)

현재는 로컬 Parquet (`/scratch/chargers_snapshot.parquet`) fetch. Workers R2 export (Stage 10.1) 가 들어오면 `app.js` 의 `PARQUET_URL` 만 R2 public URL 로 변경:

```js
// Before (Stage 10.2)
const PARQUET_URL = "/scratch/chargers_snapshot.parquet";

// After (Stage 10.1 + R2 public bucket)
const PARQUET_URL = "https://snapshots.ev-mcp.example.com/chargers-latest.parquet";
```

R2 의 CORS 설정 필요 (브라우저 fetch 가능하도록).

## 배포 (선택)

정적 파일 4개 (index.html, styles.css, app.js, README.md) 만 있으면 어떤 정적 호스팅에도 배포 가능:

| 호스팅 | 방법 | 비용 |
|---|---|---|
| Cloudflare Pages | `wrangler pages deploy web/` | 무료 |
| GitHub Pages | `gh-pages` 브랜치로 web/ push | 무료 |
| Vercel | `vercel --prod web/` | 무료 tier |
| Netlify | drag-and-drop web/ 폴더 | 무료 tier |

배포 시 Parquet 도 같이 호스팅하거나 R2 URL 로 전환.

## 한계 / 알려진 이슈

- **첫 로드 ~30MB.** 모바일 셀룰러에서 무겁다. 향후 옵션: Parquet 을 더 잘게 쪼개 partition (예: 시도별), 필요한 partition 만 fetch.
- **Web Worker SharedArrayBuffer.** DuckDB-WASM 멀티스레드 빌드는 COOP/COEP 헤더 필요. 현재는 단일 스레드 빌드 사용 — 충분히 빠름.
- **데이터 신선도.** Parquet 스냅샷이 일별 (Stage 10.1 진입 후 cron). 실시간 상태는 ev-mcp 의 `get_charger_status` MCP 툴 사용.
- **CORS.** 다른 도메인의 Parquet 을 fetch 하려면 그 도메인이 `Access-Control-Allow-Origin` 헤더 보내야 함. R2 의 경우 bucket CORS 설정 필요.

## 향후 작업

- 시계열 추적 (Stage 10.1 의 일별 스냅샷이 누적되면) — 운영자 가동률 추이, 신규 설치 트렌드 같은 시간축 차트
- 지도 시각화 (Leaflet + lat/lng 클러스터링) — 시군구 밀도를 지도로
- URL query string 필터 (`?operator=ME&zcode=11`) — 공유 가능한 deep link
- 다국어 (현재 한국어 only)
- 데이터 다운로드 버튼 (CSV/JSON)
