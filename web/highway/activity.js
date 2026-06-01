// 고속도로 충전 활성도 — last_tsdt 기반 시간 패턴 / 인기 / 휴면 분석.

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";
// Chart.js 는 HTML 에서 UMD 로 미리 로드

const PARQUET_URL = "/scratch/chargers_snapshot.parquet";
const SIDO_URL = "/src/ev_mcp/codes/sido.json";

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
    "time-title",
    "card-hour",
    "turnover-title",
    "card-turnover",
    "highway-title",
    "card-highway",
    "dormant-title",
    "card-dormant-buckets",
    "card-dormant-highway",
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

const HW_FILTER = `del_yn = 'N' AND kind_detail = 'C001'`;

// 스냅샷 시점은 max(stat_upd_dt) 사용 — 활성도 계산 기준
const Q_KPI = `
  WITH p AS (
    SELECT TRY_CAST(last_tsdt AS TIMESTAMP) ts, stat
    FROM 'chargers.parquet'
    WHERE ${HW_FILTER}
  ),
  base AS (
    SELECT
      (SELECT MAX(TRY_CAST(stat_upd_dt AS TIMESTAMP)) FROM 'chargers.parquet' WHERE ${HW_FILTER}) AS now_ts,
      ts, stat FROM p
  )
  SELECT
    COUNT(*) AS total_all,
    SUM(CASE WHEN ts IS NOT NULL THEN 1 ELSE 0 END) AS total_with_ts,
    SUM(CASE WHEN ts IS NOT NULL AND now_ts - ts < INTERVAL '1 day' THEN 1 ELSE 0 END) AS active_1d,
    SUM(CASE WHEN ts IS NOT NULL AND now_ts - ts < INTERVAL '7 days' THEN 1 ELSE 0 END) AS active_7d,
    SUM(CASE WHEN ts IS NOT NULL AND now_ts - ts < INTERVAL '30 days' THEN 1 ELSE 0 END) AS active_30d,
    SUM(CASE WHEN ts IS NOT NULL AND now_ts - ts > INTERVAL '60 days' THEN 1 ELSE 0 END) AS dormant_60d,
    SUM(CASE WHEN stat = '3' THEN 1 ELSE 0 END) AS now_charging,
    MAX(now_ts) AS snapshot_ts
  FROM base
`;

const Q_HOUR = `
  SELECT EXTRACT(HOUR FROM TRY_CAST(last_tsdt AS TIMESTAMP)) AS hour,
         COUNT(*) AS cnt
  FROM 'chargers.parquet'
  WHERE ${HW_FILTER} AND last_tsdt IS NOT NULL
  GROUP BY hour ORDER BY hour
`;

// 섹션 1: 출력대별 평균 충전 시간 (회전율) — last_tedt - last_tsdt
const Q_TURNOVER = `
  WITH base AS (
    SELECT
      TRY_CAST(output AS DOUBLE) AS kw,
      DATE_DIFF('minute',
        TRY_CAST(last_tsdt AS TIMESTAMP),
        TRY_CAST(last_tedt AS TIMESTAMP)
      ) AS dur_min
    FROM 'chargers.parquet'
    WHERE ${HW_FILTER}
      AND last_tsdt IS NOT NULL AND last_tedt IS NOT NULL
  )
  SELECT
    CASE
      WHEN kw <= 50  THEN 'A_le50'
      WHEN kw <= 100 THEN 'B_51to100'
      WHEN kw <= 200 THEN 'C_101to200'
      WHEN kw <= 350 THEN 'D_201to350'
      ELSE                'E_350plus'
    END AS bucket,
    AVG(dur_min)    AS avg_min,
    MEDIAN(dur_min) AS med_min,
    COUNT(*)        AS cnt
  FROM base
  WHERE dur_min BETWEEN 1 AND 600
  GROUP BY bucket ORDER BY bucket
`;

// 섹션 2: 노선별 평균 활성도 (작을수록 활성)
const Q_HIGHWAY_ACTIVITY = `
  WITH p AS (
    SELECT
      regexp_extract(addr, '([가-힣]+고속도로)', 1) AS hw,
      DATE_DIFF('day',
        TRY_CAST(last_tsdt AS TIMESTAMP),
        (SELECT MAX(TRY_CAST(stat_upd_dt AS TIMESTAMP))
         FROM 'chargers.parquet' WHERE ${HW_FILTER})
      ) AS days_since
    FROM 'chargers.parquet'
    WHERE ${HW_FILTER} AND last_tsdt IS NOT NULL
  )
  SELECT
    hw,
    AVG(days_since) AS avg_days,
    COUNT(*)        AS cnt
  FROM p
  WHERE hw != '' AND days_since IS NOT NULL AND days_since >= 0
  GROUP BY hw
  HAVING COUNT(*) >= 20
  ORDER BY avg_days ASC
  LIMIT 12
`;

