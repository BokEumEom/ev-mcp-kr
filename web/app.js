// ev-mcp 분석 대시보드 v2 — DuckDB-WASM 으로 Parquet 을 브라우저에서 직접 query.
// Stage 10.2 (ADR-001) 의 분석 쿼리 + 추가 인사이트 확장.

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";
import "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js";

// ──────────────────────────────────────────────────────────────────────────
// 설정 — 프로젝트 루트 기준 절대 경로. 루트에서 `python -m http.server` 실행
// ──────────────────────────────────────────────────────────────────────────
const PARQUET_URL = "/scratch/chargers_snapshot.parquet";
const CODE_URLS = {
  sido: "/src/ev_mcp/codes/sido.json",
  sigungu: "/src/ev_mcp/codes/sigungu.json",
  busi: "/src/ev_mcp/codes/busi_id.json",
  chgerType: "/src/ev_mcp/codes/charger_type.json",
  kind: "/src/ev_mcp/codes/kind.json",
};

// 분석 쿼리 코드 정의 — Stage 10.4 의 운영 검증된 분류
const DOWNTIME_CODES = ["1", "4", "5"]; // 통신이상/운영중지/점검중
const UNMONITORED_CODE = "9"; // 상태미확인 (모니터링 미연동)
const AVAILABLE_CODE = "2"; // 충전대기
const DC_CODES = ["01", "03", "04", "05", "06", "08", "09", "10"];

// ──────────────────────────────────────────────────────────────────────────
// UI 헬퍼
// ──────────────────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

function setStatus(text) {
  $("status-text").textContent = text;
}

function showError(err) {
  $("status").hidden = true;
  $("error-panel").hidden = false;
  $("error-message").textContent =
    err?.stack || err?.message || String(err);
  console.error(err);
}

function revealAll() {
  $("status").hidden = true;
  for (const id of [
    "kpi-grid",
    "insights",
    "charts-title",
    "card-operators",
    "region-title",
    "card-density",
    "card-dc-ratio",
    "composition-title",
    "card-types",
    "card-output",
    "growth-title",
    "card-year",
    "card-kind",
    "header-badge",
  ]) {
    const el = $(id);
    if (el) el.hidden = false;
  }
}

function fmtInt(n) {
  return Number(n).toLocaleString("ko-KR");
}
function fmtPct(p, digits = 1) {
  return (Number(p) * 100).toFixed(digits) + "%";
}
function fmtNum(n, digits = 1) {
  return Number(n).toFixed(digits);
}

// Safe DOM 헬퍼 — textContent only, innerHTML 사용 X
function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

// Chart.js dark-theme defaults
const C = {
  text: "#ecf0f4",
  textDim: "#8b96a4",
  grid: "#232c38",
  primary: "#6ee7b7",
  warn: "#fbbf24",
  danger: "#f87171",
  info: "#7dd3fc",
  purple: "#c4b5fd",
  rose: "#fda4af",
  amber: "#fcd34d",
  lime: "#bef264",
};

Chart.defaults.color = C.textDim;
Chart.defaults.borderColor = C.grid;
Chart.defaults.font.family =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", "Pretendard", "Noto Sans KR", system-ui, sans-serif';
Chart.defaults.plugins.legend.labels.color = C.text;

// ──────────────────────────────────────────────────────────────────────────
// DuckDB-WASM 초기화
// ──────────────────────────────────────────────────────────────────────────

async function initDuckDB() {
  setStatus("분석 엔진 준비 중…");
  const bundles = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(bundles);

  setStatus("분석 엔진 준비 중…");
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], {
      type: "text/javascript",
    }),
  );
  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger("WARNING");
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  $("duckdb-version").textContent = "v" + (await db.getVersion());

  setStatus(`충전소 데이터 불러오는 중…`);
  const res = await fetch(PARQUET_URL);
  if (!res.ok) {
    throw new Error(
      `Parquet fetch 실패: ${res.status} ${res.statusText}\n` +
        `URL: ${PARQUET_URL}\n` +
        `프로젝트 루트에서 'python -m http.server 8000' 실행했는지 확인하세요.`,
    );
  }
  const buf = new Uint8Array(await res.arrayBuffer());
  setStatus(`충전소 데이터 불러오는 중… (${(buf.byteLength / 1024 / 1024).toFixed(1)}MB)`);
  await db.registerFileBuffer("chargers.parquet", buf);

  return db;
}

