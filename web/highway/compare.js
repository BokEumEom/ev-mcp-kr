// 고속도로 비교 분석 — 운영자/노선 2~4 entity 동시 비교 + 자동 인사이트.

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";

const PARQUET_URL = "/scratch/chargers_snapshot.parquet";
const BUSI_URL = "/src/ev_mcp/codes/busi_id.json";
const DC_CODES = ["01", "03", "04", "05", "06", "08", "09", "10"];

const $ = (id) => document.getElementById(id);
const setStatus = (t) => ($("status-text").textContent = t);

function showError(err) {
  $("status").hidden = true;
  $("error-panel").hidden = false;
  $("error-message").textContent = err?.stack || err?.message || String(err);
  console.error(err);
}

function revealAll() {
  $("status").hidden = true;
  for (const id of ["insights", "overview-title", "card-radar", "card-kpi-table", "drilldown-title", "card-dist-1", "card-dist-2", "card-dist-3", "header-badge"]) {
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
  text: "#ecf0f4", textDim: "#8b96a4", grid: "#232c38",
  primary: "#6ee7b7", warn: "#fbbf24", danger: "#f87171",
  info: "#7dd3fc", purple: "#c4b5fd", amber: "#fcd34d",
  lime: "#bef264", rose: "#fda4af",
};
Chart.defaults.color = C.textDim;
Chart.defaults.borderColor = C.grid;
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", "Pretendard", "Noto Sans KR", system-ui, sans-serif';
Chart.defaults.plugins.legend.labels.color = C.text;

const PALETTE = [C.primary, C.info, C.warn, C.purple, C.rose, C.amber];
const PALETTE_DIM = PALETTE.map((c) => c + "33");

async function initDuckDB() {
  setStatus("분석 엔진 준비 중…");
  const bundles = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(bundles);
  const workerUrl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }));
  const worker = new Worker(workerUrl);
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger("WARNING"), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  setStatus("충전소 데이터 불러오는 중…");
  const res = await fetch(PARQUET_URL);
  if (!res.ok) throw new Error(`Parquet fetch 실패: ${res.status}`);
  const buf = new Uint8Array(await res.arrayBuffer());
  await db.registerFileBuffer("chargers.parquet", buf);
  return db;
}

const HW_FILTER = `del_yn = 'N' AND kind_detail = 'C001'`;
const DC_IN = DC_CODES.map((c) => `'${c}'`).join(",");

// ─── 쿼리 ───

// 운영자 entity list (드롭다운용)
const Q_OPERATORS = `
  SELECT busi_id AS id, ANY_VALUE(busi_nm) AS nm, COUNT(*) AS n,
    MIN(year) AS first_year
  FROM 'chargers.parquet' AS p
  WHERE ${HW_FILTER}
  GROUP BY busi_id ORDER BY n DESC
`;

// 노선 entity list
const Q_HIGHWAYS = `
  SELECT regexp_extract(addr, '([가-힣]+고속도로)', 1) AS id,
    regexp_extract(addr, '([가-힣]+고속도로)', 1) AS nm,
    COUNT(*) AS n
  FROM 'chargers.parquet' AS p
  WHERE ${HW_FILTER}
  GROUP BY id HAVING id != '' AND n >= 5
  ORDER BY n DESC
`;

// 선택된 entity 들의 KPI (운영자 모드)
function qOpKpis(ids) {
  const idList = ids.map((i) => `'${i.replace(/'/g, "''")}'`).join(",");
  return `
    SELECT
      busi_id AS id,
      ANY_VALUE(busi_nm) AS nm,
      COUNT(*) AS chargers,
      COUNT(DISTINCT stat_id) AS stations,
      COUNT(DISTINCT zcode) AS sido_count,
      AVG(TRY_CAST(output AS DOUBLE)) AS avg_kw,
      AVG(CASE WHEN chger_type IN (${DC_IN}) THEN 1.0 ELSE 0.0 END) AS dc_ratio,
      AVG(CASE WHEN stat IN ('1','4','5') THEN 1.0 ELSE 0.0 END) AS downtime,
      AVG(CASE WHEN stat = '9' THEN 1.0 ELSE 0.0 END) AS unmonitored,
      AVG(CASE WHEN stat = '2' THEN 1.0 ELSE 0.0 END) AS available
    FROM 'chargers.parquet' AS p
    WHERE ${HW_FILTER} AND busi_id IN (${idList})
    GROUP BY busi_id
  `;
}

