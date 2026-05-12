// 고속도로 휴게소 상세 페이지 — drill-down.
// URL ?id=STAT_ID 로 휴게소 선택. 검색 input 또는 deep link 양쪽 지원.

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";

const PARQUET_URL = "/scratch/chargers_snapshot.parquet";
const BUSI_URL = "/src/ev_mcp/codes/busi_id.json";
const CHGER_TYPE_URL = "/src/ev_mcp/codes/charger_type.json";
const STAT_URL = "/src/ev_mcp/codes/stat.json";
const SIDO_URL = "/src/ev_mcp/codes/sido.json";
const KIND_URL = "/src/ev_mcp/codes/kind_detail.json";

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
    "info-card",
    "kpi-grid",
    "dist-title",
    "card-status",
    "card-output",
    "card-map",
    "chargers-title",
    "card-chargers-table",
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
};

Chart.defaults.color = C.textDim;
Chart.defaults.borderColor = C.grid;
Chart.defaults.font.family =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", "Pretendard", "Noto Sans KR", system-ui, sans-serif';
Chart.defaults.plugins.legend.labels.color = C.text;

const STAT_COLOR = {
  "1": C.danger,
  "2": C.primary,
  "3": C.info,
  "4": C.warn,
  "5": C.amber,
  "6": C.purple,
  "9": C.textDim,
  "0": C.textDim,
};

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

const Q_STATION_LIST = `
  SELECT
    stat_id,
    ANY_VALUE(stat_nm) AS stat_nm,
    regexp_extract(ANY_VALUE(addr), '([가-힣]+고속도로)', 1) AS highway,
    COUNT(*) AS n
  FROM 'chargers.parquet' AS p
  WHERE ${HW_FILTER}
  GROUP BY stat_id
  ORDER BY stat_nm
`;

