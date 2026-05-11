// 고속도로 노선 deep dive — 단일 노선 휴게소/출력/운영자/거리 분석.
// URL ?hw=경부고속도로 형태로 노선 선택. 드롭다운 변경 시 URL 갱신 + 차트 재렌더.

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";

const PARQUET_URL = "/scratch/chargers_snapshot.parquet";
const BUSI_URL = "/src/ev_mcp/codes/busi_id.json";
const CHGER_TYPE_URL = "/src/ev_mcp/codes/charger_type.json";

const DC_CODES = ["01", "03", "04", "05", "06", "08", "09", "10"];

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
    "stations-title",
    "card-stations",
    "composition-title",
    "card-output",
    "card-ops",
    "spacing-title",
    "card-spacing",
    "header-badge",
  ]) {
    const el = $(id);
    if (el) el.hidden = false;
  }
}

const fmtInt = (n) => Number(n).toLocaleString("ko-KR");
const fmtPct = (p, d = 1) => (Number(p) * 100).toFixed(d) + "%";
const fmtNum = (n, d = 1) => Number(n).toFixed(d);

function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

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

const OP_PALETTE = [
  C.primary, C.info, C.purple, C.warn, C.rose, C.amber, C.lime,
  "#fb923c", "#a78bfa", "#34d399", "#60a5fa", "#f472b6",
];

// haversine 거리 (km)
function haversineKm(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

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
  if (!res.ok) throw new Error(`Parquet fetch 실패: ${res.status} ${PARQUET_URL}`);
  const buf = new Uint8Array(await res.arrayBuffer());
  setStatus(`Parquet 등록 중 (${(buf.byteLength / 1024 / 1024).toFixed(1)}MB)…`);
  await db.registerFileBuffer("chargers.parquet", buf);
  return db;
}

const HW_FILTER = `del_yn = 'N' AND kind_detail = 'C001'`;
const DC_IN = DC_CODES.map((c) => `'${c}'`).join(",");

const Q_HW_LIST = `
  SELECT
    regexp_extract(addr, '([가-힣]+고속도로)', 1) AS hw,
    COUNT(*) AS chargers,
    COUNT(DISTINCT stat_id) AS stations
  FROM 'chargers.parquet' AS p
  WHERE ${HW_FILTER}
  GROUP BY hw
  HAVING hw != '' AND chargers >= 5
  ORDER BY chargers DESC
`;

const Q_OVERALL = `
  SELECT
    AVG(TRY_CAST(output AS DOUBLE)) AS avg_kw,
    AVG(CASE WHEN chger_type IN (${DC_IN}) THEN 1.0 ELSE 0.0 END) AS dc_ratio
  FROM 'chargers.parquet' AS p
  WHERE ${HW_FILTER}
`;

const OUTPUT_BUCKETS_SQL = `
  CASE
    WHEN TRY_CAST(output AS DOUBLE) <= 50  THEN 'A_le50'
    WHEN TRY_CAST(output AS DOUBLE) <= 100 THEN 'B_51to100'
    WHEN TRY_CAST(output AS DOUBLE) <= 200 THEN 'C_101to200'
    WHEN TRY_CAST(output AS DOUBLE) <= 350 THEN 'D_201to350'
    ELSE                                       'E_350plus'
  END
`;

const OUTPUT_LABELS = {
  A_le50: "≤50 kW",
  B_51to100: "51~100 kW",
  C_101to200: "101~200 kW",
  D_201to350: "201~350 kW",
  E_350plus: "350+ kW",
};

const Q_OUTPUT_OVERALL = `
  SELECT ${OUTPUT_BUCKETS_SQL} AS bucket, COUNT(*) AS cnt
  FROM 'chargers.parquet' AS p
  WHERE ${HW_FILTER} AND output IS NOT NULL
  GROUP BY bucket ORDER BY bucket
`;