// 선택된 노선들의 KPI
function qHwKpis(ids) {
  // 노선별 LIKE 조건 모음. id 가 곧 "경부고속도로" 등 키워드.
  const clauses = ids.map((id) => {
    const esc = id.replace(/'/g, "''");
    return `WHEN addr LIKE '%${esc}%' THEN '${esc}'`;
  }).join(" ");
  return `
    SELECT
      hw AS id,
      hw AS nm,
      COUNT(*) AS chargers,
      COUNT(DISTINCT stat_id) AS stations,
      COUNT(DISTINCT busi_id) AS operator_count,
      AVG(TRY_CAST(output AS DOUBLE)) AS avg_kw,
      AVG(CASE WHEN chger_type IN (${DC_IN}) THEN 1.0 ELSE 0.0 END) AS dc_ratio,
      AVG(CASE WHEN stat IN ('1','4','5') THEN 1.0 ELSE 0.0 END) AS downtime,
      AVG(CASE WHEN stat = '9' THEN 1.0 ELSE 0.0 END) AS unmonitored,
      AVG(CASE WHEN stat = '2' THEN 1.0 ELSE 0.0 END) AS available
    FROM (
      SELECT *, CASE ${clauses} ELSE NULL END AS hw
      FROM 'chargers.parquet' AS p
      WHERE ${HW_FILTER}
    )
    WHERE hw IS NOT NULL
    GROUP BY hw
  `;
}

// 운영자 비교 시: 각 운영자의 노선 점유
function qOpRoutes(ids) {
  const idList = ids.map((i) => `'${i.replace(/'/g, "''")}'`).join(",");
  return `
    SELECT busi_id AS entity,
      regexp_extract(addr, '([가-힣]+고속도로)', 1) AS hw,
      COUNT(*) AS cnt
    FROM 'chargers.parquet' AS p
    WHERE ${HW_FILTER} AND busi_id IN (${idList})
    GROUP BY busi_id, hw
    HAVING hw != ''
  `;
}

// 노선 비교 시: 각 노선의 운영자 점유
function qHwOps(ids) {
  const clauses = ids.map((id) => `WHEN addr LIKE '%${id.replace(/'/g, "''")}%' THEN '${id.replace(/'/g, "''")}'`).join(" ");
  return `
    SELECT hw AS entity, busi_id AS op, ANY_VALUE(busi_nm) AS op_nm, COUNT(*) AS cnt
    FROM (
      SELECT *, CASE ${clauses} ELSE NULL END AS hw
      FROM 'chargers.parquet' AS p
      WHERE ${HW_FILTER}
    )
    WHERE hw IS NOT NULL
    GROUP BY hw, busi_id
  `;
}

// 출력 분포 (entity 별, 운영자/노선 공통)
function qOutputDist(type, ids) {
  const cond = type === "operator"
    ? `busi_id IN (${ids.map((i) => `'${i.replace(/'/g, "''")}'`).join(",")})`
    : `addr ~ '(${ids.map((i) => i.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})'`;
  const entityExpr = type === "operator"
    ? `busi_id`
    : `(${ids.map((id) => `CASE WHEN addr LIKE '%${id.replace(/'/g, "''")}%' THEN '${id.replace(/'/g, "''")}' ELSE NULL END`).join(" || ")})`;

  // 단순화: TYPE 별 분리
  if (type === "operator") {
    const idList = ids.map((i) => `'${i.replace(/'/g, "''")}'`).join(",");
    return `
      SELECT busi_id AS entity,
        CASE
          WHEN TRY_CAST(output AS DOUBLE) <= 50  THEN 'A_le50'
          WHEN TRY_CAST(output AS DOUBLE) <= 100 THEN 'B_51to100'
          WHEN TRY_CAST(output AS DOUBLE) <= 200 THEN 'C_101to200'
          WHEN TRY_CAST(output AS DOUBLE) <= 350 THEN 'D_201to350'
          ELSE 'E_350plus'
        END AS bucket,
        COUNT(*) AS cnt
      FROM 'chargers.parquet' AS p
      WHERE ${HW_FILTER} AND busi_id IN (${idList}) AND output IS NOT NULL
      GROUP BY busi_id, bucket
    `;
  } else {
    const clauses = ids.map((id) => `WHEN addr LIKE '%${id.replace(/'/g, "''")}%' THEN '${id.replace(/'/g, "''")}'`).join(" ");
    return `
      SELECT hw AS entity,
        CASE
          WHEN TRY_CAST(output AS DOUBLE) <= 50  THEN 'A_le50'
          WHEN TRY_CAST(output AS DOUBLE) <= 100 THEN 'B_51to100'
          WHEN TRY_CAST(output AS DOUBLE) <= 200 THEN 'C_101to200'
          WHEN TRY_CAST(output AS DOUBLE) <= 350 THEN 'D_201to350'
          ELSE 'E_350plus'
        END AS bucket,
        COUNT(*) AS cnt
      FROM (
        SELECT *, CASE ${clauses} ELSE NULL END AS hw
        FROM 'chargers.parquet' AS p
        WHERE ${HW_FILTER} AND output IS NOT NULL
      )
      WHERE hw IS NOT NULL
      GROUP BY hw, bucket
    `;
  }
}

const OUTPUT_LABELS = { A_le50: "≤50", B_51to100: "51~100", C_101to200: "101~200", D_201to350: "201~350", E_350plus: "350+" };

async function runQuery(conn, sql) {
  const result = await conn.query(sql);
  return JSON.parse(JSON.stringify(result.toArray(), (_, v) => typeof v === "bigint" ? Number(v) : v));
}

// ─── State ───

const state = {
  conn: null,
  type: "operator",           // operator | highway
  selected: [],               // [{id, nm}]
  entityList: { operator: [], highway: [] },
  busiNames: {},              // codes.busi
  charts: {},
};

// ─── Entity picker ───

function renderChips() {
  const wrap = $("entity-chips");
  wrap.textContent = "";
  for (const e of state.selected) {
    const chip = makeEl("div", "chip", e.nm);
    const x = makeEl("button", "chip-x", "×");
    x.addEventListener("click", () => {
      state.selected = state.selected.filter((s) => s.id !== e.id);
      renderChips();
      refreshDropdown();
      updateUrl();
      if (state.selected.length >= 2) rerender();
    });
    chip.appendChild(x);
    wrap.appendChild(chip);
  }
}

function refreshDropdown() {
  const sel = $("entity-select");
  const selectedIds = new Set(state.selected.map((s) => s.id));
  const remaining = state.entityList[state.type].filter((e) => !selectedIds.has(e.id));
  sel.textContent = "";
  sel.appendChild(makeEl("option", null, "+ 추가"));
  for (const e of remaining) {
    const opt = makeEl("option", null, `${e.nm} (${e.n}대)`);
    opt.value = e.id;
    sel.appendChild(opt);
  }
}

function addEntity(id) {
  if (state.selected.length >= 4) {
    alert("최대 4개까지 비교 가능합니다.");
    return;
  }
  const found = state.entityList[state.type].find((e) => e.id === id);
  if (!found) return;
  if (state.selected.some((s) => s.id === id)) return;
  state.selected.push(found);
  renderChips();
  refreshDropdown();
  updateUrl();
  if (state.selected.length >= 2) rerender();
}

function applyPreset(presetName) {
  const list = state.entityList[state.type];
  let ids = [];
  if (state.type === "operator") {
    if (presetName === "top4") {
      ids = list.slice(0, 4).map((e) => e.id);
    } else if (presetName === "newcomers") {
      ids = list.filter((e) => Number(e.first_year) >= 2023).slice(0, 4).map((e) => e.id);
    } else if (presetName === "incumbents") {
      ids = list.filter((e) => Number(e.first_year) <= 2020).slice(0, 4).map((e) => e.id);
    }
  } else {
    if (presetName === "top4") ids = list.slice(0, 4).map((e) => e.id);
    else if (presetName === "newcomers") ids = list.slice(8, 12).map((e) => e.id);
    else if (presetName === "incumbents") ids = list.slice(0, 4).map((e) => e.id);
  }
  state.selected = ids.map((id) => list.find((e) => e.id === id)).filter(Boolean);
  renderChips();
  refreshDropdown();
  updateUrl();
  rerender();
}

function switchType(newType) {
  if (newType === state.type) return;
  state.type = newType;
  state.selected = [];
  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.type === newType);
  });
  renderChips();
  refreshDropdown();
  // 기본 top 4 자동 선택
  applyPreset("top4");
}

