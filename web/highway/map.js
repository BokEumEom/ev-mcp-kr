// 고속도로 휴게소 지도 — Leaflet + DuckDB-WASM.
// 622곳 휴게소 마커. 색상=평균 출력, 크기=충전기 수. 노선 필터 + 클릭 popup.

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";
// Leaflet 은 UMD 로 index.html 에서 미리 로드됨 → window.L 사용

const PARQUET_URL = "/scratch/chargers_snapshot.parquet";
const SIDO_URL = "/src/ev_mcp/codes/sido.json";
const BUSI_URL = "/src/ev_mcp/codes/busi_id.json";

const DC_CODES = ["01", "03", "04", "05", "06", "08", "09", "10"];

// 한반도 중앙 기준 초기 view
const INIT_CENTER = [36.5, 127.8];
const INIT_ZOOM = 7;

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

const fmtInt = (n) => Number(n).toLocaleString("ko-KR");
const fmtPct = (p, d = 1) => (Number(p) * 100).toFixed(d) + "%";
const fmtNum = (n, d = 1) => Number(n).toFixed(d);

function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

// ─── 마커 스타일 매핑 ───

const PALETTE = {
  fast: "#6ee7b7",   // 200+ kW
  mid: "#fcd34d",    // 100~200
  slow: "#7dd3fc",   // 50~100
  low: "#8b95a4",    // ≤50
};

function colorByKw(kw) {
  if (kw == null) return PALETTE.low;
  if (kw >= 200) return PALETTE.fast;
  if (kw >= 100) return PALETTE.mid;
  if (kw >= 50) return PALETTE.slow;
  return PALETTE.low;
}

function radiusByCount(n) {
  // log scale — 1대=5px, 10대=~11px, 50대=~16px, 100대=~18px
  return Math.max(5, Math.round(Math.log2(n + 1) * 3 + 3));
}

// ─── DuckDB-WASM 초기화 ───
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

