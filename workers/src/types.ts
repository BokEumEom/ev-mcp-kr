/**
 * ChargerInfo TypeScript types + zod schema.
 *
 * Mirrors :class:`ev_mcp.models.ChargerInfo` (Pydantic) in `src/ev_mcp/models.py`
 * 1:1. Internal field names use snake_case to match the SQLite column layout
 * declared in `agent.ts` SCHEMA_STATEMENTS — no upstream alias mapping is
 * needed inside the worker because the sync worker (Stage 4) is responsible
 * for translating data.go.kr's camelCase payload into this shape.
 *
 * Source of truth for field semantics:
 * `한국환경공단_전기자동차 충전소 정보_OpenAPI활용가이드_v1.23.docx` (repo root).
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Status enum (spec v1.23, table §3.4)
// ---------------------------------------------------------------------------

export const CHARGER_STATUS_CODES = [
  "0", // UNKNOWN
  "1", // COMM_ERROR
  "2", // AVAILABLE
  "3", // CHARGING
  "4", // OUT_OF_SERVICE
  "5", // UNDER_MAINTENANCE
  "6", // RESERVED
  "9", // UNVERIFIED
] as const;

export type ChargerStatusCode = (typeof CHARGER_STATUS_CODES)[number];

/**
 * Single row from `getChargerStatus`. Mirrors :class:`ev_mcp.models.ChargerStatusRow`.
 * Datetimes are returned as ISO strings (or null) — see `parseYyyymmddhhmmss`.
 */
export interface ChargerStatusRow {
  busi_id: string;
  stat_id: string;
  chger_id: string;
  stat: ChargerStatusCode;
  stat_upd_dt: string | null;
  last_tsdt: string | null;
  last_tedt: string | null;
  now_tsdt: string | null;
}

/** data.go.kr response header (resultCode/resultMsg/totals). */
export interface ResultHeader {
  result_code: string;
  result_msg: string;
  page_no: number | null;
  num_of_rows: number | null;
  total_count: number | null;
}

const KNOWN_STAT_CODES = new Set<string>(CHARGER_STATUS_CODES);

/**
 * Tolerate undocumented stat codes by demoting to UNKNOWN. Mirrors the
 * Python `_coerce_stat` BeforeValidator — operators occasionally emit "7"/"8"
 * and we never want a single bad row to fail an entire response.
 */
export function coerceStat(v: unknown): ChargerStatusCode {
  if (typeof v === "string" && KNOWN_STAT_CODES.has(v)) {
    return v as ChargerStatusCode;
  }
  return "0";
}

// ---------------------------------------------------------------------------
// Helpers reused for sync-time normalization (Stage 4) and SQLite row mapping
// ---------------------------------------------------------------------------

const DT_STRING_LEN = 14;
const MIN_PLAUSIBLE_YEAR = 2000;

/** "20250507143015" → ISO string. Returns null on sentinel/garbage values. */
export function parseYyyymmddhhmmss(v: unknown): string | null {
  if (v == null) return null;
  if (typeof v !== "string") return null;
  const s = v.trim();
  if (s.length !== DT_STRING_LEN || !/^\d{14}$/.test(s)) {
    return null;
  }
  const year = Number(s.slice(0, 4));
  const month = Number(s.slice(4, 6));
  const day = Number(s.slice(6, 8));
  const hour = Number(s.slice(8, 10));
  const minute = Number(s.slice(10, 12));
  const second = Number(s.slice(12, 14));
  if (year < MIN_PLAUSIBLE_YEAR) return null;
  // Treat upstream timestamps as KST (data.go.kr convention). We store ISO
  // without timezone offset — readers re-attach KST as needed.
  const dt = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
  if (Number.isNaN(dt.getTime())) return null;
  return dt.toISOString();
}

/** Empty / whitespace-only string → null. */
export function emptyToNone(v: unknown): string | null {
  if (typeof v !== "string") return v as string | null;
  return v.trim() === "" ? null : v;
}

/** Empty Y/N flag → "N". */
export function ynDefaultN(v: unknown): string {
  if (typeof v !== "string" || v.trim() === "") return "N";
  return v;
}

// ---------------------------------------------------------------------------
// ChargerInfo schema
// ---------------------------------------------------------------------------

// Zod schema is used by the Stage 4 sync worker to validate raw data.go.kr
// payloads — `.optional()` is needed there because upstream may omit fields.
const optStr = z
  .union([z.string(), z.null()])
  .optional()
  .transform((v) => (v == null || v === "" ? null : v));

const optIso = z.union([z.string(), z.null()]).optional().nullable();