function updateUrl() {
  const url = new URL(location.href);
  url.searchParams.set("type", state.type);
  url.searchParams.set("entities", state.selected.map((s) => s.id).join(","));
  history.replaceState(null, "", url);
}

// ─── 차트 destroy 유틸 ───
function destroyAll() {
  for (const id of ["chart-radar", "chart-dist-1", "chart-dist-2", "chart-dist-3"]) {
    const inst = Chart.getChart(id);
    if (inst) inst.destroy();
  }
}

// ─── KPI 정의 ───

// radar: true 인 비율/질적 지표만 radar 축에 쓴다 (규모 지표는 표에만).
// radarMax: 절대 정규화 기준 — 비율은 1, 출력은 350kW 만점. 그룹 내 상대가 아니라
// 절대 기준이라 "비교 대상 중 최악이 만점"이 되는 왜곡이 없다.
const KPI_DEFS_OP = [
  { key: "chargers", label: "충전기 수", fmt: fmtInt, higherBetter: true },
  { key: "stations", label: "휴게소 수", fmt: fmtInt, higherBetter: true },
  { key: "sido_count", label: "진입 시도", fmt: fmtInt, higherBetter: true },
  { key: "avg_kw", label: "평균 출력 (kW)", fmt: (v) => fmtNum(v, 1), higherBetter: true, radar: true, radarMax: 350 },
  { key: "dc_ratio", label: "DC 비율", fmt: (v) => fmtPct(v, 1), higherBetter: true, radar: true, radarMax: 1 },
  { key: "downtime", label: "비가동률", fmt: (v) => fmtPct(v, 1), higherBetter: false, radar: true, radarMax: 1 },
  { key: "unmonitored", label: "미연동률", fmt: (v) => fmtPct(v, 1), higherBetter: false, radar: true, radarMax: 1 },
];