// 휴게소 단위 — addr 에서 고속도로 이름 정규식 추출
const Q_STATIONS = `
  SELECT
    stat_id,
    ANY_VALUE(stat_nm)                                                          AS stat_nm,
    ANY_VALUE(lat)                                                              AS lat,
    ANY_VALUE(lng)                                                              AS lng,
    ANY_VALUE(addr)                                                             AS addr,
    ANY_VALUE(zcode)                                                            AS zcode,
    ANY_VALUE(regexp_extract(addr, '([가-힣]+고속도로)', 1))                        AS highway,
    COUNT(*)                                                                    AS chargers,
    AVG(TRY_CAST(output AS DOUBLE))                                             AS avg_kw,
    AVG(CASE WHEN chger_type IN (${inList(DC_CODES)}) THEN 1.0 ELSE 0.0 END)    AS dc_ratio,
    COUNT(DISTINCT busi_id)                                                     AS operators,
    MAX(stat_upd_dt)                                                            AS latest_upd
  FROM 'chargers.parquet'
  WHERE del_yn = 'N'
    AND kind_detail = 'C001'
    AND lat BETWEEN 33 AND 39
    AND lng BETWEEN 124 AND 132
  GROUP BY stat_id
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
  const [sido, busi] = await Promise.all([
    fetch(SIDO_URL).then((r) => r.json()),
    fetch(BUSI_URL).then((r) => r.json()),
  ]);
  return { sido, busi };
}

// ─── 지도 + 마커 ───

function buildMap() {
  const map = L.map("map", {
    center: INIT_CENTER,
    zoom: INIT_ZOOM,
    minZoom: 6,
    maxZoom: 16,
    zoomControl: true,
    attributionControl: false, // footer 에서 별도 표시
  });

  // 다크 모드와 어울리는 OSM 변형 타일 (CARTO Dark Matter)
  L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    {
      maxZoom: 19,
      subdomains: "abcd",
    },
  ).addTo(map);

  return map;
}

function buildPopupHtml(s, codes) {
  const sido = codes.sido[s.zcode] || s.zcode || "";
  const detailUrl = `./station.html?id=${encodeURIComponent(s.stat_id)}`;
  const lines = [
    `<div class="popup-title">${escapeHtml(s.stat_nm || s.stat_id)}</div>`,
    `<div class="popup-meta">${escapeHtml(sido)}${s.highway ? " · " + escapeHtml(s.highway) : ""}</div>`,
    `<div class="popup-row"><span>충전기</span><b>${fmtInt(s.chargers)}대</b></div>`,
    `<div class="popup-row"><span>평균 출력</span><b>${fmtNum(s.avg_kw || 0, 1)} kW</b></div>`,
    `<div class="popup-row"><span>DC 비율</span><b>${fmtPct(s.dc_ratio || 0)}</b></div>`,
    `<div class="popup-row"><span>운영자</span><b>${s.operators}곳</b></div>`,
    s.addr
      ? `<div class="popup-addr">${escapeHtml(s.addr)}</div>`
      : "",
    `<div class="popup-action"><a href="${detailUrl}">상세 보기 →</a></div>`,
  ];
  return lines.join("");
}

// XSS 방지 — popup 은 unfortunately innerHTML 형태가 Leaflet API 라 escape 필요
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function plotMarkers(map, stations, codes) {
  const group = L.layerGroup();
  for (const s of stations) {
    if (s.lat == null || s.lng == null) continue;
    const marker = L.circleMarker([s.lat, s.lng], {
      radius: radiusByCount(s.chargers),
      color: colorByKw(s.avg_kw),
      fillColor: colorByKw(s.avg_kw),
      fillOpacity: 0.55,
      weight: 1.5,
      opacity: 0.9,
    });
    marker.bindPopup(buildPopupHtml(s, codes), {
      className: "highway-popup",
      maxWidth: 280,
    });
    marker.bindTooltip(s.stat_nm || s.stat_id, { direction: "top", offset: [0, -4] });
    group.addLayer(marker);
  }
  group.addTo(map);
  return group;
}

// ─── 통계 미니 카드 갱신 ───

function updateStats(stations) {
  const total = stations.length;
  const n200 = stations.filter((s) => (s.avg_kw || 0) >= 200).length;
  const kwSum = stations.reduce((a, s) => a + (s.avg_kw || 0), 0);
  $("visible-count").textContent = fmtInt(total) + "곳";
  $("visible-200plus").textContent =
    fmtInt(n200) + " (" + fmtPct(n200 / Math.max(total, 1), 1) + ")";
  $("visible-avg-kw").textContent =
    fmtNum(kwSum / Math.max(total, 1), 1) + " kW";
}

// ─── 노선 필터 ───

// addr 에서 노선명이 추출 안 된 휴게소. 이전엔 드롭다운에서 빠져 "전체" 에서만
// 보이고 노선 필터로는 영영 못 봤다 → 명시적 항목으로 노출.
const UNKNOWN_HW = "(노선 미확인)";

function populateHighwayFilter(stations) {
  const counts = new Map();
  for (const s of stations) {
    const key = s.highway || UNKNOWN_HW;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const select = $("highway-select");
  for (const [hw, n] of sorted) {
    const opt = document.createElement("option");
    opt.value = hw;
    opt.textContent = `${hw} (${n})`;
    select.appendChild(opt);
  }
}

// ─── 메인 ───
async function main() {
  try {
    if (location.protocol === "file:") {
      throw new Error(
        "file:// 로 열렸습니다. cd /home/bokeum/ai/ev_mcp && python -m http.server 8000",
      );
    }
    if (typeof L === "undefined") {
      throw new Error("Leaflet 라이브러리 로드 실패. 인터넷 연결 확인.");
    }

    const db = await initDuckDB();
    const conn = await db.connect();

    setStatus("휴게소 위치 불러오는 중…");
    const [codes, stations] = await Promise.all([
      loadCodes(),
      runQuery(conn, Q_STATIONS),
    ]);

    // 헤더 메타
    if (stations[0]?.latest_upd) {
      const d = String(stations[0].latest_upd).slice(0, 10);
      $("snapshot-date").textContent = `스냅샷 ${d}`;
      $("header-snapshot").textContent = `${d} 기준 ${fmtInt(stations.length)}곳`;
    }
    $("row-count").textContent = fmtInt(stations.length) + " stations";

    // UI reveal
    $("status").hidden = true;
    $("map-controls").hidden = false;
    $("map-wrap").hidden = false;
    $("header-badge").hidden = false;

    // 지도 빌드 (DOM 보인 후)
    const map = buildMap();

    let layer = plotMarkers(map, stations, codes);
    updateStats(stations);
    populateHighwayFilter(stations);

    // 노선 필터 변경 시 다시 그리기
    $("highway-select").addEventListener("change", (e) => {
      const hw = e.target.value;
      const filtered = hw
        ? stations.filter((s) => (s.highway || UNKNOWN_HW) === hw)
        : stations;
      map.removeLayer(layer);
      layer = plotMarkers(map, filtered, codes);
      updateStats(filtered);
      if (filtered.length > 0 && hw) {
        const bounds = L.latLngBounds(filtered.map((s) => [s.lat, s.lng]));
        map.fitBounds(bounds, { padding: [40, 40] });
      } else {
        map.setView(INIT_CENTER, INIT_ZOOM);
      }
    });

    await conn.close();
  } catch (e) {
    showError(e);
  }
}

main();
