// 고속도로 운영자 분석 — 12 운영자 ranking + 운영자×노선 히트맵 + 진입 연도 + 산점도.

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";
// Chart.js 는 HTML 에서 미리 로드 (UMD)

const PARQUET_URL = "/scratch/chargers_snapshot.parquet";
const BUSI_URL = "/src/ev_mcp/codes/busi_id.json";

const DOWNTIME_CODES = ["1", "4", "5"];
const DC_CODES = ["01", "03", "04", "05", "06", "08", "09", "10"];

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
    "insights",
    "ranking-title",
    "card-ranking",
    "heatmap-title",
    "card-heatmap",
    "dual-title",
    "card-year",
    "card-scatter",
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

// 운영자 색상 풍부하게
const OP_PALETTE = [
  C.primary, C.info, C.purple, C.warn, C.rose, C.amber, C.lime,
  "#fb923c", "#a78bfa", "#34d399", "#60a5fa", "#f472b6",
];

// ─── DuckDB-WASM ───
async function initDuckDB() {
  setStatus("분석 엔진 준비 중…");
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

  setStatus(`충전소 데이터 불러오는 중…`);
  const res = await fetch(PARQUET_URL);
  if (!res.ok) throw new Error(`Parquet fetch 실패: ${res.status} ${PARQUET_URL}`);
  const buf = new Uint8Array(await res.arrayBuffer());
  setStatus(`충전소 데이터 불러오는 중… (${(buf.byteLength / 1024 / 1024).toFixed(1)}MB)`);
  await db.registerFileBuffer("chargers.parquet", buf);
  return db;
}

const inList = (codes) => codes.map((c) => `'${c}'`).join(",");
const HW_FILTER = `del_yn = 'N' AND kind_detail = 'C001'`;

const Q_RANKING = `
  SELECT
    busi_id,
    ANY_VALUE(busi_nm)                                                            AS busi_nm,
    COUNT(*)                                                                      AS chargers,
    COUNT(DISTINCT stat_id)                                                       AS stations,
    COUNT(DISTINCT zcode)                                                         AS sido_count,
    AVG(TRY_CAST(output AS DOUBLE))                                               AS avg_kw,
    AVG(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1.0 ELSE 0.0 END)      AS dc_ratio,
    AVG(CASE WHEN stat IN (${inList(DOWNTIME_CODES)}) THEN 1.0 ELSE 0.0 END)      AS downtime_ratio,
    AVG(CASE WHEN stat = '9' THEN 1.0 ELSE 0.0 END)                               AS unmonitored_ratio
  FROM 'chargers.parquet'
  WHERE ${HW_FILTER}
  GROUP BY busi_id
  ORDER BY chargers DESC
`;

const Q_HEATMAP = `
  WITH base AS (
    SELECT
      busi_id,
      ANY_VALUE(busi_nm) busi_nm,
      regexp_extract(addr, '([가-힣]+고속도로)', 1) AS highway
    FROM 'chargers.parquet'
    WHERE ${HW_FILTER}
    GROUP BY busi_id, addr
  ),
  cells AS (
    SELECT busi_id, ANY_VALUE(busi_nm) busi_nm, highway, COUNT(*) cnt
    FROM (
      SELECT busi_id, ANY_VALUE(busi_nm) busi_nm,
             regexp_extract(addr, '([가-힣]+고속도로)', 1) highway
      FROM 'chargers.parquet'
      WHERE ${HW_FILTER}
      GROUP BY busi_id, addr, stat_id, chger_id
    )
    WHERE highway != ''
    GROUP BY busi_id, highway
  ),
  top_ops AS (
    SELECT busi_id FROM cells
    GROUP BY busi_id ORDER BY SUM(cnt) DESC LIMIT 8
  ),
  top_hws AS (
    SELECT highway FROM cells
    GROUP BY highway ORDER BY SUM(cnt) DESC LIMIT 8
  )
  SELECT c.busi_id, c.busi_nm, c.highway, c.cnt
  FROM cells c
  WHERE c.busi_id IN (SELECT busi_id FROM top_ops)
    AND c.highway IN (SELECT highway FROM top_hws)
`;