const KPI_DEFS_HW = [
  { key: "chargers", label: "충전기 수", fmt: fmtInt, higherBetter: true },
  { key: "stations", label: "휴게소 수", fmt: fmtInt, higherBetter: true },
  { key: "operator_count", label: "운영자 다양성", fmt: fmtInt, higherBetter: true },
  { key: "avg_kw", label: "평균 출력 (kW)", fmt: (v) => fmtNum(v, 1), higherBetter: true, radar: true, radarMax: 350 },
  { key: "dc_ratio", label: "DC 비율", fmt: (v) => fmtPct(v, 1), higherBetter: true, radar: true, radarMax: 1 },
  { key: "downtime", label: "비가동률", fmt: (v) => fmtPct(v, 1), higherBetter: false, radar: true, radarMax: 1 },
  { key: "unmonitored", label: "미연동률", fmt: (v) => fmtPct(v, 1), higherBetter: false, radar: true, radarMax: 1 },
];

// ─── 자동 인사이트 generator ───

function generateInsights(kpiData, type) {
  const defs = type === "operator" ? KPI_DEFS_OP : KPI_DEFS_HW;
  const insights = [];

  // 1. 각 KPI 별 최고/최저 차이 계산
  const gaps = [];
  for (const def of defs) {
    const vals = kpiData.map((d) => ({ entity: d, val: Number(d[def.key]) || 0 }));
    const sorted = [...vals].sort((a, b) => b.val - a.val);
    const best = def.higherBetter ? sorted[0] : sorted[sorted.length - 1];
    const worst = def.higherBetter ? sorted[sorted.length - 1] : sorted[0];
    const ratio = best.val / Math.max(worst.val, 0.0001);
    gaps.push({ def, best, worst, ratio, gap: Math.abs(best.val - worst.val) });
  }

  // 격차 큰 순으로 정렬
  gaps.sort((a, b) => b.ratio - a.ratio);

  // top 5 인사이트
  const colors = ["info", "default", "purple", "warn", "default"];
  for (let i = 0; i < Math.min(5, gaps.length); i++) {
    const g = gaps[i];
    const bestNm = g.best.entity.nm;
    const worstNm = g.worst.entity.nm;
    insights.push({
      color: colors[i],
      headline: g.def.fmt(g.best.val),
      title: `${g.def.label} 1위 — ${bestNm}`,
      body: `${bestNm}: ${g.def.fmt(g.best.val)} · 꼴찌 ${worstNm}: ${g.def.fmt(g.worst.val)} · 격차 ${fmtNum(g.ratio, 1)}×`,
    });
  }

  // 모순 발견 — 규모 1위인데 출력 꼴찌 같은 패턴
  const sizeRank = [...kpiData].sort((a, b) => b.chargers - a.chargers);
  const kwRank = [...kpiData].sort((a, b) => (b.avg_kw || 0) - (a.avg_kw || 0));
  if (sizeRank[0].id !== kwRank[0].id && kpiData.length >= 2) {
    insights.push({
      color: "purple",
      headline: "⚡ 모순",
      title: `규모 1위 ≠ 출력 1위`,
      body: `규모: ${sizeRank[0].nm} (${fmtInt(sizeRank[0].chargers)}대) · 출력: ${kwRank[0].nm} (${fmtNum(kwRank[0].avg_kw, 1)}kW). 큰 운영자가 더 빠르지 않다.`,
    });
  }

  return insights.slice(0, 5);
}

