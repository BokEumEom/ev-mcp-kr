# DESIGN.md — ev-mcp 웹 대시보드 디자인 시스템

이 문서는 `web/` 분석 대시보드의 **디자인 진실의 원천**입니다. (MCP 서버 본체 `src/ev_mcp/` 는 UI 가 없으므로 이 시스템과 무관.)

UI 변경 시 이 문서에 정의된 토큰·패턴을 따르고, 새 결정이 생기면 **여기를 먼저 갱신**한 뒤 코드를 고칩니다. 이 문서가 없던 시절, 색·대비·범례 값이 CSS 곳곳에 하드코딩돼 드리프트(범례≠마커, info 2색, 라벨 대비 미달)가 발생했습니다. 그 재발을 막는 것이 이 문서의 목적입니다.

분류: **App UI** (데이터 조밀 분석 대시보드). 랜딩페이지 규칙(히어로·브랜드 우선)이 아니라 *차분한 표면 · 조밀하지만 가독 · 최소 크롬* 규칙을 따릅니다.

---

## 1. 디자인 토큰 (`web/styles.css :root` 가 단일 소스)

**라이트/다크 듀얼 테마.** `:root` = 라이트(기본), `:root[data-theme="dark"]` = 다크 오버라이드(같은 토큰을 다크 값으로). `<html data-theme>` 는 각 페이지 `<head>` 인라인 스크립트가 `localStorage('ev-theme') ?? prefers-color-scheme` 로 선설정(FOUC 방지). 헤더의 `.theme-toggle` 버튼이 전환·저장 후 **리로드**(차트는 init 시 토큰을 읽으므로 리로드로 재생성). 핸들러는 `web/theme.js`. 차트·지도·범례가 전부 토큰을 읽으므로 두 테마가 자동으로 따라온다. 아래 표는 라이트 값.

### 색

| 토큰 | 값 | 용도 |
|---|---|---|
| `--bg` | `#f7f8fa` | 페이지 배경 |
| `--bg-card` | `#ffffff` | 카드/패널 |
| `--bg-elevated` | `#f1f3f6` | 표 헤더·서브탭 트랙 |
| `--bg-insight` | `#f5f4ff` | 인사이트 카드 |
| `--border` | `#e8eaee` | 기본 보더 |
| `--border-strong` | `#d7dbe2` | 강조 보더 |
| `--text` | `#18181b` | 본문 |
| `--text-dim` | `#5e6470` | 보조 텍스트 (≈5.6:1, AA) |
| `--text-muted` | `#6b7280` | 라벨/캡션 (≈4.6:1, AA) — **`#9aa1ad`(2.6:1, 미달) 금지** |
| `--accent` | `#5b5bd6` | 브랜드 인디고 (차트 primary 와 동일) |
| `--accent-dim` | `#4f46e5` | hover/active |
| `--accent-bg` | `rgba(91,91,214,.07)` | 활성 탭 배경 |
| `--warn` `--danger` `--info` `--purple` | `#d97706` `#dc2626` `#0891b2` `#7c3aed` | 시맨틱 |

**차트·지도 팔레트** (CSS 변수로만, JS 가 `getComputedStyle` 로 1회 읽음):
`--chart-grid #eceef1`, `--chart-amber #ca8a04`, `--chart-lime #65a30d`, `--chart-rose #e11d48`.
지도 출력 버킷: `--kw-fast #5b5bd6` (200+kW), `--kw-mid #ca8a04` (100~200), `--kw-slow #0891b2` (50~100), `--kw-low #8b95a4` (≤50). **범례 스와치(`.swatch-*`)도 같은 토큰을 써야 함** — 마커와 어긋나면 범례가 거짓말이 됨.

> 규칙: `--info` 는 CSS 와 차트가 같은 값(`#0891b2`)을 공유. 같은 시맨틱에 두 색 금지.

### 모서리 (5단계만 사용)
`--r-xs 4px` · `--r-sm 6px` · `--r-md 8px` · `--r-lg 12px` (카드 기본) · `--r-pill 999px`.
예외: 포커스 링 `2px`, 원형 요소 `50%`.

