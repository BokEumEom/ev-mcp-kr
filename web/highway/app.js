// 고속도로 휴게소 충전 인프라 — 별도 페이지.
// 메인 대시보드와 동일 데이터를 사용하되 kind_detail='C001' 필터 후 분석.

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";
import "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js";

const PARQUET_URL = "/scratch/chargers_snapshot.parquet";
const CODE_URLS = {
  sido: "/src/ev_mcp/codes/sido.json",
  busi: "/src/ev_mcp/codes/busi_id.json",
  chgerType: "/src/ev_mcp/codes/charger_type.json",
};

const DC_CODES = ["01", "03", "04", "05", "06", "08", "09", "10"];
const AVAILABLE_CODE = "2";
const HIGHWAY_KIND_DETAIL = "C001"; // 고속도로 휴게소

// ─── UI 헬퍼 ───
const $ = (id) => document.getElementById(id);
const setStatus = (t) => ($("status-text").textContent = t);

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
    "ops-title",
    "card-operators",
    "dist-title",
    "card-sido",
    "card-output",
    "station-title",
    "card-stations",
    "header-badge",
  ]) {
    const el = $(id);
    if (el) el.hidden = false;
  }
}

function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

const fmtInt = (n) => Number(n).toLocaleString("ko-KR");
const fmtPct = (p, d = 1) => (Number(p) * 100).toFixed(d) + "%";
const fmtNum = (n, d = 1) => Number(n).toFixed(d);
const shortSido = (s) =>
  (s || "").replace(/특별자치(도|시)$/, "").replace(/광역시$/, "");

const C = {
  text: "#ecf0f4",
  textDim: "#8b96a4",
  grid: "#232c38",
  primary: "#6ee7b7",
  warn: "#fbbf24",
  danger: "#f87171",
  info: "#7dd3fc",
  purple: "#c4b5fd",
  amber: "#fcd34d",
  lime: "#bef264",
  rose: "#fda4af",
};

Chart.defaults.color = C.textDim;
Chart.defaults.borderColor = C.grid;
Chart.defaults.font.family =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", "Pretendard", "Noto Sans KR", system-ui, sans-serif';
Chart.defaults.plugins.legend.labels.color = C.text;

// ─── DuckDB-WASM 초기화 ───
async function initDuckDB() {
  setStatus("DuckDB-WASM 번들 선택 중…");
  const bundles = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(bundles);
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], {
      type: "text/javascript",
    }),
  );
  const worker = new Worker(workerUrl);
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger("WARNING"), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  $("duckdb-version").textContent = "v" + (await db.getVersion());

  setStatus(`Parquet 다운로드 중 (${PARQUET_URL})…`);
  const res = await fetch(PARQUET_URL);
  if (!res.ok) {
    throw new Error(
      `Parquet fetch 실패: ${res.status} ${res.statusText}\nURL: ${PARQUET_URL}`,
    );
  }
  const buf = new Uint8Array(await res.arrayBuffer());
  setStatus(`Parquet 등록 중 (${(buf.byteLength / 1024 / 1024).toFixed(1)}MB)…`);
  await db.registerFileBuffer("chargers.parquet", buf);
  return db;
}

// ─── 쿼리 (모두 kind_detail='C001' 필터링) ───
const inList = (codes) => codes.map((c) => `'${c}'`).join(",");

const HW_FILTER = `del_yn = 'N' AND kind_detail = '${HIGHWAY_KIND_DETAIL}'`;

const Q_KPI = `
  SELECT
    COUNT(*)                                                                      AS total_chargers,
    COUNT(DISTINCT stat_id)                                                       AS stations,
    COUNT(DISTINCT busi_id)                                                       AS operators,
    SUM(CASE WHEN stat = '${AVAILABLE_CODE}' THEN 1 ELSE 0 END)                   AS available_now,
    AVG(TRY_CAST(output AS DOUBLE))                                               AS avg_output_kw,
    AVG(CASE WHEN TRY_CAST(output AS DOUBLE) >= 200 THEN 1.0 ELSE 0.0 END)        AS ratio_200plus,
    SUM(CASE WHEN TRY_CAST(output AS DOUBLE) >= 200 THEN 1 ELSE 0 END)            AS count_200plus,
    AVG(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1.0 ELSE 0.0 END)      AS dc_ratio,
    MAX(stat_upd_dt)                                                              AS latest_upd
  FROM 'chargers.parquet'
  WHERE ${HW_FILTER}
`;

// 비교용 — 전체 평균 (인사이트 카드에서 사용)
const Q_OVERALL = `
  SELECT
    COUNT(*)                                                                      AS total_chargers,
    AVG(TRY_CAST(output AS DOUBLE))                                               AS avg_output_kw,
    AVG(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1.0 ELSE 0.0 END)      AS dc_ratio
  FROM 'chargers.parquet'
  WHERE del_yn = 'N'
`;