// ──────────────────────────────────────────────────────────────────────────
// 쿼리
// ──────────────────────────────────────────────────────────────────────────

const inList = (codes) => codes.map((c) => `'${c}'`).join(",");

const Q_KPI = `
  SELECT
    COUNT(*)                                                                          AS total_chargers,
    COUNT(DISTINCT busi_id)                                                           AS operator_count,
    COUNT(DISTINCT zscode)                                                            AS sigungu_count,
    SUM(CASE WHEN stat = '${AVAILABLE_CODE}' THEN 1 ELSE 0 END)                       AS available_now,
    AVG(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1.0 ELSE 0.0 END)          AS dc_ratio,
    SUM(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1 ELSE 0 END)              AS dc_count,
    AVG(CASE WHEN use_time LIKE '%24%' THEN 1.0 ELSE 0.0 END)                         AS h24_ratio,
    SUM(CASE WHEN use_time LIKE '%24%' THEN 1 ELSE 0 END)                             AS h24_count,
    AVG(CASE WHEN parking_free = 'Y' THEN 1.0 ELSE 0.0 END)                           AS free_parking_ratio,
    SUM(CASE WHEN parking_free = 'Y' THEN 1 ELSE 0 END)                               AS free_parking_count,
    AVG(TRY_CAST(output AS DOUBLE))                                                   AS avg_output_kw,
    MAX(stat_upd_dt)                                                                  AS latest_upd
  FROM 'chargers.parquet'
  WHERE del_yn = 'N'
`;

const Q_OPERATORS = `
  SELECT
    busi_id,
    ANY_VALUE(busi_nm)                                                            AS busi_nm,
    COUNT(*)                                                                      AS total_chargers,
    SUM(CASE WHEN stat IN (${inList(DOWNTIME_CODES)}) THEN 1 ELSE 0 END)          AS downtime_count,
    AVG(CASE WHEN stat IN (${inList(DOWNTIME_CODES)}) THEN 1.0 ELSE 0.0 END)      AS downtime_ratio,
    SUM(CASE WHEN stat = '${UNMONITORED_CODE}' THEN 1 ELSE 0 END)                 AS unmonitored_count,
    AVG(CASE WHEN stat = '${UNMONITORED_CODE}' THEN 1.0 ELSE 0.0 END)             AS unmonitored_ratio
  FROM 'chargers.parquet'
  WHERE del_yn = 'N'
  GROUP BY busi_id
  HAVING COUNT(*) >= 100
  ORDER BY downtime_ratio DESC, total_chargers DESC
  LIMIT 10
`;

const Q_DENSITY = `
  SELECT zcode, zscode,
    COUNT(*) AS total_chargers,
    COUNT(DISTINCT busi_id) AS distinct_operators,
    AVG(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1.0 ELSE 0.0 END) AS dc_ratio
  FROM 'chargers.parquet'
  WHERE del_yn = 'N' AND zscode IS NOT NULL
  GROUP BY zcode, zscode
  ORDER BY total_chargers DESC
  LIMIT 10
`;

const Q_SIDO_DC = `
  SELECT zcode,
    COUNT(*) AS total_chargers,
    SUM(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1 ELSE 0 END) AS dc_count,
    AVG(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1.0 ELSE 0.0 END) AS dc_ratio
  FROM 'chargers.parquet'
  WHERE del_yn = 'N'
  GROUP BY zcode
  ORDER BY dc_ratio DESC
`;

