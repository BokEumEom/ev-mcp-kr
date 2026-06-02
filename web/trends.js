// ev-mcp 시계열 분석 — 여러 날짜 스냅샷을 DuckDB-WASM 으로 union 해 추세 분석.
// Phase 11 (snapshot_diff / inventory_trend) 의 web 시각화.

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";
import "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js";

// 프로젝트 루트 기준 절대 경로 (루트에서 python -m http.server 실행 전제)
const MANIFEST_URL = "/scratch/web_snapshots/manifest.json";
const SNAPSHOT_BASE = "/scratch/web_snapshots";

const DOWNTIME_CODES = ["1", "4", "5"];
const UNMONITORED_CODE = "9";
const AVAILABLE_CODE = "2";
const DC_CODES = ["01", "03", "04", "05", "06", "08", "09", "10"];
const inList = (codes) => codes.map((c) => `'${c}'`).join(",");

// ── UI 헬퍼 ──
const $ = (id) => document.getElementById(id);
const setStatus = (t) => ($("status-text").textContent = t);
function showError(err) {
  $("status").hidden = true;
  $("error-panel").hidden = false;
  $("error-message").textContent = err?.stack || err?.message || String(err);
  console.error(err);
}
const fmtInt = (n) => Number(n).toLocaleString("ko-KR");
const fmtPct = (p, d = 1) => (Number(p) * 100).toFixed(d) + "%";
const fmtSigned = (n) => (n >= 0 ? "+" : "") + fmtInt(n);
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
};
Chart.defaults.color = C.textDim;
Chart.defaults.borderColor = C.grid;
Chart.defaults.font.family =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", system-ui, sans-serif';
Chart.defaults.plugins.legend.labels.color = C.text;

// ── DuckDB-WASM 초기화 + 다중 스냅샷 등록 ──
async function initDuckDB() {
  setStatus("분석 엔진 준비 중…");
  const bundles = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(bundles);
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }),
  );
  const worker = new Worker(workerUrl);
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger("WARNING"), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);
  $("duckdb-version").textContent = "v" + (await db.getVersion());
  return db;
}

async function loadManifest() {
  const res = await fetch(MANIFEST_URL);
  if (!res.ok) {
    throw new Error(
      `manifest fetch 실패: ${res.status} ${MANIFEST_URL}\n` +
        "scripts/synthesize_snapshots.py 를 실행해 시계열 스냅샷을 만드세요.\n" +
        "(또는 실제 스냅샷이 며칠 쌓이면 동일 페이지가 진짜 데이터로 동작)",
    );
  }
  return res.json();
}

async function registerSnapshots(db, dates) {
  for (let i = 0; i < dates.length; i++) {
    const d = dates[i];
    setStatus(`충전소 데이터 불러오는 중… (${i + 1}/${dates.length})`);
    const res = await fetch(`${SNAPSHOT_BASE}/chargers_${d}.parquet`);
    if (!res.ok) throw new Error(`스냅샷 fetch 실패: ${d} (${res.status})`);
    const buf = new Uint8Array(await res.arrayBuffer());
    await db.registerFileBuffer(`s_${d}.parquet`, buf);
  }
  const conn = await db.connect();
  const fileList = dates.map((d) => `'s_${d}.parquet'`).join(", ");
  await conn.query(
    `CREATE VIEW v_all AS SELECT * FROM read_parquet([${fileList}])`,
  );
  return conn;
}

async function runQuery(conn, sql) {
  const result = await conn.query(sql);
  return JSON.parse(
    JSON.stringify(result.toArray(), (_, v) => (typeof v === "bigint" ? Number(v) : v)),
  );
}

// ── 쿼리 ──
const Q_TREND = `
  SELECT
    CAST(snapshot_date AS VARCHAR) AS d,
    COUNT(*) FILTER (WHERE del_yn = 'N') AS total,
    COUNT(*) FILTER (WHERE del_yn = 'N' AND chger_type IN (${inList(DC_CODES)})) AS dc,
    COUNT(*) FILTER (WHERE del_yn = 'N' AND stat = '${AVAILABLE_CODE}') AS available,
    COUNT(DISTINCT busi_id) FILTER (WHERE del_yn = 'N') AS operators
  FROM v_all
  GROUP BY snapshot_date
  ORDER BY snapshot_date
`;