function qStations(hw) {
  const esc = hw.replace(/'/g, "''");
  return `
    SELECT
      stat_id,
      ANY_VALUE(stat_nm) AS stat_nm,
      ANY_VALUE(addr) AS addr,
      ANY_VALUE(lat) AS lat,
      ANY_VALUE(lng) AS lng,
      ANY_VALUE(busi_id) AS busi_id,
      ANY_VALUE(busi_nm) AS busi_nm,
      COUNT(*) AS chargers,
      AVG(TRY_CAST(output AS DOUBLE)) AS avg_kw,
      AVG(CASE WHEN chger_type IN (${DC_IN}) THEN 1.0 ELSE 0.0 END) AS dc_ratio
    FROM 'chargers.parquet' AS p
    WHERE ${HW_FILTER} AND addr LIKE '%${esc}%'
      AND lat BETWEEN 33 AND 39 AND lng BETWEEN 124 AND 132
    GROUP BY stat_id
  `;
}

function qOutputThisRoute(hw) {
  const esc = hw.replace(/'/g, "''");
  return `
    SELECT ${OUTPUT_BUCKETS_SQL} AS bucket, COUNT(*) AS cnt
    FROM 'chargers.parquet' AS p
    WHERE ${HW_FILTER} AND addr LIKE '%${esc}%' AND output IS NOT NULL
    GROUP BY bucket ORDER BY bucket
  `;
}

function qOpsThisRoute(hw) {
  const esc = hw.replace(/'/g, "''");
  return `
    SELECT
      busi_id,
      ANY_VALUE(busi_nm) AS busi_nm,
      COUNT(*) AS chargers,
      COUNT(DISTINCT stat_id) AS stations
    FROM 'chargers.parquet' AS p
    WHERE ${HW_FILTER} AND addr LIKE '%${esc}%'
    GROUP BY busi_id
    ORDER BY chargers DESC
  `;
}

async function runQuery(conn, sql) {
  const result = await conn.query(sql);
  return JSON.parse(
    JSON.stringify(result.toArray(), (_, v) =>
      typeof v === "bigint" ? Number(v) : v,
    ),
  );
}

async function loadCodes() {
  const [busi, chgerType] = await Promise.all([
    fetch(BUSI_URL).then((r) => r.json()),
    fetch(CHGER_TYPE_URL).then((r) => r.json()),
  ]);
  return { busi, chgerType };
}

const shortHighway = (h) => (h || "").replace(/고속도로$/, "");

// 노선의 lat/lng 변화 폭 큰 축으로 정렬
function sortStationsByCorridor(stations) {
  if (stations.length < 2) return [...stations];
  const lats = stations.map((s) => s.lat);
  const lngs = stations.map((s) => s.lng);
  const latRange = Math.max(...lats) - Math.min(...lats);
  const lngRange = Math.max(...lngs) - Math.min(...lngs);
  return [...stations].sort((a, b) =>
    latRange >= lngRange ? a.lat - b.lat : a.lng - b.lng,
  );
}

function computeAdjacentDistances(sortedStations) {
  const pairs = [];
  for (let i = 1; i < sortedStations.length; i++) {
    const a = sortedStations[i - 1];
    const b = sortedStations[i];
    pairs.push({
      from: a,
      to: b,
      km: haversineKm(a.lat, a.lng, b.lat, b.lng),
    });
  }
  return pairs;
}

// ─── 렌더 ───

function renderKpi(stations, distances, overall) {
  const chargers = stations.reduce((s, r) => s + r.chargers, 0);
  const ops = new Set(stations.map((s) => s.busi_id)).size;
  const dcRatioSum = stations.reduce((s, r) => s + r.dc_ratio * r.chargers, 0);
  const dcRatio = dcRatioSum / Math.max(chargers, 1);
  const kwSum = stations.reduce(
    (s, r) => s + (r.avg_kw || 0) * r.chargers,
    0,
  );
  const avgKw = kwSum / Math.max(chargers, 1);
  const avgKm =
    distances.length > 0
      ? distances.reduce((s, p) => s + p.km, 0) / distances.length
      : 0;
  const maxKm =
    distances.length > 0 ? Math.max(...distances.map((d) => d.km)) : 0;

  $("kpi-stations").textContent = fmtInt(stations.length);
  $("kpi-chargers").textContent = fmtInt(chargers);
  $("kpi-avg-kw").textContent = fmtNum(avgKw, 1);
  const kwDiff = avgKw - (overall.avg_kw || 0);
  $("kpi-avg-kw-sub").textContent =
    `전체 ${fmtNum(overall.avg_kw, 1)} kW · ${kwDiff >= 0 ? "+" : ""}${fmtNum(kwDiff, 1)}`;
  $("kpi-dc").textContent = fmtPct(dcRatio, 1);
  const dcDiff = dcRatio - (overall.dc_ratio || 0);
  $("kpi-dc-sub").textContent =
    `전체 ${fmtPct(overall.dc_ratio, 1)} · ${dcDiff >= 0 ? "+" : ""}${fmtPct(dcDiff, 1)}`;
  $("kpi-spacing").textContent = fmtNum(avgKm, 1);
  $("kpi-spacing-sub").textContent =
    distances.length > 0
      ? `최대 ${fmtNum(maxKm, 1)} km · 인접 휴게소`
      : "—";
  $("kpi-operators").textContent = fmtInt(ops);
  $("kpi-operators-sub").textContent = `${stations.length}개 휴게소 분할`;
}

function renderInsights(hw, stations, distances, ops, overall, outputThis, outputAll) {
  const grid = $("insight-grid");
  grid.textContent = "";
  const ins = [];

  const chargers = stations.reduce((s, r) => s + r.chargers, 0);

  ins.push({
    color: "info",
    headline: fmtInt(chargers),
    title: `${shortHighway(hw)} 노선 전체 충전기`,
    body: `${stations.length}개 휴게소 / 운영자 ${new Set(stations.map((s) => s.busi_id)).size}곳. 노선 전체에 분산.`,
  });

  const kwSum = stations.reduce((s, r) => s + (r.avg_kw || 0) * r.chargers, 0);
  const avgKw = kwSum / Math.max(chargers, 1);
  const kwDiff = avgKw - (overall.avg_kw || 0);
  ins.push({
    color: kwDiff >= 10 ? "default" : kwDiff <= -10 ? "warn" : "purple",
    headline: (kwDiff >= 0 ? "+" : "") + fmtNum(kwDiff, 0) + " kW",
    title: kwDiff >= 0 ? "전체 평균 대비 우월" : "전체 평균 대비 낮음",
    body: `이 노선 ${fmtNum(avgKw, 1)} kW vs 전체 ${fmtNum(overall.avg_kw, 1)} kW. ${kwDiff >= 10 ? "초급속 비중이 높은 노선." : kwDiff <= -10 ? "구형 충전기 비율이 높을 가능성." : "고속도로 평균과 유사."}`,
  });

  if (distances.length > 0) {
    const longest = distances.reduce((a, b) => (b.km > a.km ? b : a));
    ins.push({
      color: longest.km > 60 ? "warn" : "default",
      headline: fmtNum(longest.km, 1) + " km",
      title: "가장 먼 무충전 구간",
      body: `${(longest.from.stat_nm || "").slice(0, 14)} → ${(longest.to.stat_nm || "").slice(0, 14)}. ${longest.km > 60 ? "EV 한 충전 사거리에 부담될 수 있음." : "EV 사거리 안에 안정적."}`,
    });
  }

  if (ops.length > 0) {
    const topOp = ops[0];
    const topShare = topOp.chargers / chargers;
    ins.push({
      color: "default",
      headline: fmtPct(topShare, 0),
      title: `${topOp.busi_nm || topOp.busi_id} 시장 점유 1위`,
      body: `${fmtInt(topOp.chargers)}대 / ${topOp.stations} 휴게소. 노선의 ${fmtPct(topShare, 1)} 차지.`,
    });
  }

  const outputThisTotal = outputThis.reduce((s, r) => s + r.cnt, 0);
  const outputAllTotal = outputAll.reduce((s, r) => s + r.cnt, 0);
  const fastThis =
    outputThis
      .filter((r) => r.bucket === "D_201to350" || r.bucket === "E_350plus")
      .reduce((s, r) => s + r.cnt, 0) / Math.max(outputThisTotal, 1);
  const fastAll =
    outputAll
      .filter((r) => r.bucket === "D_201to350" || r.bucket === "E_350plus")
      .reduce((s, r) => s + r.cnt, 0) / Math.max(outputAllTotal, 1);
  ins.push({
    color: fastThis > fastAll ? "default" : "purple",
    headline: fmtPct(fastThis, 1),
    title: "200+ kW 초급속 비중",
    body: `이 노선 ${fmtPct(fastThis, 1)} vs 고속도로 전체 ${fmtPct(fastAll, 1)}. ${fastThis > fastAll * 1.2 ? "초급속 인프라가 강한 노선." : fastThis < fastAll * 0.8 ? "초급속 상대적 부족." : "전체 평균 수준."}`,
  });

  for (const i of ins) {
    const card = makeEl(
      "div",
      "insight-card " + (i.color !== "default" ? i.color : ""),
    );
    card.append(
      makeEl("div", "insight-headline", i.headline),
      makeEl("div", "insight-title", i.title),
      makeEl("div", "insight-body", i.body),
    );
    grid.appendChild(card);
  }
}

function renderStations(sorted, codes) {
  const labels = sorted.map((s) => (s.stat_nm || s.stat_id).slice(0, 24));
  new Chart($("chart-stations").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "충전기 수",
        data: sorted.map((s) => s.chargers),
        backgroundColor: sorted.map((s) => {
          const kw = s.avg_kw || 0;
          if (kw >= 200) return C.primary;
          if (kw >= 100) return C.amber;
          if (kw >= 50) return C.info;
          return C.textDim;
        }),
        borderWidth: 0,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { beginAtZero: true, ticks: { callback: (v) => fmtInt(v) }, grid: { color: C.grid } },
        y: { grid: { display: false }, ticks: { autoSkip: false, font: { size: 11 } } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody: (ctx) => {
              const s = sorted[ctx[0].dataIndex];
              const op = codes.busi[s.busi_id] || s.busi_nm || s.busi_id;
              return [
                `평균 출력: ${fmtNum(s.avg_kw || 0, 1)} kW`,
                `DC 비율: ${fmtPct(s.dc_ratio, 1)}`,
                `운영자: ${op}`,
                `주소: ${(s.addr || "").slice(0, 40)}`,
              ];
            },
          },
        },
      },
    },
  });
}