### 간격 (8px 기반)
`--sp-1 4` · `--sp-2 8` · `--sp-3 12` · `--sp-4 16` · `--sp-5 24` · `--sp-6 32`. **신규 작업은 이 토큰 사용.** (기존 하드코딩 padding 은 점진 이행.)

### 그림자 / 폰트
`--shadow-sm` `--shadow` `--shadow-md`.
`--font-sans`: **Inter** 우선 → `-apple-system, "Segoe UI", "Pretendard", "Noto Sans KR", system-ui`.
`--font-mono`: `ui-monospace, "SF Mono", Menlo, Consolas`.

---

## 2. 타이포그래피

- 본문 16px (≥16px). 라벨/캡션 ≥12px (11px 금지).
- h1 26px/700, 섹션 h2 12px/600(대문자톤), 카드 h3 16px/600.
- **숫자는 mono 폰트(`--font-mono`)로 tabular 정렬** — KPI 값(`.kpi-value`), 표 숫자칸(`.ranking-table td.num`), `.stat-value`. (`font-variant-numeric` 가 아니라 mono 로 정렬함.)

---

## 3. 내비게이션 IA (2단계)

모든 페이지가 **동일한 1차 뷰 전환기**를 같은 위치(헤더 우측)에 갖는다.

- **1차 (어디서나):** `전체` · `시계열 추세` · `고속도로 휴게소` — `.view-nav` 세그먼트 컨트롤. 현재 뷰는 `.view-tab.is-active` (배경 `--bg-card`, 색 `--accent`) + `aria-current="page"`.
- **2차 (고속도로 안에서만):** `차트·지도·운영자·활성도·노선·휴게소·비교` — `.sub-nav` 의 `.sub-tab`. **7개 전부 표시하고 현재만 활성**(`--accent-bg`). 현재 페이지를 빼지 말 것(어디 있는지 모르게 됨).
- `문서` 는 분석 뷰가 아니라 **유틸리티** — `.header-util` 에 `.nav-link-muted` 로 분리.
- **breadcrumb 사용 안 함** (1차 내비에 `전체` 가 항상 있음). 화살표(→) 접미사 금지(평행 뷰지 순서가 아님).
- 헤더 마크업은 현재 9개 파일에 복붙됨 → 새 페이지 추가 시 공유 컴포넌트(`docs/_shared.js` 방식)로 추출 권장.

---

## 4. 컴포넌트

- **카드**: `.kpi` / `.chart-card` / `.insight-card` — `--bg-card`, `--border`, `--r-lg`, `--shadow-sm`. 카드는 *상호작용일 때만* 사용(장식용 카드 그리드 금지). KPI 카드는 비대화형 readout.
- **표**: `.ranking-table` `width:100% + min-width:680px`, `.table-wrap { overflow-x:auto }` 로 모바일에서 **구겨지지 않고 가로 스크롤**. 숫자칸 mono + 우측정렬.
- **탭/칩/셀렉트/버튼**: `.view-tab` `.sub-tab` `.tab-btn` `.preset-btn` `.chip-x` — 데스크톱은 조밀, 터치 기기는 `@media (pointer: coarse)` 로 44px 확보.
- **지도**: Leaflet + CARTO **Positron(밝은)** 타일 (다크 타일 금지 — 앱이 밝은 톤). 마커/범례 색 = `--kw-*`.

---

## 5. 상호작용 · 접근성

- **포커스**: 전역 `:focus-visible { outline: 2px solid var(--accent); offset 2px }`. `outline:none` 단독 사용 금지.
- **터치 타깃**: `@media (pointer: coarse)` 에서 대화형 요소 min 44px. (데스크톱은 조밀 유지.)
- **대비**: 본문/라벨 AA(4.5:1). `--text-muted #6b7280` 가 최저선.
- **시맨틱**: 현재 내비 항목에 `aria-current="page"`. nav 에 `aria-label`.

---

## 6. 차트 (Chart.js)

- 폰트: `Chart.defaults.font.family` = `--font-sans` 와 동일(Inter 우선). OS 기본폰트 금지.
- 색: **하드코딩 hex 금지.** 각 스크립트 상단에서 `getComputedStyle(document.documentElement)` 로 CSS 토큰을 읽어 `const C = {...}` 구성(단일 소스). 카테고리형 다색 팔레트(`OP_PALETTE`/`PALETTE`)는 `C.*` 조합.
- 도넛/파이 세그먼트 보더 = `--bg-card`(흰색). 어두운 보더(`#131820`) 금지(다크 잔재).
- **재렌더 시 `mountChart(id, config)` 로 이전 인스턴스 파기 후 생성** (직접 `new Chart` 금지 — 필터·테마 재렌더에서 누수·겹침).