function renderInsights(kpiData, type) {
  const grid = $("insight-grid");
  grid.textContent = "";
  const insights = generateInsights(kpiData, type);
  for (const ins of insights) {
    const card = makeEl("div", "insight-card " + (ins.color !== "default" ? ins.color : ""));
    card.append(
      makeEl("div", "insight-headline", ins.headline),
      makeEl("div", "insight-title", ins.title),
      makeEl("div", "insight-body", ins.body),
    );
    grid.appendChild(card);
  }
}

// ─── Radar Chart ───

// 절대 기준 정규화 — 그룹 내 최댓값이 아니라 radarMax(비율=1, 출력=350kW) 기준.
// 바깥쪽일수록 우수: 낮을수록 좋은 지표(비가동·미연동)는 반전.
function radarNorm(def, v) {
  const pct = Math.min(v / def.radarMax, 1) * 100;
  return def.higherBetter ? pct : 100 - pct;
}

function renderRadar(kpiData, type) {
  // 규모 지표는 제외하고 비율/질적 지표만 (규모 큰 entity 가 시각적으로 우세해
  // 보이는 왜곡 차단). 규모는 아래 KPI 표에서 본다.
  const axes = (type === "operator" ? KPI_DEFS_OP : KPI_DEFS_HW).filter((d) => d.radar);

  const datasets = kpiData.map((d, i) => ({
    label: d.nm,
    data: axes.map((def) => radarNorm(def, Number(d[def.key]) || 0)),
    raw: axes.map((def) => def.fmt(Number(d[def.key]) || 0)),
    borderColor: PALETTE[i],
    backgroundColor: PALETTE[i] + "33",
    borderWidth: 2,
    pointBackgroundColor: PALETTE[i],
  }));

  new Chart($("chart-radar").getContext("2d"), {
    type: "radar",
    data: { labels: axes.map((a) => a.label), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        r: {
          beginAtZero: true,
          max: 100,
          grid: { color: C.grid },
          angleLines: { color: C.grid },
          pointLabels: { color: C.text, font: { size: 11 } },
          ticks: { color: C.textDim, backdropColor: "transparent", stepSize: 25 },
        },
      },
      plugins: {
        legend: { position: "bottom", labels: { color: C.text, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            // 정규화 점수(0~100)가 아니라 실제 원본값을 보여준다.
            label: (ctx) =>
              `${ctx.dataset.label}: ${ctx.dataset.raw[ctx.dataIndex]} (${fmtNum(ctx.parsed.r, 0)}점)`,
          },
        },
      },
    },
  });
}