const Q_HEALTH = `
  SELECT
    CAST(snapshot_date AS VARCHAR) AS d,
    AVG(CASE WHEN stat IN (${inList(DOWNTIME_CODES)}) THEN 1.0 ELSE 0.0 END) AS downtime,
    AVG(CASE WHEN stat = '${UNMONITORED_CODE}' THEN 1.0 ELSE 0.0 END) AS unmonitored
  FROM v_all
  WHERE del_yn = 'N'
  GROUP BY snapshot_date
  ORDER BY snapshot_date
`;

function qDiff(from, to) {
  return `
    WITH f AS (
      SELECT stat_id, chger_id, stat FROM v_all
      WHERE CAST(snapshot_date AS VARCHAR) = '${from}' AND del_yn = 'N'
    ),
    t AS (
      SELECT stat_id, chger_id, stat FROM v_all
      WHERE CAST(snapshot_date AS VARCHAR) = '${to}' AND del_yn = 'N'
    )
    SELECT
      COUNT(*) FILTER (WHERE f.chger_id IS NULL) AS appeared,
      COUNT(*) FILTER (WHERE t.chger_id IS NULL) AS disappeared,
      COUNT(*) FILTER (
        WHERE f.chger_id IS NOT NULL AND t.chger_id IS NOT NULL
          AND f.stat IS DISTINCT FROM t.stat
      ) AS stat_changed
    FROM f
    FULL OUTER JOIN t ON f.stat_id = t.stat_id AND f.chger_id = t.chger_id
  `;
}

// ── 렌더 ──
function renderKpi(trend, health) {
  const first = trend[0];
  const last = trend[trend.length - 1];
  const prev = trend[trend.length - 2] || first;
  $("kpi-obs").textContent = fmtInt(trend.length);
  $("kpi-range").textContent = `${first.d} ~ ${last.d}`;
  $("kpi-latest-total").textContent = fmtInt(last.total);
  $("kpi-latest-delta").textContent = `전 관측 대비 ${fmtSigned(last.total - prev.total)}`;
  $("kpi-net").textContent = fmtSigned(last.total - first.total);
  const lastH = health[health.length - 1];
  const firstH = health[0];
  $("kpi-downtime").textContent = fmtPct(lastH.downtime, 1);
  const trendArrow = lastH.downtime < firstH.downtime ? "개선" : "악화";
  $("kpi-downtime-trend").textContent =
    `기간 시작 ${fmtPct(firstH.downtime, 1)} → ${trendArrow}`;
}

function lineChart(canvasId, labels, datasets) {
  new Chart($(canvasId).getContext("2d"), {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: { y: { beginAtZero: false } },
    },
  });
}

function renderTrend(trend) {
  const labels = trend.map((r) => r.d);
  const ds = (label, key, color, axis) => ({
    label,
    data: trend.map((r) => r[key]),
    borderColor: color,
    backgroundColor: color,
    tension: 0.3,
    yAxisID: axis,
  });
  new Chart($("chart-trend").getContext("2d"), {
    type: "line",
    data: {
      labels,
      datasets: [
        ds("총 충전기", "total", C.primary, "y"),
        ds("급속(DC)", "dc", C.info, "y"),
        ds("즉시 사용 가능", "available", C.purple, "y"),
        ds("운영자 수", "operators", C.warn, "y2"),
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        y: { position: "left", title: { display: true, text: "충전기 수" } },
        y2: {
          position: "right",
          grid: { drawOnChartArea: false },
          title: { display: true, text: "운영자 수" },
        },
      },
      plugins: {
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              const i = items[0].dataIndex;
              if (i === 0) return "(첫 관측 — 증감 없음)";
              const cur = trend[i].total;
              const prev = trend[i - 1].total;
              return `전 관측 대비 총 ${fmtSigned(cur - prev)}`;
            },
          },
        },
      },
    },
  });
}