const Q_CHGER_TYPE = `
  SELECT chger_type, COUNT(*) AS cnt
  FROM 'chargers.parquet'
  WHERE del_yn = 'N'
  GROUP BY chger_type
  ORDER BY cnt DESC
`;

const Q_OUTPUT = `
  WITH typed AS (
    SELECT TRY_CAST(output AS DOUBLE) AS kw
    FROM 'chargers.parquet'
    WHERE del_yn = 'N' AND output IS NOT NULL
  )
  SELECT bucket, cnt FROM (
    SELECT
      CASE
        WHEN kw IS NULL        THEN '미상'
        WHEN kw <= 7           THEN 'A_le7'
        WHEN kw <= 14          THEN 'B_8to14'
        WHEN kw <= 30          THEN 'C_15to30'
        WHEN kw <= 50          THEN 'D_31to50'
        WHEN kw <= 100         THEN 'E_51to100'
        WHEN kw <= 200         THEN 'F_101to200'
        ELSE                        'G_200plus'
      END AS bucket,
      COUNT(*) AS cnt
    FROM typed
    GROUP BY bucket
  ) ORDER BY bucket
`;

const OUTPUT_BUCKET_LABELS = {
  A_le7: "≤7 kW",
  B_8to14: "8~14 kW",
  C_15to30: "15~30 kW",
  D_31to50: "31~50 kW",
  E_51to100: "51~100 kW",
  F_101to200: "101~200 kW",
  G_200plus: "200+ kW",
  미상: "미상",
};

const Q_YEAR = `
  SELECT year, COUNT(*) AS cnt
  FROM 'chargers.parquet'
  WHERE del_yn = 'N' AND year IS NOT NULL
    AND TRY_CAST(year AS INTEGER) BETWEEN 2015 AND 2026
  GROUP BY year
  ORDER BY year
`;

const Q_KIND = `
  SELECT kind, COUNT(*) AS cnt
  FROM 'chargers.parquet'
  WHERE del_yn = 'N' AND kind IS NOT NULL
  GROUP BY kind
  ORDER BY cnt DESC
`;

async function runQuery(conn, sql) {
  const result = await conn.query(sql);
  return JSON.parse(
    JSON.stringify(result.toArray(), (_, v) =>
      typeof v === "bigint" ? Number(v) : v,
    ),
  );
}

// ──────────────────────────────────────────────────────────────────────────
// 코드 → 한국어 라벨
// ──────────────────────────────────────────────────────────────────────────

async function loadCodes() {
  const entries = await Promise.all(
    Object.entries(CODE_URLS).map(async ([name, url]) => {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`코드 테이블 fetch 실패: ${url} ${r.status}`);
      return [name, await r.json()];
    }),
  );
  return Object.fromEntries(entries);
}

const shortSido = (s) =>
  (s || "").replace(/특별자치(도|시)$/, "").replace(/광역시$/, "");

// ──────────────────────────────────────────────────────────────────────────
// 렌더 — KPI
// ──────────────────────────────────────────────────────────────────────────

function renderKpi(kpi) {
  const total = Number(kpi.total_chargers);
  const operators = Number(kpi.operator_count);
  const sigungu = Number(kpi.sigungu_count);
  const available = Number(kpi.available_now);

  $("kpi-total").textContent = fmtInt(total);
  $("kpi-operators").textContent = fmtInt(operators);
  $("kpi-sigungu").textContent = fmtInt(sigungu);
  $("kpi-available").textContent = fmtInt(available);
  $("kpi-available-pct").textContent =
    "전체의 " + fmtPct(available / total, 1);

  $("kpi-dc-ratio").textContent = fmtPct(kpi.dc_ratio, 1);
  $("kpi-dc-sub").textContent = fmtInt(kpi.dc_count) + " 대";

  $("kpi-24h").textContent = fmtPct(kpi.h24_ratio, 1);
  $("kpi-24h-sub").textContent = fmtInt(kpi.h24_count) + " 대";

  $("kpi-free-parking").textContent = fmtPct(kpi.free_parking_ratio, 1);
  $("kpi-free-parking-sub").textContent = fmtInt(kpi.free_parking_count) + " 대";

  $("kpi-avg-output").textContent = fmtNum(kpi.avg_output_kw, 1);

  if (kpi.latest_upd) {
    const d = String(kpi.latest_upd).slice(0, 10);
    $("snapshot-date").textContent = `스냅샷 ${d}`;
    $("header-snapshot").textContent = `${d} 기준 ${fmtInt(total)}대`;
  }
  $("row-count").textContent = fmtInt(total) + " rows";
}