// ─── KPI 표 ───

function renderKpiTable(kpiData, type) {
  const defs = type === "operator" ? KPI_DEFS_OP : KPI_DEFS_HW;

  const thead = $("compare-thead-row");
  thead.textContent = "";
  thead.appendChild(makeEl("th", null, "지표"));
  for (const d of kpiData) {
    thead.appendChild(makeEl("th", "num", d.nm));
  }

  const tbody = $("compare-tbody");
  tbody.textContent = "";

  for (const def of defs) {
    const tr = document.createElement("tr");
    tr.appendChild(makeEl("td", "op-name", def.label));
    const vals = kpiData.map((d) => Number(d[def.key]) || 0);
    const bestVal = def.higherBetter ? Math.max(...vals) : Math.min(...vals);
    const worstVal = def.higherBetter ? Math.min(...vals) : Math.max(...vals);
    for (let i = 0; i < kpiData.length; i++) {
      const v = vals[i];
      let cls = "num";
      if (v === bestVal && bestVal !== worstVal) cls += " cell-best";
      else if (v === worstVal && bestVal !== worstVal) cls += " cell-worst";
      tr.appendChild(makeEl("td", cls, def.fmt(v)));
    }
    tbody.appendChild(tr);
  }
}

// ─── Drill-down 차트들 ───

function renderDistOutput(distData, kpiData) {
  $("dist-1-title").textContent = "출력 분포 비교";
  $("dist-1-desc").textContent = "5 버킷별 충전기 수 (entity 별 grouped bar).";

  const buckets = ["A_le50", "B_51to100", "C_101to200", "D_201to350", "E_350plus"];
  const labels = buckets.map((b) => OUTPUT_LABELS[b] + " kW");

  const datasets = kpiData.map((d, i) => {
    const data = buckets.map((b) => {
      const r = distData.find((x) => x.entity === d.id && x.bucket === b);
      return r ? r.cnt : 0;
    });
    return {
      label: d.nm, data,
      backgroundColor: PALETTE[i],
      borderWidth: 0,
    };
  });

  new Chart($("chart-dist-1").getContext("2d"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, ticks: { callback: (v) => fmtInt(v) }, grid: { color: C.grid } },
        x: { grid: { display: false } },
      },
      plugins: { legend: { labels: { color: C.text, boxWidth: 12 } } },
    },
  });
}