function renderHealth(health) {
  const labels = health.map((r) => r.d);
  lineChart("chart-health", labels, [
    {
      label: "비가동률 (1/4/5)",
      data: health.map((r) => r.downtime * 100),
      borderColor: C.danger,
      backgroundColor: C.danger,
      tension: 0.3,
    },
    {
      label: "미연동률 (9)",
      data: health.map((r) => r.unmonitored * 100),
      borderColor: C.textDim,
      backgroundColor: C.textDim,
      tension: 0.3,
    },
  ]);
}

function diffCard(label, value, color) {
  const card = makeEl("div", "kpi");
  card.append(
    makeEl("div", "kpi-label", label),
    makeEl("div", "kpi-value", value),
  );
  if (color) card.querySelector(".kpi-value").style.color = color;
  return card;
}

async function renderDiff(conn, from, to) {
  const grid = $("diff-cards");
  grid.textContent = "";
  if (from === to) {
    grid.append(diffCard("안내", "서로 다른 두 날짜를 선택하세요", C.textDim));
    return;
  }
  const [r] = await runQuery(conn, qDiff(from, to));
  const net = r.appeared - r.disappeared;
  grid.append(
    diffCard("신규 등장", fmtSigned(r.appeared), C.primary),
    diffCard("사라짐", fmtSigned(-r.disappeared), C.danger),
    diffCard("상태 변경", fmtInt(r.stat_changed), C.info),
    diffCard("순변화", fmtSigned(net), net >= 0 ? C.primary : C.danger),
  );
}

function fillDateSelects(dates, onChange) {
  for (const id of ["diff-from", "diff-to"]) {
    const sel = $(id);
    for (const d of dates) {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      sel.appendChild(opt);
    }
  }
  // 기본: 처음 → 마지막
  $("diff-from").value = dates[0];
  $("diff-to").value = dates[dates.length - 1];
  $("diff-from").addEventListener("change", onChange);
  $("diff-to").addEventListener("change", onChange);
}

function reveal() {
  $("status").hidden = true;
  for (const id of [
    "header-badge",
    "kpi-grid",
    "trend-title",
    "card-trend",
    "diff-title",
    "card-diff",
    "health-title",
    "card-health",
  ]) {
    const el = $(id);
    if (el) el.hidden = false;
  }
}

// ── 메인 ──
async function main() {
  try {
    const manifest = await loadManifest();
    const dates = manifest.dates || [];
    if (dates.length < 2) {
      throw new Error(
        `시계열 분석에는 2개 이상의 스냅샷이 필요합니다 (현재 ${dates.length}개).`,
      );
    }
    if (manifest.synthetic) {
      $("demo-banner").hidden = false;
      $("demo-banner-text").textContent =
        "⚠️ 합성 데모 데이터입니다 — 실제 추세가 아닙니다. " +
        (manifest.note || "") +
        " 실제 스냅샷이 며칠 쌓이면 같은 페이지가 진짜 데이터로 동작합니다.";
    }

    const db = await initDuckDB();
    const conn = await registerSnapshots(db, dates);

    setStatus("추세 계산 중…");
    const [trend, health] = await Promise.all([
      runQuery(conn, Q_TREND),
      runQuery(conn, Q_HEALTH),
    ]);

    $("snapshot-date").textContent = `${dates[0]} ~ ${dates[dates.length - 1]}`;
    $("row-count").textContent = `${dates.length} 관측`;
    $("header-snapshot").textContent = `${dates.length} 스냅샷`;

    renderKpi(trend, health);
    renderTrend(trend);
    renderHealth(health);

    fillDateSelects(dates, () =>
      renderDiff(conn, $("diff-from").value, $("diff-to").value),
    );
    await renderDiff(conn, dates[0], dates[dates.length - 1]);

    reveal();
  } catch (e) {
    showError(e);
  }
}

main();