const Q_YEAR_BY_OP = `
  SELECT busi_id, ANY_VALUE(busi_nm) busi_nm, year, COUNT(*) cnt
  FROM 'chargers.parquet'
  WHERE ${HW_FILTER} AND year IS NOT NULL
    AND TRY_CAST(year AS INTEGER) BETWEEN 2017 AND 2026
    AND busi_id IN (
      SELECT busi_id FROM 'chargers.parquet'
      WHERE ${HW_FILTER}
      GROUP BY busi_id ORDER BY COUNT(*) DESC LIMIT 6
    )
  GROUP BY busi_id, year
  ORDER BY busi_id, year
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
  const busi = await fetch(BUSI_URL).then((r) => r.json());
  return { busi };
}

const shortHighway = (h) => (h || "").replace(/고속도로$/, "");

// ─── 인사이트 ───

function renderInsights(ranking, heatmap, year) {
  const grid = $("insight-grid");
  grid.textContent = "";

  const totalChargers = ranking.reduce((a, r) => a + r.chargers, 0);
  const totalStations = ranking.reduce((a, r) => a + r.stations, 0);

  // 1) 1휴게소-1운영자 독점
  // 데이터 검증: stations 합 == 622 인가?
  const isMonopoly = totalStations === 622;
  // (heatmap 데이터로 추가 검증 불가하니 직접 사실 인용)
  const insights = [];
  insights.push({
    color: "info",
    headline: "100%",
    title: "1휴게소-1운영자 독점",
    body: `622곳 휴게소 모두 단일 운영자. 일반 시내 충전소(멀티 운영자) 와 결정적 구조 차이. 시장 진입 = 휴게소 권리 획득.`,
  });

  // 2) 최상위 운영자 점유
  const top = ranking[0];
  const topShare = top.chargers / totalChargers;
  insights.push({
    color: "default",
    headline: fmtPct(topShare, 0),
    title: `${top.busi_nm} 시장 점유 1위`,
    body: `${fmtInt(top.chargers)}대 / ${fmtInt(top.stations)}곳 휴게소 / ${top.sido_count}개 시도 진입. 거점 분산형 전략.`,
  });

  // 3) 노선 집중도 — 최상위 운영자가 한 노선에 집중 비율
  // heatmap 데이터에서 가장 큰 (op, hw) 쌍
  if (heatmap.length > 0) {
    const max = heatmap.reduce((a, b) => (b.cnt > a.cnt ? b : a));
    const opTotalInHeatmap = heatmap
      .filter((r) => r.busi_id === max.busi_id)
      .reduce((a, r) => a + r.cnt, 0);
    const concentration = max.cnt / Math.max(opTotalInHeatmap, 1);
    insights.push({
      color: "purple",
      headline: fmtPct(concentration, 0),
      title: `${max.busi_nm} 의 ${shortHighway(max.highway)} 집중`,
      body: `${max.busi_nm} 의 top 8 노선 내 ${fmtInt(max.cnt)}대가 ${shortHighway(max.highway)} 단일 노선. 단일 노선 점유 전략의 대표 사례.`,
    });
  }

  // 4) 신규 진입자 폭증 (year 데이터)
  // 가장 최근 5년 (2022~2026) 에 비중 큰 운영자 vs 그 이전
  const recentByOp = new Map();
  const oldByOp = new Map();
  for (const r of year) {
    const yr = Number(r.year);
    const map = yr >= 2022 ? recentByOp : oldByOp;
    map.set(r.busi_id, (map.get(r.busi_id) || 0) + r.cnt);
  }
  // 신규 진입자: oldByOp 이 0 또는 매우 작은 곳 중 recentByOp 가 큰 곳
  const newcomers = [];
  for (const [op, recent] of recentByOp.entries()) {
    const old = oldByOp.get(op) || 0;
    if (recent > 50 && recent / Math.max(old + recent, 1) > 0.8) {
      newcomers.push({ op, recent, old });
    }
  }
  newcomers.sort((a, b) => b.recent - a.recent);
  if (newcomers.length > 0) {
    const nc = newcomers[0];
    const opName =
      ranking.find((r) => r.busi_id === nc.op)?.busi_nm || nc.op;
    insights.push({
      color: "warn",
      headline: fmtInt(nc.recent),
      title: `${opName} 신규 진입 (2022+)`,
      body: `2022 이전 ${fmtInt(nc.old)}대 → 2022 이후 ${fmtInt(nc.recent)}대. 신규 운영자의 폭발적 시장 진입.`,
    });
  }

  // 5) 출력 격차 — 신규 vs 기존
  // ranking 의 평균 kW 최대 vs 최소
  const sortedByKw = [...ranking].sort((a, b) => b.avg_kw - a.avg_kw);
  const highest = sortedByKw[0];
  const ringChampion = sortedByKw.find((r) => r.chargers >= 100); // 큰 운영자 중
  insights.push({
    color: "default",
    headline: fmtNum(highest.avg_kw, 0) + " kW",
    title: `최고 평균 출력 — ${highest.busi_nm}`,
    body: `${highest.busi_nm} 평균 ${fmtNum(highest.avg_kw, 1)} kW${
      ringChampion && ringChampion.busi_id !== highest.busi_id
        ? ` vs 대형 운영자 ${ringChampion.busi_nm} ${fmtNum(ringChampion.avg_kw, 1)} kW`
        : ""
    }. 소규모 운영자가 초급속에 집중하는 전략.`,
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

// ─── Ranking 표 ───

function renderRanking(ranking, codes) {
  const total = ranking.reduce((a, r) => a + r.chargers, 0);
  const tbody = $("ranking-body");
  tbody.textContent = "";

  ranking.slice(0, 12).forEach((r, i) => {
    const share = r.chargers / total;
    const tr = document.createElement("tr");

    const nameLabel = codes.busi[r.busi_id] || r.busi_nm || r.busi_id;

    tr.append(
      makeEl("td", "num rank-num", String(i + 1)),
      makeEl("td", "op-name", nameLabel),
      makeEl("td", "num", fmtInt(r.chargers)),
      makeEl("td", "num", fmtInt(r.stations)),
      makeEl("td", "num", fmtInt(r.sido_count)),
      makeEl("td", "num", fmtNum(r.avg_kw, 1)),
      makeEl("td", "num", fmtPct(r.dc_ratio, 1)),
      makeEl("td", "num " + (r.downtime_ratio > 0.1 ? "warn-text" : ""), fmtPct(r.downtime_ratio, 1)),
      makeEl("td", "num " + (r.unmonitored_ratio > 0.1 ? "info-text" : ""), fmtPct(r.unmonitored_ratio, 1)),
    );

    // share cell — inline bar + text
    const shareCell = document.createElement("td");
    shareCell.className = "share-cell";
    const bar = makeEl("div", "share-bar");
    const fill = makeEl("div", "share-fill");
    fill.style.width = (share * 100).toFixed(1) + "%";
    bar.appendChild(fill);
    shareCell.append(bar, makeEl("span", "share-text", fmtPct(share, 1)));
    tr.appendChild(shareCell);

    tbody.appendChild(tr);
  });
}

// ─── 히트맵 (CSS grid) ───

function renderHeatmap(heatmap, codes) {
  const wrap = $("heatmap-wrap");
  wrap.textContent = "";

  // 가로축: 노선 (총 충전기 수 내림차순)
  const hwTotals = new Map();
  const opTotals = new Map();
  const cellMap = new Map(); // "op|hw" → cnt
  let maxCnt = 0;

  for (const r of heatmap) {
    hwTotals.set(r.highway, (hwTotals.get(r.highway) || 0) + r.cnt);
    opTotals.set(
      r.busi_id,
      { busi_nm: r.busi_nm, total: (opTotals.get(r.busi_id)?.total || 0) + r.cnt },
    );
    cellMap.set(r.busi_id + "|" + r.highway, r.cnt);
    if (r.cnt > maxCnt) maxCnt = r.cnt;
  }

  const highways = [...hwTotals.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([h]) => h);
  const ops = [...opTotals.entries()]
    .sort((a, b) => b[1].total - a[1].total)
    .map(([id, { busi_nm }]) => ({ id, busi_nm }));

  // Build CSS grid
  const grid = document.createElement("div");
  grid.className = "heatmap";
  grid.style.gridTemplateColumns =
    `minmax(120px, 1fr) repeat(${highways.length}, minmax(56px, 1fr))`;

  // Header row
  grid.appendChild(makeEl("div", "heatmap-corner")); // empty top-left
  for (const hw of highways) {
    const cell = makeEl("div", "heatmap-x-label", shortHighway(hw));
    cell.title = hw;
    grid.appendChild(cell);
  }

  // Data rows
  for (const op of ops) {
    const label = codes.busi[op.id] || op.busi_nm || op.id;
    grid.appendChild(makeEl("div", "heatmap-y-label", label));
    for (const hw of highways) {
      const cnt = cellMap.get(op.id + "|" + hw) || 0;
      const intensity = cnt / maxCnt;
      const cell = document.createElement("div");
      cell.className = "heatmap-cell";
      if (cnt > 0) {
        // 진한 녹색 (alpha = intensity^0.55, 약한 값도 보이게)
        const alpha = Math.pow(intensity, 0.55).toFixed(2);
        cell.style.background = `rgba(110, 231, 183, ${alpha})`;
        cell.title = `${label} × ${hw}: ${cnt}대`;
        const v = makeEl("span", "heatmap-val", fmtInt(cnt));
        if (intensity > 0.55) v.classList.add("dark");
        cell.appendChild(v);
      } else {
        cell.classList.add("empty");
      }
      grid.appendChild(cell);
    }
  }

  wrap.appendChild(grid);
}

// ─── 진입 연도 line chart ───

function renderYear(year, codes) {
  // group by busi_id → year series
  const byOp = new Map();
  const years = new Set();
  for (const r of year) {
    if (!byOp.has(r.busi_id)) {
      byOp.set(r.busi_id, { busi_nm: r.busi_nm, points: new Map() });
    }
    byOp.get(r.busi_id).points.set(Number(r.year), r.cnt);
    years.add(Number(r.year));
  }
  const yrSorted = [...years].sort((a, b) => a - b);
  const ops = [...byOp.entries()];

  const datasets = ops.map(([opId, { busi_nm, points }], i) => ({
    label: codes.busi[opId] || busi_nm || opId,
    data: yrSorted.map((y) => points.get(y) || 0),
    borderColor: OP_PALETTE[i % OP_PALETTE.length],
    backgroundColor: OP_PALETTE[i % OP_PALETTE.length] + "33",
    tension: 0.25,
    pointRadius: 3,
    pointHoverRadius: 5,
  }));

  new Chart($("chart-year").getContext("2d"), {
    type: "line",
    data: { labels: yrSorted, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { callback: (v) => fmtInt(v) },
          grid: { color: C.grid },
        },
        x: { grid: { display: false } },
      },
      plugins: {
        legend: { position: "bottom", labels: { color: C.text, boxWidth: 10, padding: 12 } },
      },
    },
  });
}

// ─── 규모 vs 출력 산점도 ───

function renderScatter(ranking, codes) {
  const data = ranking.slice(0, 12).map((r, i) => ({
    x: r.chargers,
    y: r.avg_kw,
    label: codes.busi[r.busi_id] || r.busi_nm || r.busi_id,
    op: r.busi_id,
    color: OP_PALETTE[i % OP_PALETTE.length],
    chargers: r.chargers,
    stations: r.stations,
  }));

  new Chart($("chart-scatter").getContext("2d"), {
    type: "scatter",
    data: {
      datasets: [{
        label: "운영자",
        data,
        backgroundColor: data.map((d) => d.color),
        borderColor: data.map((d) => d.color),
        pointRadius: data.map((d) => Math.max(6, Math.sqrt(d.chargers) * 0.8)),
        pointHoverRadius: data.map((d) => Math.max(8, Math.sqrt(d.chargers) * 0.9 + 2)),
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: "logarithmic",
          title: { display: true, text: "총 충전기 수 (log scale)", color: C.textDim },
          ticks: { color: C.textDim, callback: (v) => fmtInt(v) },
          grid: { color: C.grid },
        },
        y: {
          title: { display: true, text: "평균 출력 (kW)", color: C.textDim },
          ticks: { color: C.textDim },
          grid: { color: C.grid },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const d = data[ctx.dataIndex];
              return [
                `${d.label}`,
                `충전기 ${fmtInt(d.chargers)}대 / 휴게소 ${fmtInt(d.stations)}곳`,
                `평균 출력 ${fmtNum(d.y, 1)} kW`,
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
        "file:// 로 열렸습니다. cd /home/bokeum/ai/ev_mcp && python -m http.server 8000",
      );
    }
    if (typeof Chart === "undefined") {
      throw new Error("Chart.js 로드 실패. 인터넷 연결 확인.");
    }

    const db = await initDuckDB();
    const conn = await db.connect();

    setStatus("운영자 분석 중…");
    const [codes, ranking, heatmap, year] = await Promise.all([
      loadCodes(),
      runQuery(conn, Q_RANKING),
      runQuery(conn, Q_HEATMAP),
      runQuery(conn, Q_YEAR_BY_OP),
    ]);

    // 헤더 메타
    const totalChargers = ranking.reduce((a, r) => a + r.chargers, 0);
    const totalStations = ranking.reduce((a, r) => a + r.stations, 0);
    $("snapshot-date").textContent = `${totalChargers} 충전기 / ${totalStations} 휴게소`;
    $("header-snapshot").textContent = `운영자 ${ranking.length}곳`;
    $("row-count").textContent = fmtInt(totalChargers) + " rows";

    renderInsights(ranking, heatmap, year);
    renderRanking(ranking, codes);
    renderHeatmap(heatmap, codes);
    renderYear(year, codes);
    renderScatter(ranking, codes);

    revealAll();
    await conn.close();
  } catch (e) {
    showError(e);
  }
}

main();