function renderDistRoutes(routeData, kpiData) {
  // 운영자 비교 모드 — 각 운영자의 노선 분포
  $("dist-2-title").textContent = "노선 점유 비교";
  $("dist-2-desc").textContent = "각 운영자가 어떤 노선에 강한지 (top 10 노선).";

  const hwTotals = new Map();
  for (const r of routeData) {
    hwTotals.set(r.hw, (hwTotals.get(r.hw) || 0) + r.cnt);
  }
  const topHws = [...hwTotals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10).map(([h]) => h);

  const datasets = kpiData.map((d, i) => {
    const data = topHws.map((hw) => {
      const r = routeData.find((x) => x.entity === d.id && x.hw === hw);
      return r ? r.cnt : 0;
    });
    return { label: d.nm, data, backgroundColor: PALETTE[i], borderWidth: 0 };
  });

  new Chart($("chart-dist-2").getContext("2d"), {
    type: "bar",
    data: { labels: topHws.map((h) => h.replace(/고속도로$/, "")), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      scales: {
        x: { beginAtZero: true, stacked: true, ticks: { callback: (v) => fmtInt(v) }, grid: { color: C.grid } },
        y: { stacked: true, grid: { display: false } },
      },
      plugins: { legend: { labels: { color: C.text, boxWidth: 12 } } },
    },
  });
}

function renderDistOps(opsData, kpiData) {
  // 노선 비교 모드 — 각 노선의 운영자 분포
  $("dist-2-title").textContent = "운영자 점유 비교";
  $("dist-2-desc").textContent = "각 노선의 운영자 시장 분할.";

  const opTotals = new Map();
  for (const r of opsData) {
    if (!opTotals.has(r.op)) opTotals.set(r.op, { nm: r.op_nm || r.op, total: 0 });
    opTotals.get(r.op).total += r.cnt;
  }
  const topOps = [...opTotals.entries()].sort((a, b) => b[1].total - a[1].total).slice(0, 8);

  const datasets = topOps.map(([opId, info], i) => {
    const data = kpiData.map((d) => {
      const r = opsData.find((x) => x.entity === d.id && x.op === opId);
      return r ? r.cnt : 0;
    });
    return {
      label: info.nm, data,
      backgroundColor: PALETTE[i % PALETTE.length], borderWidth: 0,
    };
  });

  new Chart($("chart-dist-2").getContext("2d"), {
    type: "bar",
    data: { labels: kpiData.map((d) => d.nm.replace(/고속도로$/, "")), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      scales: {
        x: { beginAtZero: true, stacked: true, ticks: { callback: (v) => fmtInt(v) }, grid: { color: C.grid } },
        y: { stacked: true, grid: { display: false } },
      },
      plugins: { legend: { labels: { color: C.text, boxWidth: 12 } } },
    },
  });
}

function renderDistKpiBar(kpiData, type) {
  $("dist-3-title").textContent = "주요 KPI 막대 비교";
  $("dist-3-desc").textContent = "5 핵심 지표를 grouped bar 로. 같은 지표끼리 막대 길이 비교.";
  const defs = (type === "operator" ? KPI_DEFS_OP : KPI_DEFS_HW).slice(0, 5);
  // 각 KPI 를 0~100 정규화 (radar 와 같은 정규화)
  const maxVals = defs.map((def) =>
    Math.max(...kpiData.map((d) => Number(d[def.key]) || 0))
  );

  const datasets = kpiData.map((d, i) => ({
    label: d.nm,
    data: defs.map((def, j) => {
      const v = Number(d[def.key]) || 0;
      const maxV = maxVals[j];
      const norm = maxV > 0 ? (v / maxV) * 100 : 0;
      return def.higherBetter ? norm : 100 - norm;
    }),
    backgroundColor: PALETTE[i],
    borderWidth: 0,
  }));

  new Chart($("chart-dist-3").getContext("2d"), {
    type: "bar",
    data: { labels: defs.map((d) => d.label), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, max: 100, ticks: { callback: (v) => v }, grid: { color: C.grid } },
        x: { grid: { display: false } },
      },
      plugins: {
        legend: { labels: { color: C.text, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            afterBody: (ctx) => ["100 = 비교 대상 중 최고"],
          },
        },
      },
    },
  });
}

// ─── 메인 re-render ───