function renderOutputCompare(thisRoute, overall) {
  const buckets = Object.keys(OUTPUT_LABELS);
  const total1 = thisRoute.reduce((s, r) => s + r.cnt, 0);
  const total2 = overall.reduce((s, r) => s + r.cnt, 0);
  const m1 = new Map(thisRoute.map((r) => [r.bucket, r.cnt]));
  const m2 = new Map(overall.map((r) => [r.bucket, r.cnt]));

  new Chart($("chart-output").getContext("2d"), {
    type: "bar",
    data: {
      labels: buckets.map((b) => OUTPUT_LABELS[b]),
      datasets: [
        {
          label: "이 노선 (%)",
          data: buckets.map((b) => ((m1.get(b) || 0) / Math.max(total1, 1)) * 100),
          backgroundColor: C.primary,
          borderWidth: 0,
        },
        {
          label: "고속도로 전체 (%)",
          data: buckets.map((b) => ((m2.get(b) || 0) / Math.max(total2, 1)) * 100),
          backgroundColor: C.textDim,
          borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, ticks: { callback: (v) => v + "%" }, grid: { color: C.grid } },
        x: { grid: { display: false } },
      },
      plugins: {
        legend: { labels: { color: C.text, boxWidth: 12 } },
      },
    },
  });
}