const Q_OPERATORS = `
  SELECT
    busi_id,
    ANY_VALUE(busi_nm)                                                            AS busi_nm,
    COUNT(*)                                                                      AS total_chargers,
    AVG(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1.0 ELSE 0.0 END)      AS dc_ratio,
    AVG(TRY_CAST(output AS DOUBLE))                                               AS avg_output_kw
  FROM 'chargers.parquet'
  WHERE ${HW_FILTER}
  GROUP BY busi_id
  ORDER BY total_chargers DESC
  LIMIT 12
`;

const Q_SIDO = `
  SELECT
    zcode,
    COUNT(*) AS total_chargers,
    COUNT(DISTINCT stat_id) AS stations,
    COUNT(DISTINCT busi_id) AS operators
  FROM 'chargers.parquet'
  WHERE ${HW_FILTER}
  GROUP BY zcode
  ORDER BY total_chargers DESC
`;

const Q_OUTPUT = `
  WITH typed AS (
    SELECT TRY_CAST(output AS DOUBLE) AS kw
    FROM 'chargers.parquet'
    WHERE ${HW_FILTER} AND output IS NOT NULL
  )
  SELECT bucket, cnt FROM (
    SELECT
      CASE
        WHEN kw <= 50          THEN 'A_le50'
        WHEN kw <= 100         THEN 'B_51to100'
        WHEN kw <= 200         THEN 'C_101to200'
        WHEN kw <= 350         THEN 'D_201to350'
        ELSE                        'E_350plus'
      END AS bucket,
      COUNT(*) AS cnt
    FROM typed
    GROUP BY bucket
  ) ORDER BY bucket
`;

const OUTPUT_LABELS = {
  A_le50: "≤50 kW",
  B_51to100: "51~100 kW",
  C_101to200: "101~200 kW",
  D_201to350: "201~350 kW",
  E_350plus: "350+ kW",
};

const Q_TOP_STATIONS = `
  SELECT
    stat_id,
    ANY_VALUE(stat_nm) AS stat_nm,
    ANY_VALUE(addr) AS addr,
    ANY_VALUE(zcode) AS zcode,
    COUNT(*) AS chargers,
    AVG(TRY_CAST(output AS DOUBLE)) AS avg_kw,
    COUNT(DISTINCT busi_id) AS operators
  FROM 'chargers.parquet'
  WHERE ${HW_FILTER}
  GROUP BY stat_id
  ORDER BY chargers DESC
  LIMIT 12
`;

async function runQuery(conn, sql) {
  const result = await conn.query(sql);
  return JSON.parse(
    JSON.stringify(result.toArray(), (_, v) =>
      typeof v === "bigint" ? Number(v) : v,
    ),
  );
}

async function loadCodes() {
  const entries = await Promise.all(
    Object.entries(CODE_URLS).map(async ([name, url]) => {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`코드 테이블 fetch 실패: ${url}`);
      return [name, await r.json()];
    }),
  );
  return Object.fromEntries(entries);
}

// ─── 렌더 ───

function renderKpi(kpi) {
  const total = Number(kpi.total_chargers);
  $("kpi-total").textContent = fmtInt(total);
  $("kpi-stations").textContent = fmtInt(kpi.stations);
  $("kpi-operators").textContent = fmtInt(kpi.operators);
  $("kpi-operators-sub").textContent =
    "전체 145곳 중 " + fmtInt(kpi.operators) + "곳 진입";
  $("kpi-avg-output").textContent = fmtNum(kpi.avg_output_kw, 1);
  $("kpi-200plus").textContent = fmtPct(kpi.ratio_200plus, 1);
  $("kpi-200plus-sub").textContent = fmtInt(kpi.count_200plus) + " 대";
  $("kpi-available").textContent = fmtInt(kpi.available_now);
  $("kpi-available-pct").textContent =
    "전체의 " + fmtPct(kpi.available_now / total, 1);

  if (kpi.latest_upd) {
    const d = String(kpi.latest_upd).slice(0, 10);
    $("snapshot-date").textContent = `스냅샷 ${d}`;
    $("header-snapshot").textContent = `${d} 기준 ${fmtInt(total)}대`;
  }
  $("row-count").textContent = fmtInt(total) + " rows";
}