// ──────────────────────────────────────────────────────────────────────────
// 렌더 — 자동 인사이트 카드 (안전한 DOM 메서드만 사용)
// ──────────────────────────────────────────────────────────────────────────

function renderInsights({ kpi, chgerType, year, sidoDc, codes }) {
  const grid = $("insight-grid");
  grid.textContent = ""; // safe clear

  const insights = [];

  // 1) 충전기 타입 압도적 1위
  const total = chgerType.reduce((s, r) => s + r.cnt, 0);
  const topType = chgerType[0];
  const topLabel = codes.chgerType[topType.chger_type] || topType.chger_type;
  insights.push({
    color: "info",
    headline: fmtPct(topType.cnt / total, 1),
    title: `${topLabel} 가 압도적`,
    body: `전체 ${fmtInt(total)}대 중 ${fmtInt(topType.cnt)}대. 한국 충전 인프라는 여전히 완속 위주.`,
  });

  // 2) 설치 폭증 연도
  const peakYear = year.reduce((a, b) => (b.cnt > a.cnt ? b : a), year[0]);
  const secondYear = year
    .filter((y) => y.year !== peakYear.year)
    .reduce((a, b) => (b.cnt > a.cnt ? b : a), year[0]);
  insights.push({
    color: "default",
    headline: peakYear.year,
    title: "역대 최다 설치 해",
    body: `${fmtInt(peakYear.cnt)}대 신규. 2022~2024 폭증 후 ${peakYear.year} 이후 감소세 (다음 ${secondYear.year}: ${fmtInt(secondYear.cnt)}).`,
  });

  // 3) 도시 vs 비도시 DC 비율 격차
  const urbanCodes = new Set(["11", "26", "27", "28", "29", "30", "31"]);
  const urban = sidoDc.filter((r) => urbanCodes.has(r.zcode));
  const rural = sidoDc.filter((r) => !urbanCodes.has(r.zcode));
  const urbanAvg =
    urban.reduce((s, r) => s + r.dc_ratio, 0) / Math.max(urban.length, 1);
  const ruralAvg =
    rural.reduce((s, r) => s + r.dc_ratio, 0) / Math.max(rural.length, 1);
  const ratio = ruralAvg / Math.max(urbanAvg, 0.001);
  insights.push({
    color: "purple",
    headline: fmtNum(ratio, 1) + "×",
    title: "비도시 vs 도시 DC 격차",
    body: `광역시 평균 DC ${fmtPct(urbanAvg)} vs 도/특별자치 평균 ${fmtPct(ruralAvg)}. 고속도로·휴게소 인프라 영향.`,
  });

  // 4) 24h 운영 비율
  insights.push({
    color: "default",
    headline: fmtPct(kpi.h24_ratio, 1),
    title: "24시간 운영 충전기",
    body: `${fmtInt(kpi.h24_count)}대가 24시간 운영. 제한 시간 충전기는 약 ${fmtPct(1 - kpi.h24_ratio, 1)}.`,
  });

  // 5) 즉시 사용 가능
  insights.push({
    color: "warn",
    headline: fmtPct(kpi.available_now / kpi.total_chargers),
    title: "즉시 사용 가능",
    body: `${fmtInt(kpi.available_now)}대가 충전대기 상태 (스냅샷 시점). 나머지는 충전중/모니터링 미연동/비가동 등.`,
  });

  for (const ins of insights) {
    const className = "insight-card " + (ins.color !== "default" ? ins.color : "");
    const card = makeEl("div", className);
    card.append(
      makeEl("div", "insight-headline", ins.headline),
      makeEl("div", "insight-title", ins.title),
      makeEl("div", "insight-body", ins.body),
    );
    grid.appendChild(card);
  }
}