async function rerender() {
  if (state.selected.length < 2) {
    setStatus("2개 이상 entity 선택 시 비교 시작");
    $("status").hidden = false;
    return;
  }
  destroyAll();
  setStatus(`${state.selected.length}개 ${state.type === "operator" ? "운영자" : "노선"} 비교 중…`);
  $("status").hidden = false;

  try {
    const ids = state.selected.map((s) => s.id);
    let kpiData, distOutput, drillData;

    if (state.type === "operator") {
      [kpiData, distOutput, drillData] = await Promise.all([
        runQuery(state.conn, qOpKpis(ids)),
        runQuery(state.conn, qOutputDist("operator", ids)),
        runQuery(state.conn, qOpRoutes(ids)),
      ]);
      // 순서 유지 (kpi 결과를 selected 순으로)
      kpiData = ids.map((id) => kpiData.find((k) => k.id === id)).filter(Boolean);
      // nm fallback (코드 테이블)
      for (const d of kpiData) d.nm = state.busiNames[d.id] || d.nm;
    } else {
      [kpiData, distOutput, drillData] = await Promise.all([
        runQuery(state.conn, qHwKpis(ids)),
        runQuery(state.conn, qOutputDist("highway", ids)),
        runQuery(state.conn, qHwOps(ids)),
      ]);
      kpiData = ids.map((id) => kpiData.find((k) => k.id === id)).filter(Boolean);
    }

    if (kpiData.length < 2) {
      throw new Error("데이터 부족 — 선택한 entity 의 데이터가 충분치 않음.");
    }

    renderInsights(kpiData, state.type);
    renderRadar(kpiData, state.type);
    renderKpiTable(kpiData, state.type);
    renderDistOutput(distOutput, kpiData);
    if (state.type === "operator") {
      renderDistRoutes(drillData, kpiData);
    } else {
      renderDistOps(drillData, kpiData);
    }
    renderDistKpiBar(kpiData, state.type);

    $("header-snapshot").textContent =
      `${kpiData.length}개 ${state.type === "operator" ? "운영자" : "노선"} 비교`;
    revealAll();
  } catch (e) {
    showError(e);
  }
}

// ─── 메인 ───

async function main() {
  try {
    if (location.protocol === "file:") {
      throw new Error("file:// 로 열렸습니다. python -m http.server 8000 후 접속.");
    }
    if (typeof Chart === "undefined") {
      throw new Error("Chart.js 로드 실패.");
    }

    const db = await initDuckDB();
    state.conn = await db.connect();

    setStatus("비교 데이터 불러오는 중…");
    const [opList, hwList, busiCodes] = await Promise.all([
      runQuery(state.conn, Q_OPERATORS),
      runQuery(state.conn, Q_HIGHWAYS),
      fetch(BUSI_URL).then((r) => r.json()),
    ]);

    state.busiNames = busiCodes;
    // 운영자 nm 에 코드 테이블 라벨 적용
    state.entityList.operator = opList.map((o) => ({
      ...o, nm: busiCodes[o.id] || o.nm || o.id,
    }));
    state.entityList.highway = hwList;

    // type 토글
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchType(btn.dataset.type));
    });
    // entity add
    $("entity-select").addEventListener("change", (e) => {
      if (e.target.value) {
        addEntity(e.target.value);
        e.target.value = "";
      }
    });
    // preset
    document.querySelectorAll(".preset-btn").forEach((btn) => {
      btn.addEventListener("click", () => applyPreset(btn.dataset.preset));
    });

    // URL state 복원
    const params = new URLSearchParams(location.search);
    const urlType = params.get("type");
    const urlEntities = params.get("entities");
    if (urlType === "highway") {
      state.type = "highway";
      document.querySelectorAll(".tab-btn").forEach((b) => {
        b.classList.toggle("is-active", b.dataset.type === "highway");
      });
    }
    if (urlEntities) {
      const ids = urlEntities.split(",").filter(Boolean);
      state.selected = ids.map((id) => state.entityList[state.type].find((e) => e.id === id)).filter(Boolean);
    } else {
      // 기본 top 4
      state.selected = state.entityList[state.type].slice(0, 4);
    }

    renderChips();
    refreshDropdown();
    await rerender();
  } catch (e) {
    showError(e);
  }
}

main();