function renderOps(ops, codes) {
  const top = ops.slice(0, 8);
  const rest = ops.slice(8);
  const restSum = rest.reduce((s, r) => s + r.chargers, 0);
  const labels = top.map((r) => codes.busi[r.busi_id] || r.busi_nm || r.busi_id);
  const data = top.map((r) => r.chargers);
  if (restSum > 0) {
    labels.push("기타");
    data.push(restSum);
  }
  const total = data.reduce((a, b) => a + b, 0);

  new Chart($("chart-ops").getContext("2d"), {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: OP_PALETTE.slice(0, data.length),
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
            label: (ctx) =>
              `${ctx.label}: ${fmtInt(ctx.parsed)} (${fmtPct(ctx.parsed / total)})`,
          },
        },
      },
    },
  });
}

function renderSpacing(distances) {
  const buckets = [
    { label: "≤10 km", min: 0, max: 10 },
    { label: "11~20 km", min: 10, max: 20 },
    { label: "21~40 km", min: 20, max: 40 },
    { label: "41~60 km", min: 40, max: 60 },
    { label: "61~100 km", min: 60, max: 100 },
    { label: "100+ km", min: 100, max: Infinity },
  ];
  const counts = buckets.map((b) =>
    distances.filter((d) => d.km > b.min && d.km <= b.max).length,
  );
  const colors = buckets.map((b) =>
    b.min >= 60 ? C.danger : b.min >= 40 ? C.warn : C.primary,
  );

  new Chart($("chart-spacing").getContext("2d"), {
    type: "bar",
    data: {
      labels: buckets.map((b) => b.label),
      datasets: [{
        label: "인접 휴게소 쌍 수",
        data: counts,
        backgroundColor: colors,
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
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody: (ctx) => {
              const b = buckets[ctx[0].dataIndex];
              const ds = distances
                .filter((d) => d.km > b.min && d.km <= b.max)
                .sort((a, b) => b.km - a.km)
                .slice(0, 3);
              return ds.map(
                (d) =>
                  `${(d.from.stat_nm || "").slice(0, 12)} → ${(d.to.stat_nm || "").slice(0, 12)}: ${fmtNum(d.km, 1)} km`,
              );
            },
          },
        },
      },
    },
  });
}