### 크로스필터 패턴 (메인 대시보드)
데이터가 이미 브라우저(DuckDB-WASM)에 있으므로 필터=즉시 재쿼리. 새 필터 차원 추가 시 이 패턴을 따른다:
- 차트 막대 `onClick` → 필터값 set → 쿼리에 조건 주입(`sidoSql` 처럼 `WHERE del_yn='N'` 뒤에) → 영향 차트+KPI 재렌더.
- 활성 필터는 **제거 가능한 칩**(`.region-chip`)으로 표시 + **URL 쿼리스트링**에 저장(`?sido=`, 공유·뒤로가기). 알 수 없는 값은 무시(변조 방어).
- **전국 기준 내러티브(인사이트 카드)는 필터 시 숨김** — 스코프가 안 맞는 문구를 보이지 않게.

---

## 7. docs 읽기 모드 서브브랜드 (`web/docs/_docs.css`)

장문 문서는 의도적으로 다른 **읽기 treatment** 를 가진다 (Stripe/Linear 의 앱≠문서 패턴):
- 배경 `--ivory #FAF9F5`, 세리프 헤드라인(`ui-serif`), 따뜻한 그레이 스케일(`--g100~g700`, `--oat`, `--olive`), 넓은 측정폭.
- **단, 브랜드 강조색은 앱과 통일**: `--clay`/`--clay-d` = 앱 인디고(`#5b5bd6`/`#4f46e5`). 색 점프로 "다른 사이트" 착각을 막는 **브랜드 브리지** 규칙.
- 즉 *읽기 스타일은 분리, 브랜드 색은 공유.* 대시보드의 조밀 인디고 UI 를 문서에 강제하지 말 것(산문 가독성 손상).

---

## 8. 운영 컨벤션

- **테마**: 라이트/다크 토글(`.theme-toggle` + `theme.js` + `<head>` 선설정). 다크는 `:root[data-theme="dark"]` 토큰만 재정의 — 새 색은 토큰에 추가하면 두 테마 자동 반영. 지도 타일은 `data-theme` 으로 light_all/dark_all 선택. (docs `_docs.css` 는 아직 라이트 전용 — 추후 다크 대응 가능.)
- **캐시 버전**: 모든 자산 참조에 `?v=N`. 배포 시 사이트 전역으로 동시에 bump (부분 bump 금지 — 페이지 간 자산 불일치 방지). 현재 `?v=7`.
- **데이터 정직성** (콘텐츠 규칙, 디자인과 함께 지킬 것):
  - 합성/데모 데이터는 페이지 상단 경고 배너로 명시 (`trends.html`).
  - "진행 중" 기간(스냅샷 시점까지만 집계된 연도 등)은 과소집계 경고.
  - 비가동(`stat 1/4/5`)과 모니터링 미연동(`stat 9`)을 분리 표기 — 합치지 말 것.
- **AI 슬롭 금지**: 보라 그라데이션 히어로, 3열 아이콘-원 그리드, 전체 가운데정렬, 균일 큰 라운드, 장식 블롭, 이모지 장식 — 전부 금지. (현재 점수 AI Slop A-.)

---

## 9. 드리프트 방지 원칙 (이 문서의 핵심)

1. 색/모서리/간격은 **`:root` 토큰에서만**. 컴포넌트·JS·차트는 토큰을 *참조*.
2. 같은 시맨틱에 두 값 금지 (info, 범례=마커).
3. 새 결정 → **DESIGN.md 먼저 갱신** → 코드.
4. 새 페이지 → 1차 내비 그대로, 자산 `?v` 동일하게.

---

*최종 갱신: 2026-06-02 디자인 감사 + 수정 사이클 (대비·포커스·밝은지도·모바일표·색단일화·내비통일·타이포·토큰스케일·docs 브리지·라이트/다크 토글). 상세 커밋은 git log `style(design)/style(web)/feat(web)/refactor(web)` 참조.*