function qStationDetail(statId) {
  const esc = statId.replace(/'/g, "''");
  return `
    SELECT
      ANY_VALUE(stat_nm) AS stat_nm,
      ANY_VALUE(addr) AS addr,
      ANY_VALUE(addr_detail) AS addr_detail,
      ANY_VALUE(location) AS location,
      ANY_VALUE(lat) AS lat,
      ANY_VALUE(lng) AS lng,
      ANY_VALUE(zcode) AS zcode,
      ANY_VALUE(zscode) AS zscode,
      ANY_VALUE(busi_id) AS busi_id,
      ANY_VALUE(busi_nm) AS busi_nm,
      ANY_VALUE(busi_call) AS busi_call,
      ANY_VALUE(use_time) AS use_time,
      ANY_VALUE(parking_free) AS parking_free,
      ANY_VALUE(kind) AS kind,
      ANY_VALUE(kind_detail) AS kind_detail,
      ANY_VALUE(year) AS year,
      ANY_VALUE(floor_num) AS floor_num,
      ANY_VALUE(floor_type) AS floor_type,
      ANY_VALUE(note) AS note,
      regexp_extract(ANY_VALUE(addr), '([가-힣]+고속도로)', 1) AS highway,
      COUNT(*) AS chargers,
      AVG(TRY_CAST(output AS DOUBLE)) AS avg_kw,
      AVG(CASE WHEN chger_type IN (${DC_IN}) THEN 1.0 ELSE 0.0 END) AS dc_ratio,
      SUM(CASE WHEN stat = '2' THEN 1 ELSE 0 END) AS available,
      SUM(CASE WHEN stat = '3' THEN 1 ELSE 0 END) AS charging,
      MAX(last_tsdt) AS latest_tsdt
    FROM 'chargers.parquet' AS p
    WHERE ${HW_FILTER} AND stat_id = '${esc}'
  `;
}

function qChargers(statId) {
  const esc = statId.replace(/'/g, "''");
  return `
    SELECT chger_id, chger_type, output, stat, method, last_tsdt, last_tedt
    FROM 'chargers.parquet' AS p
    WHERE ${HW_FILTER} AND stat_id = '${esc}'
    ORDER BY chger_id
  `;
}

function qNeighbors(highway, lat, lng) {
  const esc = highway.replace(/'/g, "''");
  return `
    SELECT stat_id, ANY_VALUE(stat_nm) AS stat_nm,
      ANY_VALUE(lat) AS lat, ANY_VALUE(lng) AS lng,
      COUNT(*) AS chargers
    FROM 'chargers.parquet' AS p
    WHERE ${HW_FILTER} AND addr LIKE '%${esc}%'
      AND lat BETWEEN ${lat - 1.0} AND ${lat + 1.0}
      AND lng BETWEEN ${lng - 1.0} AND ${lng + 1.0}
    GROUP BY stat_id LIMIT 30
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
  const [busi, chgerType, stat, sido, kind] = await Promise.all([
    fetch(BUSI_URL).then((r) => r.json()),
    fetch(CHGER_TYPE_URL).then((r) => r.json()),
    fetch(STAT_URL).then((r) => r.json()),
    fetch(SIDO_URL).then((r) => r.json()),
    fetch(KIND_URL).then((r) => r.json()),
  ]);
  return { busi, chgerType, stat, sido, kind };
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// ─── 렌더 ───

function renderInfo(d, codes) {
  $("page-title").textContent = d.stat_nm || d.stat_id || "휴게소";
  const subEl = $("page-subtitle");
  subEl.textContent = "";
  subEl.append(
    makeEl("code", null, `stat_id = ${d.stat_id || "—"}`),
    document.createTextNode(d.highway ? ` · ${d.highway}` : ""),
  );

  $("info-name").textContent = d.stat_nm || d.stat_id || "—";
  const addr = [d.addr, d.addr_detail].filter(Boolean).join(" ");
  $("info-addr").textContent = addr || "—";

  $("info-operator").textContent =
    (codes.busi[d.busi_id] || d.busi_nm || d.busi_id || "—") +
    (d.busi_id ? ` (${d.busi_id})` : "");
  $("info-call").textContent = d.busi_call || "—";
  $("info-usetime").textContent = d.use_time || "—";
  $("info-parking").textContent =
    d.parking_free === "Y" ? "무료" : d.parking_free === "N" ? "유료" : "—";
  $("info-year").textContent = d.year || "—";
  $("info-highway").textContent =
    (d.highway || "—") +
    (d.kind_detail ? ` · ${codes.kind[d.kind_detail] || d.kind_detail}` : "");
}

function renderKpi(d) {
  const total = Number(d.chargers);
  $("kpi-chargers").textContent = fmtInt(total);
  $("kpi-avg-kw").textContent = fmtNum(d.avg_kw || 0, 1);
  $("kpi-dc").textContent = fmtPct(d.dc_ratio || 0, 1);
  $("kpi-dc-sub").textContent =
    fmtInt(Math.round((d.dc_ratio || 0) * total)) + "대 / " + fmtInt(total);
  $("kpi-available").textContent = fmtInt(d.available);
  $("kpi-available-sub").textContent =
    fmtPct(d.available / Math.max(total, 1), 1) + " · 즉시 사용";
  $("kpi-charging").textContent = fmtInt(d.charging);

  if (d.latest_tsdt) {
    const dt = String(d.latest_tsdt).slice(0, 16).replace("T", " ");
    $("kpi-latest").textContent = dt;
    const last = new Date(d.latest_tsdt);
    const now = new Date();
    const hoursAgo = (now - last) / (1000 * 60 * 60);
    let ago;
    if (hoursAgo < 1) ago = "1시간 이내";
    else if (hoursAgo < 24) ago = `${Math.round(hoursAgo)}시간 전`;
    else ago = `${Math.round(hoursAgo / 24)}일 전`;
    $("kpi-latest-sub").textContent = ago;
  } else {
    $("kpi-latest").textContent = "—";
    $("kpi-latest-sub").textContent = "기록 없음";
  }

  $("header-snapshot").textContent =
    `${fmtInt(total)}대 충전기 · ${fmtInt(d.charging)}대 사용중`;
  $("row-count").textContent = fmtInt(total) + " chargers";
  $("snapshot-date").textContent = d.stat_id || "—";
}

function renderStatusChart(chargers, codes) {
  const byStat = new Map();
  for (const c of chargers) {
    byStat.set(c.stat, (byStat.get(c.stat) || 0) + 1);
  }
  const entries = [...byStat.entries()].sort((a, b) => b[1] - a[1]);

  new Chart($("chart-status").getContext("2d"), {
    type: "doughnut",
    data: {
      labels: entries.map(([s]) => `${codes.stat[s] || s} (${s})`),
      datasets: [{
        data: entries.map(([, n]) => n),
        backgroundColor: entries.map(([s]) => STAT_COLOR[s] || C.textDim),
        borderColor: "#131820",
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right", labels: { color: C.text, boxWidth: 12 } },
      },
    },
  });
}

function renderOutputChart(chargers) {
  const byKw = new Map();
  for (const c of chargers) {
    const kw = c.output || "?";
    byKw.set(kw, (byKw.get(kw) || 0) + 1);
  }
  const entries = [...byKw.entries()].sort((a, b) => {
    const na = Number(a[0]) || 0;
    const nb = Number(b[0]) || 0;
    return na - nb;
  });

  new Chart($("chart-output").getContext("2d"), {
    type: "bar",
    data: {
      labels: entries.map(([kw]) => kw + " kW"),
      datasets: [{
        label: "충전기 수",
        data: entries.map(([, n]) => n),
        backgroundColor: entries.map(([kw]) => {
          const n = Number(kw) || 0;
          if (n >= 200) return C.primary;
          if (n >= 100) return C.amber;
          if (n >= 50) return C.info;
          return C.textDim;
        }),
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1 }, grid: { color: C.grid } },
        x: { grid: { display: false } },
      },
      plugins: { legend: { display: false } },
    },
  });
}

let map = null;
function renderMap(d, neighbors) {
  const mapEl = $("map-mini");
  if (map) {
    map.remove();
    map = null;
  }
  // safe clear (avoid innerHTML)
  mapEl.replaceChildren();

  if (d.lat == null || d.lng == null) {
    mapEl.textContent = "좌표 정보 없음";
    return;
  }

  map = L.map(mapEl, {
    center: [d.lat, d.lng],
    zoom: 11,
    attributionControl: false,
  });
  L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    { subdomains: "abcd", maxZoom: 19 },
  ).addTo(map);

  for (const n of neighbors) {
    if (n.stat_id === d.stat_id) continue;
    if (n.lat == null || n.lng == null) continue;
    const marker = L.circleMarker([n.lat, n.lng], {
      radius: 5,
      color: C.textDim,
      fillColor: C.textDim,
      fillOpacity: 0.6,
      weight: 1,
    });
    const popupHtml =
      `<div class="popup-title">${escapeHtml(n.stat_nm || n.stat_id)}</div>` +
      `<div class="popup-meta">${fmtInt(n.chargers)}대 충전기</div>` +
      `<div><a href="./station.html?id=${encodeURIComponent(n.stat_id)}">상세 →</a></div>`;
    marker.bindPopup(popupHtml, { className: "highway-popup" });
    marker.bindTooltip(n.stat_nm || n.stat_id, { direction: "top" });
    marker.addTo(map);
  }

  L.circleMarker([d.lat, d.lng], {
    radius: 12,
    color: C.primary,
    fillColor: C.primary,
    fillOpacity: 0.75,
    weight: 2,
  })
    .bindPopup(
      `<div class="popup-title">${escapeHtml(d.stat_nm || "")}</div>` +
        `<div class="popup-meta">현재 위치</div>`,
      { className: "highway-popup" },
    )
    .addTo(map);

  if (neighbors.length > 1) {
    const pts = neighbors
      .filter((n) => n.lat != null && n.lng != null)
      .map((n) => [n.lat, n.lng]);
    if (pts.length > 0) {
      map.fitBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 12 });
    }
  }
}

function renderChargersTable(chargers, codes, sortKey = "id") {
  const sorted = [...chargers].sort((a, b) => {
    switch (sortKey) {
      case "kw-desc":
        return (Number(b.output) || 0) - (Number(a.output) || 0);
      case "kw-asc":
        return (Number(a.output) || 0) - (Number(b.output) || 0);
      case "recent":
        return String(b.last_tsdt || "").localeCompare(String(a.last_tsdt || ""));
      case "id":
      default:
        return String(a.chger_id).localeCompare(String(b.chger_id));
    }
  });

  const tbody = $("chargers-tbody");
  tbody.textContent = "";

  for (const c of sorted) {
    const tr = document.createElement("tr");
    const statLabel = `${codes.stat[c.stat] || "—"} (${c.stat || "—"})`;
    const typeLabel = codes.chgerType[c.chger_type] || c.chger_type || "—";

    const fmtDt = (s) => {
      if (!s) return "—";
      return String(s).slice(0, 16).replace("T", " ");
    };

    tr.append(
      makeEl("td", "op-name", c.chger_id || "—"),
      makeEl("td", null, typeLabel),
      makeEl("td", "num", c.output ? c.output + " kW" : "—"),
      makeEl(
        "td",
        c.stat === "2" || c.stat === "3" ? "" : "warn-text",
        statLabel,
      ),
      makeEl("td", null, c.method || "—"),
      makeEl("td", "mono-cell", fmtDt(c.last_tsdt)),
      makeEl("td", "mono-cell", fmtDt(c.last_tedt)),
    );
    tbody.appendChild(tr);
  }

  const titleH3 = $("card-chargers-table").querySelector("h3");
  if (titleH3) titleH3.textContent = `충전기 ${chargers.length}대 — 모든 상세`;
}

// ─── 메인 ───

const state = {
  conn: null,
  codes: null,
  stationList: [],
  currentStatId: null,
  chargers: [],
  chargerSortKey: "id",
};

async function loadStation(statId) {
  setStatus(`${statId} 로딩…`);
  $("status").hidden = false;

  const [[detail], chargers] = await Promise.all([
    runQuery(state.conn, qStationDetail(statId)),
    runQuery(state.conn, qChargers(statId)),
  ]);

  if (!detail || !detail.stat_nm) {
    throw new Error(`휴게소 not found: ${statId}. URL ?id= 값 확인.`);
  }
  detail.stat_id = statId;

  const neighbors = detail.highway
    ? await runQuery(state.conn, qNeighbors(detail.highway, detail.lat, detail.lng))
    : [];

  state.currentStatId = statId;
  state.chargers = chargers;

  renderInfo(detail, state.codes);
  renderKpi(detail);
  renderStatusChart(chargers, state.codes);
  renderOutputChart(chargers);
  renderMap(detail, neighbors);
  renderChargersTable(chargers, state.codes, state.chargerSortKey);

  const url = new URL(location.href);
  url.searchParams.set("id", statId);
  history.replaceState(null, "", url);

  $("station-input").value = detail.stat_nm || statId;

  revealAll();
  $("status").hidden = true;
}

function destroyCharts() {
  for (const id of ["chart-status", "chart-output"]) {
    const inst = Chart.getChart(id);
    if (inst) inst.destroy();
  }
}

async function main() {
  try {
    if (location.protocol === "file:") {
      throw new Error("file:// 로 열렸습니다. python -m http.server 8000 후 접속.");
    }
    if (typeof Chart === "undefined" || typeof L === "undefined") {
      throw new Error("Chart.js 또는 Leaflet 로드 실패.");
    }

    const db = await initDuckDB();
    state.conn = await db.connect();

    setStatus("코드 + 휴게소 list 로드…");
    const [codes, stationList] = await Promise.all([
      loadCodes(),
      runQuery(state.conn, Q_STATION_LIST),
    ]);
    state.codes = codes;
    state.stationList = stationList;

    const dl = $("station-options");
    dl.textContent = "";
    for (const s of stationList) {
      const opt = document.createElement("option");
      opt.value = s.stat_nm;
      opt.textContent = `${s.highway || "?"} · ${s.n}대`;
      dl.appendChild(opt);
    }

    const params = new URLSearchParams(location.search);
    let initial = params.get("id");
    if (!initial) {
      const biggest = stationList.reduce((a, b) => (b.n > a.n ? b : a));
      initial = biggest.stat_id;
    }

    await loadStation(initial);

    $("station-input").addEventListener("change", async (e) => {
      const v = e.target.value;
      const match = stationList.find((s) => s.stat_nm === v);
      if (!match) {
        setStatus(`"${v}" 매치되는 휴게소 없음. 다시 입력하세요.`);
        return;
      }
      if (match.stat_id === state.currentStatId) return;
      try {
        destroyCharts();
        await loadStation(match.stat_id);
      } catch (err) {
        showError(err);
      }
    });

    const sortSel = $("charger-sort");
    if (sortSel) {
      sortSel.addEventListener("change", (e) => {
        state.chargerSortKey = e.target.value;
        renderChargersTable(state.chargers, state.codes, state.chargerSortKey);
      });
    }
  } catch (e) {
    showError(e);
  }
}

main();