// 차트 인스턴스 캐시 — 재렌더 시 destroy
const chartIds = [
  "chart-stations",
  "chart-output",
  "chart-ops",
  "chart-spacing",
];

function destroyCharts() {
  for (const id of chartIds) {
    const inst = Chart.getChart(id);
    if (inst) inst.destroy();
  }
}

// 노선 변경 시 모든 차트 재렌더
async function loadRoute(conn, hw, codes, overall, outputAll) {
  destroyCharts();
  $("page-title").textContent = `${shortHighway(hw)} — 노선 분석`;
  const subEl = $("page-subtitle");
  subEl.textContent = "";
  subEl.append(
    makeEl("code", null, "kind_detail = 'C001'"),
    document.createTextNode(` · ${hw}`),
  );

  const [stations, outputThis, ops] = await Promise.all([
    runQuery(conn, qStations(hw)),
    runQuery(conn, qOutputThisRoute(hw)),
    runQuery(conn, qOpsThisRoute(hw)),
  ]);

  if (stations.length === 0) {
    throw new Error(`${hw} 휴게소 0개. 데이터 확인 필요.`);
  }

  const sorted = sortStationsByCorridor(stations);
  const distances = computeAdjacentDistances(sorted);

  renderKpi(stations, distances, overall);
  renderInsights(hw, stations, distances, ops, overall, outputThis, outputAll);
  renderStations(sorted, codes);
  renderOutputCompare(outputThis, outputAll);
  renderOps(ops, codes);
  renderSpacing(distances);

  // URL ?hw= 갱신
  const url = new URL(location.href);
  url.searchParams.set("hw", hw);
  history.replaceState(null, "", url);

  $("header-snapshot").textContent =
    `${shortHighway(hw)} · ${fmtInt(stations.length)} 휴게소`;
  $("row-count").textContent =
    fmtInt(stations.reduce((s, r) => s + r.chargers, 0)) + " chargers";
}

async function main() {
  try {
    if (location.protocol === "file:") {
      throw new Error("file:// 로 열렸습니다. python -m http.server 8000 후 접속.");
    }
    if (typeof Chart === "undefined") {
      throw new Error("Chart.js 로드 실패.");
    }

    const db = await initDuckDB();
    const conn = await db.connect();

    setStatus("노선 list + 전체 평균 로드…");
    const [codes, hwList, [overall], outputAll] = await Promise.all([
      loadCodes(),
      runQuery(conn, Q_HW_LIST),
      runQuery(conn, Q_OVERALL),
      runQuery(conn, Q_OUTPUT_OVERALL),
    ]);

    // 드롭다운 채우기
    const sel = $("hw-select");
    sel.textContent = "";
    sel.disabled = false;
    for (const r of hwList) {
      const opt = document.createElement("option");
      opt.value = r.hw;
      opt.textContent = `${r.hw} (${r.stations}개 휴게소 · ${r.chargers}대)`;
      sel.appendChild(opt);
    }

    const params = new URLSearchParams(location.search);
    const initialHw = params.get("hw") || hwList[0].hw;
    if ([...sel.options].some((o) => o.value === initialHw)) {
      sel.value = initialHw;
    }

    $("snapshot-date").textContent =
      `노선 ${hwList.length}개 · 전체 평균 ${fmtNum(overall.avg_kw, 1)} kW`;

    setStatus(`${sel.value} 분석 중…`);
    await loadRoute(conn, sel.value, codes, overall, outputAll);
    revealAll();

    sel.addEventListener("change", async (e) => {
      const hw = e.target.value;
      setStatus(`${hw} 분석 중…`);
      $("status").hidden = false;
      try {
        await loadRoute(conn, hw, codes, overall, outputAll);
        $("status").hidden = true;
      } catch (err) {
        showError(err);
      }
    });
  } catch (e) {
    showError(e);
  }
}

main();