// 섹션 3a: 휴면 기간별 분포 (60+일)
const Q_DORMANT_BUCKETS = `
  WITH base AS (
    SELECT DATE_DIFF('day',
      TRY_CAST(last_tsdt AS TIMESTAMP),
      (SELECT MAX(TRY_CAST(stat_upd_dt AS TIMESTAMP))
       FROM 'chargers.parquet' WHERE ${HW_FILTER})
    ) AS days_since
    FROM 'chargers.parquet'
    WHERE ${HW_FILTER} AND last_tsdt IS NOT NULL
  )
  SELECT
    CASE
      WHEN days_since BETWEEN 60 AND 90    THEN 'A_60_90'
      WHEN days_since BETWEEN 91 AND 180   THEN 'B_91_180'
      WHEN days_since BETWEEN 181 AND 365  THEN 'C_181_365'
      WHEN days_since > 365                THEN 'D_365plus'
    END AS bucket,
    COUNT(*) AS cnt
  FROM base
  WHERE days_since > 60
  GROUP BY bucket
  HAVING bucket IS NOT NULL
  ORDER BY bucket
`;

// 섹션 3b: 노선별 휴면 충전기 ranking
const Q_DORMANT_BY_HIGHWAY = `
  WITH base AS (
    SELECT
      regexp_extract(addr, '([가-힣]+고속도로)', 1) AS hw,
      last_tsdt,
      (SELECT MAX(TRY_CAST(stat_upd_dt AS TIMESTAMP))
       FROM 'chargers.parquet' WHERE ${HW_FILTER}) AS now_ts
    FROM 'chargers.parquet'
    WHERE ${HW_FILTER}
  )
  SELECT hw,
    SUM(CASE
      WHEN last_tsdt IS NOT NULL
      AND now_ts - TRY_CAST(last_tsdt AS TIMESTAMP) > INTERVAL '60 days'
      THEN 1 ELSE 0 END) AS dormant,
    COUNT(*) AS total
  FROM base
  WHERE hw != ''
  GROUP BY hw
  HAVING dormant > 0
  ORDER BY dormant DESC
  LIMIT 8
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
  const sido = await fetch(SIDO_URL).then((r) => r.json());
  return { sido };
}

const shortSido = (s) =>
  (s || "").replace(/특별자치(도|시)$/, "").replace(/광역시$/, "");
const shortHighway = (h) => (h || "").replace(/고속도로$/, "");

// ─── 렌더 ───

function renderKpi(kpi) {
  const total = Number(kpi.total_with_ts);
  $("kpi-total").textContent = fmtInt(total);
  $("kpi-1d").textContent = fmtInt(kpi.active_1d);
  $("kpi-1d-sub").textContent = fmtPct(kpi.active_1d / total, 1);
  $("kpi-7d").textContent = fmtInt(kpi.active_7d);
  $("kpi-7d-sub").textContent = fmtPct(kpi.active_7d / total, 1);
  $("kpi-30d").textContent = fmtInt(kpi.active_30d);
  $("kpi-30d-sub").textContent = fmtPct(kpi.active_30d / total, 1);
  $("kpi-dormant").textContent = fmtInt(kpi.dormant_60d);
  $("kpi-dormant-sub").textContent =
    fmtPct(kpi.dormant_60d / total, 1) + " · 관리 필요";
  $("kpi-now").textContent = fmtInt(kpi.now_charging);

  if (kpi.snapshot_ts) {
    const d = String(kpi.snapshot_ts).slice(0, 10);
    $("snapshot-date").textContent = `스냅샷 ${d}`;
    $("header-snapshot").textContent = `${d} · ${fmtInt(total)} 활성 데이터`;
  }
  $("row-count").textContent = fmtInt(total) + " rows";
}

function renderInsights(kpi, hourDist, turnover, highwayAct, dormantBuckets) {
  const grid = $("insight-grid");
  grid.textContent = "";

  const total = Number(kpi.total_with_ts);
  const insights = [];

  // 1) 활성도 매우 높음
  insights.push({
    color: "info",
    headline: fmtPct(kpi.active_7d / total, 1),
    title: "7일 내 사용 — 매우 활성",
    body: `${fmtInt(kpi.active_7d)}대가 최근 7일 내 충전. 고속도로 충전 인프라는 죽어있지 않다.`,
  });

  // 2) 시간대 피크
  const peakHour = hourDist.reduce((a, b) => (b.cnt > a.cnt ? b : a));
  insights.push({
    color: "default",
    headline: peakHour.hour + "시",
    title: "가장 바쁜 시간",
    body: `${fmtInt(peakHour.cnt)}건 충전. 점심(11~16시) 이 ${fmtPct(hourDist.filter((h) => h.hour >= 11 && h.hour < 16).reduce((s, h) => s + h.cnt, 0) / total, 0)} 차지.`,
  });

  // 3) 회전율 — 초급속 vs AC
  const slowest = turnover.find((b) => b.bucket === "A_le50");
  const fastest =
    turnover.find((b) => b.bucket === "E_350plus") ||
    turnover.find((b) => b.bucket === "D_201to350");
  if (slowest && fastest) {
    const factor = slowest.avg_min / fastest.avg_min;
    insights.push({
      color: "purple",
      headline: fmtNum(fastest.avg_min, 0) + "분",
      title: `초급속 평균 회전 시간`,
      body: `${slowest.bucket === "A_le50" ? "AC완속(≤50kW)" : "저출력"} 평균 ${fmtNum(slowest.avg_min, 1)}분 vs 고출력 ${fmtNum(fastest.avg_min, 1)}분 — ${fmtNum(factor, 1)}× 빠른 회전.`,
    });
  }

  // 4) 가장 활성 노선
  if (highwayAct.length > 0) {
    const top = highwayAct[0];
    insights.push({
      color: "default",
      headline: shortHighway(top.hw),
      title: "가장 자주 쓰이는 노선",
      body: `${top.hw} — 충전기 ${fmtInt(top.cnt)}대 평균 마지막 사용 후 ${fmtNum(top.avg_days, 1)}일 경과. 최단 인터벌 = 가장 활성.`,
    });
  }

  // 5) 휴면의 심각도 — 90일+ 비율
  const totalDormant = dormantBuckets.reduce((s, b) => s + b.cnt, 0);
  const veryDormant = dormantBuckets
    .filter((b) => b.bucket === "C_181_365" || b.bucket === "D_365plus")
    .reduce((s, b) => s + b.cnt, 0);
  if (totalDormant > 0) {
    insights.push({
      color: "warn",
      headline: fmtPct(veryDormant / totalDormant, 0),
      title: "휴면 충전기 중 180일+ 방치",
      body: `60일+ 휴면 ${totalDormant}대 중 ${veryDormant}대(${fmtPct(veryDormant / totalDormant, 0)})가 6개월 이상 미사용. 사실상 방치 상태.`,
    });
  }

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

function renderHour(rows) {
  // 빈 시간대를 0 으로 채우기
  const filled = Array.from({ length: 24 }, (_, h) => ({
    hour: h,
    cnt: rows.find((r) => Number(r.hour) === h)?.cnt || 0,
  }));
  new Chart($("chart-hour").getContext("2d"), {
    type: "bar",
    data: {
      labels: filled.map((r) => r.hour + "시"),
      datasets: [{
        label: "충전 발생 건수",
        data: filled.map((r) => r.cnt),
        backgroundColor: filled.map((r) => {
          if (r.hour >= 11 && r.hour < 16) return C.primary;
          if (r.hour >= 6 && r.hour < 11) return C.info;
          if (r.hour >= 16 && r.hour < 22) return C.amber;
          return C.purple;
        }),
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
            label: (ctx) => `${fmtInt(ctx.parsed.y)}대`,
          },
        },
      },
    },
  });
}

// ─── 섹션 1: 회전율 (출력대별 평균 충전 시간) ───
function renderTurnover(rows) {
  const LABEL = {
    A_le50: "≤50 kW",
    B_51to100: "51~100 kW",
    C_101to200: "101~200 kW",
    D_201to350: "201~350 kW",
    E_350plus: "350+ kW",
  };
  const COLOR = {
    A_le50: C.info,
    B_51to100: C.amber,
    C_101to200: C.purple,
    D_201to350: C.primary,
    E_350plus: C.lime,
  };
  new Chart($("chart-turnover").getContext("2d"), {
    type: "bar",
    data: {
      labels: rows.map((r) => LABEL[r.bucket] || r.bucket),
      datasets: [{
        label: "평균 충전 시간 (분)",
        data: rows.map((r) => Number(r.avg_min)),
        backgroundColor: rows.map((r) => COLOR[r.bucket] || C.textDim),
        borderWidth: 0,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          beginAtZero: true,
          title: { display: true, text: "평균 충전 시간 (분) — last_tedt - last_tsdt", color: C.textDim },
          ticks: { callback: (v) => v + "분" },
          grid: { color: C.grid },
        },
        y: { grid: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody: (ctx) => {
              const r = rows[ctx[0].dataIndex];
              return [
                `중앙값: ${fmtNum(r.med_min, 0)}분`,
                `샘플 수: ${fmtInt(r.cnt)}대`,
              ];
            },
          },
        },
      },
    },
  });
}

// ─── 섹션 2: 노선별 평균 활성도 ───
function renderHighwayActivity(rows) {
  const labels = rows.map((r) => shortHighway(r.hw));
  new Chart($("chart-highway").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "평균 마지막 사용 후 일수",
        data: rows.map((r) => Number(r.avg_days)),
        backgroundColor: rows.map((r, i) =>
          i === 0 ? C.primary : Number(r.avg_days) < 1 ? C.info : C.purple,
        ),
        borderWidth: 0,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          beginAtZero: true,
          title: { display: true, text: "평균 일수 (작을수록 활성)", color: C.textDim },
          ticks: { callback: (v) => fmtNum(v, 1) + "일" },
          grid: { color: C.grid },
        },
        y: { grid: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody: (ctx) => {
              const r = rows[ctx[0].dataIndex];
              return [
                `노선 전체: ${r.hw}`,
                `충전기 수: ${fmtInt(r.cnt)}대`,
                `평균: ${fmtNum(r.avg_days, 2)}일`,
              ];
            },
          },
        },
      },
    },
  });
}

// ─── 섹션 3a: 휴면 기간별 분포 (도넛) ───
function renderDormantBuckets(rows) {
  const LABEL = {
    A_60_90: "60~90일",
    B_91_180: "91~180일",
    C_181_365: "181~365일",
    D_365plus: "365일+ (1년 이상)",
  };
  const COLOR = {
    A_60_90: C.amber,
    B_91_180: C.warn,
    C_181_365: "#fb923c",
    D_365plus: C.danger,
  };
  const labels = rows.map((r) => LABEL[r.bucket] || r.bucket);
  const data = rows.map((r) => r.cnt);
  const colors = rows.map((r) => COLOR[r.bucket] || C.textDim);
  const total = data.reduce((a, b) => a + b, 0);

  new Chart($("chart-dormant-buckets").getContext("2d"), {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: colors,
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
              `${ctx.label}: ${fmtInt(ctx.parsed)}대 (${fmtPct(ctx.parsed / total)})`,
          },
        },
      },
    },
  });
}

// ─── 섹션 3b: 노선별 휴면 ranking ───
function renderDormantByHighway(rows) {
  const labels = rows.map((r) => shortHighway(r.hw));
  new Chart($("chart-dormant-highway").getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "휴면(60일+)",
          data: rows.map((r) => r.dormant),
          backgroundColor: C.warn,
          borderWidth: 0,
        },
        {
          label: "정상",
          data: rows.map((r) => r.total - r.dormant),
          backgroundColor: C.grid,
          borderWidth: 0,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { beginAtZero: true, stacked: true, ticks: { callback: (v) => fmtInt(v) }, grid: { color: C.grid } },
        y: { stacked: true, grid: { display: false } },
      },
      plugins: {
        legend: { labels: { color: C.text, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            afterBody: (ctx) => {
              const r = rows[ctx[0].dataIndex];
              return [
                `${r.hw}`,
                `휴면 비율: ${fmtPct(r.dormant / r.total)}`,
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
      throw new Error("file:// 로 열렸습니다. python -m http.server 실행 후 접속.");
    }
    if (typeof Chart === "undefined") {
      throw new Error("Chart.js 로드 실패.");
    }
    const db = await initDuckDB();
    const conn = await db.connect();

    setStatus("활성도 통계 계산 중…");
    const [
      codes,
      [kpi],
      hourDist,
      turnover,
      highwayAct,
      dormantBuckets,
      dormantByHw,
    ] = await Promise.all([
      loadCodes(),
      runQuery(conn, Q_KPI),
      runQuery(conn, Q_HOUR),
      runQuery(conn, Q_TURNOVER),
      runQuery(conn, Q_HIGHWAY_ACTIVITY),
      runQuery(conn, Q_DORMANT_BUCKETS),
      runQuery(conn, Q_DORMANT_BY_HIGHWAY),
    ]);

    renderKpi(kpi);
    renderInsights(kpi, hourDist, turnover, highwayAct, dormantBuckets);
    renderHour(hourDist);
    renderTurnover(turnover);
    renderHighwayActivity(highwayAct);
    renderDormantBuckets(dormantBuckets);
    renderDormantByHighway(dormantByHw);

    revealAll();
    await conn.close();
  } catch (e) {
    showError(e);
  }
}

main();