function renderInsights(kpi, overall, operators, sido) {
  const grid = $("insight-grid");
  grid.textContent = "";

  const insights = [];

  // 1) DC 비율 격차
  const dcGap = kpi.dc_ratio / overall.dc_ratio;
  insights.push({
    color: "info",
    headline: fmtNum(dcGap, 1) + "×",
    title: "DC 비율 격차",
    body: `고속도로 ${fmtPct(kpi.dc_ratio, 1)} vs 전체 ${fmtPct(overall.dc_ratio, 1)}. 장거리 빠른 충전 인프라가 거의 완전히 DC 로 분리.`,
  });

  // 2) 평균 출력 격차
  const kwGap = kpi.avg_output_kw / overall.avg_output_kw;
  insights.push({
    color: "default",
    headline: fmtNum(kwGap, 1) + "×",
    title: "평균 출력 격차",
    body: `고속도로 ${fmtNum(kpi.avg_output_kw, 1)} kW vs 전체 ${fmtNum(overall.avg_output_kw, 1)} kW. 일반 시설은 7kW AC 위주, 고속도로는 100~200kW 급속 중심.`,
  });

  // 3) 운영자 시장 점유 — top 1 의 점유율
  const topOp = operators[0];
  const topShare = topOp.total_chargers / kpi.total_chargers;
  insights.push({
    color: "purple",
    headline: fmtPct(topShare, 0),
    title: `${topOp.busi_nm || topOp.busi_id} 시장 점유 1위`,
    body: `${fmtInt(topOp.total_chargers)}대 — 운영자 ${kpi.operators}곳 중 1곳이 전체의 ${fmtPct(topShare, 1)} 차지. 일반 인프라보다 운영자 집중도 높음.`,
  });

  // 4) 시도 1위 점유
  const topSido = sido[0];
  const sidoShare = topSido.total_chargers / kpi.total_chargers;
  insights.push({
    color: "warn",
    headline: fmtPct(sidoShare, 0),
    title: "수도권 진입 관문 집중",
    body: `1위 시도(zcode=${topSido.zcode}) 가 ${fmtInt(topSido.total_chargers)}대 (${fmtPct(sidoShare, 1)}). 휴게소 ${fmtInt(topSido.stations)}개 분산.`,
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

function renderOperators(rows, codes) {
  const labels = rows.map((r) => {
    const lbl = codes.busi[r.busi_id] || r.busi_nm || r.busi_id;
    return lbl.length > 16 ? lbl.slice(0, 15) + "…" : lbl;
  });
  new Chart($("chart-operators").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "충전기 수",
        data: rows.map((r) => r.total_chargers),
        backgroundColor: rows.map((r) =>
          Number(r.avg_output_kw) >= 200 ? C.primary : C.info,
        ),
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
                `평균 출력: ${fmtNum(r.avg_output_kw, 1)} kW`,
                `DC 비율: ${fmtPct(r.dc_ratio, 1)}`,
              ];
            },
          },
        },
      },
    },
  });
}

function renderSido(rows, codes) {
  const labels = rows.map((r) => shortSido(codes.sido[r.zcode] || r.zcode));
  new Chart($("chart-sido").getContext("2d"), {
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
                `휴게소 수: ${r.stations}`,
                `운영자 수: ${r.operators}`,
              ];
            },
          },
        },
      },
    },
  });
}

function renderOutput(rows) {
  new Chart($("chart-output").getContext("2d"), {
    type: "bar",
    data: {
      labels: rows.map((r) => OUTPUT_LABELS[r.bucket] || r.bucket),
      datasets: [{
        label: "충전기 수",
        data: rows.map((r) => r.cnt),
        backgroundColor: rows.map((r) =>
          r.bucket === "D_201to350" || r.bucket === "E_350plus"
            ? C.primary
            : r.bucket === "C_101to200"
              ? C.amber
              : C.info,
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

function renderStations(rows, codes) {
  const labels = rows.map((r) => {
    const sido = shortSido(codes.sido[r.zcode] || r.zcode);
    const nm = (r.stat_nm || r.stat_id).slice(0, 22);
    return `${sido} ${nm}`;
  });
  new Chart($("chart-stations").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "충전기 수",
        data: rows.map((r) => r.chargers),
        backgroundColor: rows.map((r) =>
          Number(r.avg_kw) >= 200 ? C.primary : C.info,
        ),
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
                `평균 출력: ${fmtNum(r.avg_kw, 1)} kW`,
                `운영자 수: ${r.operators}`,
                `주소: ${(r.addr || "").slice(0, 40)}`,
              ];
            },
          },
        },
      },
    },
  });
}

// ─── 메인 ───
async function main() {
  try {
    if (location.protocol === "file:") {
      throw new Error(
        "file:// 로 열렸습니다. 정적 서버가 필요합니다.\n" +
          "cd /home/bokeum/ai/ev_mcp && python -m http.server 8000",
      );
    }
    const db = await initDuckDB();
    const conn = await db.connect();

    setStatus("쿼리 6건 병렬 실행…");
    const [codes, [kpi], [overall], operators, sido, output, stations] =
      await Promise.all([
        loadCodes(),
        runQuery(conn, Q_KPI),
        runQuery(conn, Q_OVERALL),
        runQuery(conn, Q_OPERATORS),
        runQuery(conn, Q_SIDO),
        runQuery(conn, Q_OUTPUT),
        runQuery(conn, Q_TOP_STATIONS),
      ]);

    renderKpi(kpi);
    renderInsights(kpi, overall, operators, sido);
    renderOperators(operators, codes);
    renderSido(sido, codes);
    renderOutput(output);
    renderStations(stations, codes);

    revealAll();
    await conn.close();
  } catch (e) {
    showError(e);
  }
}

main();