export const chargerInfoSchema = z.object({
  stat_nm: z.string(),
  stat_id: z.string(),
  chger_id: z.string(),
  chger_type: z.string(),
  addr: z.string(),
  addr_detail: optStr,
  location: optStr,
  lat: z.number(),
  lng: z.number(),
  use_time: z.string(),
  busi_id: z.string(),
  bnm: z.string(),
  busi_nm: z.string(),
  busi_call: optStr,
  stat: z.enum(CHARGER_STATUS_CODES),
  stat_upd_dt: optIso,
  last_tsdt: optIso,
  last_tedt: optIso,
  now_tsdt: optIso,
  power_type: optStr,
  output: optStr,
  method: optStr,
  zcode: z.string(),
  zscode: optStr,
  kind: optStr,
  kind_detail: optStr,
  parking_free: optStr,
  note: optStr,
  limit_yn: z.string().default("N"),
  limit_detail: optStr,
  del_yn: z.string().default("N"),
  del_detail: optStr,
  traffic_yn: optStr,
  year: optStr,
  floor_num: optStr,
  floor_type: optStr,
});

// Static type used by the rest of the worker. Kept narrower than `z.infer<>`
// so that nullable fields are exactly `string | null` (never `undefined`).
// The DO write path needs concrete null bindings for SQLite parameters.
export interface ChargerInfo {
  stat_nm: string;
  stat_id: string;
  chger_id: string;
  chger_type: string;
  addr: string;
  addr_detail: string | null;
  location: string | null;
  lat: number;
  lng: number;
  use_time: string;
  busi_id: string;
  bnm: string;
  busi_nm: string;
  busi_call: string | null;
  stat: ChargerStatusCode;
  stat_upd_dt: string | null;
  last_tsdt: string | null;
  last_tedt: string | null;
  now_tsdt: string | null;
  power_type: string | null;
  output: string | null;
  method: string | null;
  zcode: string;
  zscode: string | null;
  kind: string | null;
  kind_detail: string | null;
  parking_free: string | null;
  note: string | null;
  limit_yn: string;
  limit_detail: string | null;
  del_yn: string;
  del_detail: string | null;
  traffic_yn: string | null;
  year: string | null;
  floor_num: string | null;
  floor_type: string | null;
}

// ---------------------------------------------------------------------------
// SQLite row → ChargerInfo
// ---------------------------------------------------------------------------

/** Shape of a row returned by the DO SQLite query helper. */
export type ChargerRow = Record<string, string | number | boolean | null>;

const STR = (v: unknown): string => (typeof v === "string" ? v : "");
const OPT_STR = (v: unknown): string | null =>
  typeof v === "string" && v !== "" ? v : null;
const NUM = (v: unknown): number => (typeof v === "number" ? v : Number(v));

export function rowToChargerInfo(row: ChargerRow): ChargerInfo {
  return {
    stat_nm: STR(row["stat_nm"]),
    stat_id: STR(row["stat_id"]),
    chger_id: STR(row["chger_id"]),
    chger_type: STR(row["chger_type"]),
    addr: STR(row["addr"]),
    addr_detail: OPT_STR(row["addr_detail"]),
    location: OPT_STR(row["location"]),
    lat: NUM(row["lat"]),
    lng: NUM(row["lng"]),
    use_time: STR(row["use_time"]),
    busi_id: STR(row["busi_id"]),
    bnm: STR(row["bnm"]),
    busi_nm: STR(row["busi_nm"]),
    busi_call: OPT_STR(row["busi_call"]),
    stat: coerceStat(row["stat"]),
    stat_upd_dt: OPT_STR(row["stat_upd_dt"]),
    last_tsdt: OPT_STR(row["last_tsdt"]),
    last_tedt: OPT_STR(row["last_tedt"]),
    now_tsdt: OPT_STR(row["now_tsdt"]),
    power_type: OPT_STR(row["power_type"]),
    output: OPT_STR(row["output"]),
    method: OPT_STR(row["method"]),
    zcode: STR(row["zcode"]),
    zscode: OPT_STR(row["zscode"]),
    kind: OPT_STR(row["kind"]),
    kind_detail: OPT_STR(row["kind_detail"]),
    parking_free: OPT_STR(row["parking_free"]),
    note: OPT_STR(row["note"]),
    limit_yn: STR(row["limit_yn"]) || "N",
    limit_detail: OPT_STR(row["limit_detail"]),
    del_yn: STR(row["del_yn"]) || "N",
    del_detail: OPT_STR(row["del_detail"]),
    traffic_yn: OPT_STR(row["traffic_yn"]),
    year: OPT_STR(row["year"]),
    floor_num: OPT_STR(row["floor_num"]),
    floor_type: OPT_STR(row["floor_type"]),
  };
}