// ──────────────────────────────────────────────────────────────────────────
// 렌더 — 차트
// ──────────────────────────────────────────────────────────────────────────

function renderOperators(rows, codes) {
  const labels = rows.map((r) => {
    const label = codes.busi[r.busi_id] || r.busi_nm || r.busi_id;
    return label.length > 14 ? label.slice(0, 13) + "…" : label;
  });
  new Chart($("chart-operators").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "비가동률",
          data: rows.map((r) => Number(r.downtime_ratio) * 100),
          backgroundColor: C.danger,
          borderWidth: 0,
        },
        {
          label: "미연동률",
          data: rows.map((r) => Number(r.unmonitored_ratio) * 100),
          backgroundColor: C.warn,
          borderWidth: 0,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { beginAtZero: true, max: 100, ticks: { callback: (v) => v + "%" }, grid: { color: C.grid } },
        y: { grid: { display: false } },
      },
      plugins: {
        tooltip: {
          callbacks: {
            afterBody: (ctx) => {
              const r = rows[ctx[0].dataIndex];
              return [
                `총 충전기: ${fmtInt(r.total_chargers)}`,
                `비가동: ${fmtInt(r.downtime_count)} (${fmtPct(r.downtime_ratio)})`,
                `미연동: ${fmtInt(r.unmonitored_count)} (${fmtPct(r.unmonitored_ratio)})`,
              ];
            },
          },
        },
      },
    },
  });
}

function renderDensity(rows, codes) {
  const labels = rows.map((r) => {
    const sido = codes.sido[r.zcode] || r.zcode;
    const gu = codes.sigungu[r.zscode] || r.zscode;
    return `${shortSido(sido)} ${gu}`;
  });
  new Chart($("chart-density").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "충전기 수",
        data: rows.map((r) => r.total_chargers),
        backgroundColor: C.primary,
        borderWidth: 0,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { beginAtZero: true, ticks: { callback: (v) => fmtInt(v) }, grid: { color: C.grid } },
        y: { grid: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody: (ctx) => {
              const r = rows[ctx[0].dataIndex];
              return [
                `운영자 수: ${r.distinct_operators}`,
                `DC 비율: ${fmtPct(r.dc_ratio)}`,
              ];
            },
          },
        },
      },
    },
  });
}

function renderDcRatio(rows, codes) {
  const top = rows.slice(0, 12);
  const labels = top.map((r) => shortSido(codes.sido[r.zcode] || r.zcode));
  new Chart($("chart-dc-ratio").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "DC 비율",
        data: top.map((r) => Number(r.dc_ratio) * 100),
        backgroundColor: top.map((r) =>
          Number(r.dc_ratio) > 0.15 ? C.primary : C.info,
        ),
        borderWidth: 0,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { beginAtZero: true, ticks: { callback: (v) => v + "%" }, grid: { color: C.grid } },
        y: { grid: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody: (ctx) => {
              const r = top[ctx[0].dataIndex];
              return [
                `총 충전기: ${fmtInt(r.total_chargers)}`,
                `DC 충전기: ${fmtInt(r.dc_count)}`,
              ];
            },
          },
        },
      },
    },
  });
}

function renderChgerType(rows, codes) {
  const top = rows.slice(0, 6);
  const rest = rows.slice(6);
  const restSum = rest.reduce((s, r) => s + r.cnt, 0);
  const labels = top.map((r) => codes.chgerType[r.chger_type] || r.chger_type);
  const data = top.map((r) => r.cnt);
  if (restSum > 0) {
    labels.push("기타");
    data.push(restSum);
  }
  const palette = [C.primary, C.info, C.purple, C.warn, C.rose, C.lime, C.textDim];

  new Chart($("chart-types").getContext("2d"), {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: palette.slice(0, data.length),
        borderColor: "#131820",
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right", labels: { color: C.text, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const total = data.reduce((a, b) => a + b, 0);
              return `${ctx.label}: ${fmtInt(ctx.parsed)} (${fmtPct(ctx.parsed / total)})`;
            },
          },
        },
      },
    },
  });
}

function renderOutput(rows) {
  const labels = rows.map((r) => OUTPUT_BUCKET_LABELS[r.bucket] || r.bucket);
  new Chart($("chart-output").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "충전기 수",
        data: rows.map((r) => r.cnt),
        backgroundColor: rows.map((r) =>
          r.bucket === "A_le7" || r.bucket === "B_8to14"
            ? C.info
            : r.bucket === "G_200plus" || r.bucket === "F_101to200"
              ? C.primary
              : C.purple,
        ),
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, ticks: { callback: (v) => fmtInt(v) }, grid: { color: C.grid } },
        x: { grid: { display: false } },
      },
      plugins: { legend: { display: false } },
    },
  });
}

function renderYear(rows) {
  new Chart($("chart-year").getContext("2d"), {
    type: "line",
    data: {
      labels: rows.map((r) => r.year),
      datasets: [{
        label: "신규 설치",
        data: rows.map((r) => r.cnt),
        borderColor: C.primary,
        backgroundColor: "rgba(110, 231, 183, 0.12)",
        fill: true,
        tension: 0.3,
        pointBackgroundColor: C.primary,
        pointRadius: 4,
        pointHoverRadius: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, ticks: { callback: (v) => fmtInt(v) }, grid: { color: C.grid } },
        x: { grid: { display: false } },
      },
      plugins: { legend: { display: false } },
    },
  });
}

function renderKind(rows, codes) {
  const top = rows.slice(0, 8);
  const labels = top.map((r) => codes.kind[r.kind] || r.kind);
  new Chart($("chart-kind").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "충전기 수",
        data: top.map((r) => r.cnt),
        backgroundColor: C.purple,
        borderWidth: 0,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { beginAtZero: true, ticks: { callback: (v) => fmtInt(v) }, grid: { color: C.grid } },
        y: { grid: { display: false } },
      },
      plugins: { legend: { display: false } },
    },
  });
}

// ──────────────────────────────────────────────────────────────────────────
// 메인
// ──────────────────────────────────────────────────────────────────────────

async function main() {
  try {
    if (location.protocol === "file:") {
      throw new Error(
        "file:// 로 열렸습니다. 정적 서버가 필요합니다.\n" +
          "프로젝트 루트에서 실행하세요:\n" +
          "  cd /home/bokeum/ai/ev_mcp\n" +
          "  python -m http.server 8000\n" +
          "그 뒤 http://localhost:8000/web/ 접속.",
      );
    }
    const db = await initDuckDB();
    const conn = await db.connect();

    setStatus("통계 계산 중…");
    const [
      codes,
      [kpi],
      operators,
      density,
      sidoDc,
      chgerType,
      output,
      year,
      kind,
    ] = await Promise.all([
      loadCodes(),
      runQuery(conn, Q_KPI),
      runQuery(conn, Q_OPERATORS),
      runQuery(conn, Q_DENSITY),
      runQuery(conn, Q_SIDO_DC),
      runQuery(conn, Q_CHGER_TYPE),
      runQuery(conn, Q_OUTPUT),
      runQuery(conn, Q_YEAR),
      runQuery(conn, Q_KIND),
    ]);

    renderKpi(kpi);
    renderInsights({ kpi, chgerType, year, sidoDc, codes });
    renderOperators(operators, codes);
    renderDensity(density, codes);
    renderDcRatio(sidoDc, codes);
    renderChgerType(chgerType, codes);
    renderOutput(output);
    renderYear(year);
    renderKind(kind, codes);

    revealAll();
    await conn.close();
  } catch (e) {
    showError(e);
  }
}

main();
